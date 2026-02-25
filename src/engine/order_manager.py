"""Order state machine and order lifecycle management."""

import asyncio
from datetime import datetime
from decimal import Decimal
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

    def __init__(self, client: KISClient, enable_db: bool = True):
        self.client = client
        self._orders: dict[str, OrderInfo] = {}
        self._callbacks: list = []
        self._lock = asyncio.Lock()
        self._enable_db = enable_db

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
        max_retries: int = 0,
    ) -> OrderInfo:
        """Submit a new order to KIS API.

        매도(SELL) 주문은 max_retries=3이 기본.
        매수(BUY)는 재시도 안 함 (중복 매수 방지).
        """
        # 매도 주문은 자동 재시도 (안 팔리면 큰일이니까)
        if side == OrderSide.SELL and max_retries == 0:
            max_retries = 3

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

            last_error = ""
            for attempt in range(max_retries + 1):
                resp: OrderResponse = await self.client.place_order(req)

                if resp.success:
                    order.order_id = resp.order_number
                    order.status = OrderStatus.SUBMITTED
                    self._orders[order.order_id] = order
                    logger.info(
                        f"주문 접수: {stock_code} {side.value} {quantity}주 "
                        f"order_id={order.order_id}"
                    )
                    break
                else:
                    last_error = resp.message
                    if attempt < max_retries:
                        wait = 3 * (attempt + 1)
                        logger.warning(
                            f"주문 실패 ({attempt+1}/{max_retries+1}): "
                            f"{stock_code} {side.value} - {last_error}, "
                            f"{wait}초 후 재시도"
                        )
                        await asyncio.sleep(wait)
                    else:
                        order.order_id = f"FAILED_{datetime.now().strftime('%H%M%S%f')}"
                        order.status = OrderStatus.REJECTED
                        self._orders[order.order_id] = order
                        logger.warning(
                            f"주문 거부 (최종): {stock_code} {side.value} - {last_error}"
                        )

            self._save_order_to_db(order)
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

        prev_filled = order.filled_quantity
        prev_price = order.filled_price

        # 부분체결 누적 (덮어쓰기 X)
        order.filled_quantity = prev_filled + filled_qty

        # 가중평균 체결가
        if order.filled_quantity > 0:
            order.filled_price = (
                (prev_price * prev_filled + filled_price * filled_qty)
                / order.filled_quantity
            )

        order.updated_at = datetime.now()

        if order.filled_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIAL_FILL

        logger.info(
            f"체결 업데이트: {order.stock_code} {order.side.value} "
            f"{order.filled_quantity}/{order.quantity}주 @{filled_price} "
            f"(이번 {filled_qty}주, 누적 {order.filled_quantity}주)"
        )

        self._update_order_in_db(order)
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

    # ── DB Persistence Helpers ─────────────────────────────

    def _save_order_to_db(self, order: OrderInfo) -> None:
        if not self._enable_db:
            return
        try:
            from src.database.connection import get_session
            from src.database.repositories import LiveOrderRepository

            with get_session() as session:
                repo = LiveOrderRepository(session)
                repo.upsert({
                    "order_id": order.order_id,
                    "stock_code": order.stock_code,
                    "strategy_name": order.strategy_name,
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "price": Decimal(str(order.price)),
                    "status": order.status.value,
                    "filled_quantity": order.filled_quantity,
                    "filled_price": Decimal(str(order.filled_price)),
                    "created_at": order.created_at or datetime.now(),
                    "updated_at": datetime.now(),
                })
        except Exception as e:
            logger.warning(f"주문 DB 저장 실패 (주문 실행은 계속): {e}")

    def _update_order_in_db(self, order: OrderInfo) -> None:
        if not self._enable_db:
            return
        try:
            from src.database.connection import get_session
            from src.database.repositories import LiveOrderRepository

            with get_session() as session:
                repo = LiveOrderRepository(session)
                repo.update_status(
                    order_id=order.order_id,
                    status=order.status.value,
                    filled_quantity=order.filled_quantity,
                    filled_price=order.filled_price,
                )
        except Exception as e:
            logger.warning(f"주문 상태 DB 업데이트 실패: {e}")
