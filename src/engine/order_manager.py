"""Order state machine and order lifecycle management."""

import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger

from src.broker.kis_client import KISClient
from src.broker.kis_models import (
    OrderInfo,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
)


class OrderManager:
    """Manages order lifecycle with FSM state transitions.

    State machine:
        PENDING → SUBMITTED → PARTIAL_FILL → FILLED
                          ↘ REJECTED          ↗
                            CANCELLED / FAILED
    """

    def __init__(self, client: KISClient):
        self.client = client
        self._orders: dict[str, OrderInfo] = {}
        self._callbacks: list = []
        self._lock = asyncio.Lock()

    @property
    def open_orders(self) -> list[OrderInfo]:
        return [
            o for o in self._orders.values()
            if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILL)
        ]

    @property
    def filled_orders(self) -> list[OrderInfo]:
        return [o for o in self._orders.values() if o.status == OrderStatus.FILLED]

    def get_order(self, order_id: str) -> Optional[OrderInfo]:
        return self._orders.get(order_id)

    def on_order_update(self, callback) -> None:
        """Register callback for order state changes."""
        self._callbacks.append(callback)

    async def submit_order(
        self,
        stock_code: str,
        side: OrderSide,
        quantity: int,
        price: int = 0,
        order_type: OrderType = OrderType.MARKET,
        strategy_name: str = "",
    ) -> OrderInfo:
        """Submit a new order to KIS API."""
        async with self._lock:
            req = OrderRequest(
                stock_code=stock_code,
                side=side,
                quantity=quantity,
                price=price,
                order_type=order_type,
            )

            # Create local order record
            order = OrderInfo(
                order_id="",
                stock_code=stock_code,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                status=OrderStatus.PENDING,
                strategy_name=strategy_name,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            resp: OrderResponse = await self.client.place_order(req)

            if resp.success:
                order.order_id = resp.order_number
                order.status = OrderStatus.SUBMITTED
                self._orders[order.order_id] = order
                logger.info(
                    f"주문 접수: {stock_code} {side.value} {quantity}주 "
                    f"order_id={order.order_id}"
                )
            else:
                order.order_id = f"FAILED_{datetime.now().strftime('%H%M%S%f')}"
                order.status = OrderStatus.REJECTED
                self._orders[order.order_id] = order
                logger.warning(
                    f"주문 거부: {stock_code} {side.value} - {resp.message}"
                )

            await self._notify(order)
            return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        order = self._orders.get(order_id)
        if not order:
            logger.warning(f"주문 없음: {order_id}")
            return False

        if order.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILL):
            logger.warning(f"취소 불가 상태: {order_id} status={order.status}")
            return False

        remaining = order.quantity - order.filled_quantity
        resp = await self.client.cancel_order(order_id, order.stock_code, remaining)

        if resp.success:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now()
            logger.info(f"주문 취소: {order_id}")
            await self._notify(order)
            return True

        logger.warning(f"주문 취소 실패: {order_id} - {resp.message}")
        return False

    async def cancel_all_open(self) -> int:
        """Cancel all open orders. Returns number cancelled."""
        cancelled = 0
        for order in list(self.open_orders):
            if await self.cancel_order(order.order_id):
                cancelled += 1
        return cancelled

    def update_from_execution(
        self, order_id: str, filled_qty: int, filled_price: float
    ) -> Optional[OrderInfo]:
        """Update order state from execution notice."""
        order = self._orders.get(order_id)
        if not order:
            return None

        order.filled_quantity = filled_qty
        order.filled_price = filled_price
        order.updated_at = datetime.now()

        if order.filled_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIAL_FILL

        logger.info(
            f"체결 업데이트: {order.stock_code} {order.side.value} "
            f"{filled_qty}/{order.quantity}주 @{filled_price}"
        )
        return order

    async def _notify(self, order: OrderInfo) -> None:
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(order)
                else:
                    cb(order)
            except Exception as e:
                logger.error(f"주문 콜백 오류: {e}")
