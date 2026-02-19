"""KIS WebSocket client for real-time tick and execution data."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import websockets
from loguru import logger

from src.broker.kis_constants import (
    MOCK_WS_URL,
    REAL_WS_URL,
    WS_MAX_SUBSCRIPTIONS,
    WS_MY_TRADE,
    WS_MY_TRADE_MOCK,
    WS_ORDERBOOK,
    WS_TRADE,
)
from src.broker.kis_models import WSTickData


class KISWebSocket:
    """Real-time WebSocket client for KIS market data and execution notices."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        approval_key: str = "",
        is_mock: bool = True,
        on_tick: Callable[[WSTickData], Any] | None = None,
        on_execution: Callable[[dict], Any] | None = None,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self._approval_key = approval_key
        self.is_mock = is_mock
        self.ws_url = MOCK_WS_URL if is_mock else REAL_WS_URL
        self.on_tick = on_tick
        self.on_execution = on_execution

        self._ws: Any = None
        self._subscribed: set[str] = set()
        self._running = False
        self._recv_task: asyncio.Task | None = None

    @property
    def subscribed_count(self) -> int:
        return len(self._subscribed)

    async def start(self, approval_key: str = "") -> None:
        """Connect to WebSocket server."""
        if approval_key:
            self._approval_key = approval_key

        self._ws = await websockets.connect(
            self.ws_url,
            ping_interval=30,
            ping_timeout=10,
        )
        self._running = True
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.info(f"KIS WebSocket 연결 완료 ({'모의' if self.is_mock else '실전'})")

    async def stop(self) -> None:
        """Disconnect from WebSocket."""
        self._running = False
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._subscribed.clear()
        logger.info("KIS WebSocket 연결 종료")

    async def subscribe_trade(self, stock_code: str) -> bool:
        """Subscribe to real-time trade data for a stock."""
        if stock_code in self._subscribed:
            return True
        if len(self._subscribed) >= WS_MAX_SUBSCRIPTIONS:
            logger.warning(
                f"WebSocket 구독 한도 초과 ({WS_MAX_SUBSCRIPTIONS}종목). "
                f"{stock_code} 구독 실패"
            )
            return False
        if not self._ws or not self._running:
            logger.warning(f"WS 미연결 상태, 구독 불가: {stock_code}")
            return False

        try:
            msg = self._build_subscribe_msg(WS_TRADE, stock_code, subscribe=True)
            await self._ws.send(json.dumps(msg))
            self._subscribed.add(stock_code)
            logger.debug(f"WS 구독: {stock_code} (총 {len(self._subscribed)}종목)")
            return True
        except Exception as e:
            logger.warning(f"WS 구독 전송 실패: {stock_code} - {e}")
            return False

    async def unsubscribe_trade(self, stock_code: str) -> None:
        """Unsubscribe from real-time trade data."""
        if stock_code not in self._subscribed:
            return
        if not self._ws or not self._running:
            self._subscribed.discard(stock_code)
            return

        try:
            msg = self._build_subscribe_msg(WS_TRADE, stock_code, subscribe=False)
            await self._ws.send(json.dumps(msg))
            self._subscribed.discard(stock_code)
            logger.debug(f"WS 해제: {stock_code} (총 {len(self._subscribed)}종목)")
        except Exception as e:
            logger.warning(f"WS 해제 전송 실패: {stock_code} - {e}")
            self._subscribed.discard(stock_code)

    async def subscribe_my_executions(self) -> None:
        """Subscribe to personal execution notices."""
        if not self._ws or not self._running:
            logger.warning("WS 미연결 상태, 체결통보 구독 불가")
            return

        tr_id = WS_MY_TRADE_MOCK if self.is_mock else WS_MY_TRADE
        hts_id = self.app_key[:8] if len(self.app_key) >= 8 else self.app_key
        msg = self._build_subscribe_msg(tr_id, hts_id, subscribe=True)
        await self._ws.send(json.dumps(msg))
        logger.info("WS 체결 통보 구독 완료")

    async def update_subscriptions(
        self, required_codes: set[str]
    ) -> None:
        """Dynamically update subscriptions to match required set."""
        to_add = required_codes - self._subscribed
        to_remove = self._subscribed - required_codes

        for code in to_remove:
            await self.unsubscribe_trade(code)
            await asyncio.sleep(0.05)

        for code in to_add:
            if not await self.subscribe_trade(code):
                break
            await asyncio.sleep(0.05)

    def _build_subscribe_msg(
        self, tr_id: str, tr_key: str, subscribe: bool
    ) -> dict:
        return {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": "1" if subscribe else "2",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": tr_key,
                }
            },
        }

    async def _recv_loop(self) -> None:
        """Main receive loop for WebSocket messages."""
        while self._running:
            try:
                raw = await self._ws.recv()
                await self._handle_message(raw)
            except websockets.ConnectionClosed:
                logger.warning("KIS WebSocket 연결 끊김, 재연결 시도...")
                await self._reconnect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"KIS WebSocket 수신 오류: {e}")
                await asyncio.sleep(1)

    async def _reconnect(self) -> None:
        """Attempt to reconnect on connection loss."""
        codes = set(self._subscribed)
        self._subscribed.clear()

        for attempt in range(5):
            try:
                await asyncio.sleep(2 ** attempt)
                self._ws = await websockets.connect(
                    self.ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                )
                # Re-subscribe market data
                for code in codes:
                    await self.subscribe_trade(code)
                    await asyncio.sleep(0.1)
                # Re-subscribe execution notices
                try:
                    await self.subscribe_my_executions()
                except Exception as e:
                    logger.warning(f"체결통보 재구독 실패: {e}")
                logger.info(f"KIS WebSocket 재연결 성공 (시도 {attempt + 1})")
                return
            except Exception as e:
                logger.warning(f"재연결 실패 (시도 {attempt + 1}): {e}")

        logger.error("KIS WebSocket 재연결 5회 실패, 수신 중단")
        self._running = False

    async def _handle_message(self, raw: str) -> None:
        """Parse and dispatch a WebSocket message."""
        # JSON 응답 (구독 확인/에러)
        if raw.startswith("{"):
            data = json.loads(raw)
            header = data.get("header", {})
            tr_id = header.get("tr_id", "")
            msg_cd = header.get("msg_cd", "")

            if msg_cd == "OPSP0000":
                return  # 구독 성공 ACK
            if "error" in str(data).lower() or msg_cd.startswith("E"):
                logger.warning(f"KIS WS 에러: {data}")
            return

        # 파이프 구분 데이터 (실시간 체결가 등)
        parts = raw.split("|")
        if len(parts) < 4:
            return

        tr_id = parts[1]
        body = parts[3]

        if tr_id == WS_TRADE:
            self._handle_trade_tick(body)
        elif tr_id in (WS_MY_TRADE, WS_MY_TRADE_MOCK):
            self._handle_execution_notice(body)

    def _handle_trade_tick(self, body: str) -> None:
        """Parse real-time trade tick data."""
        fields = body.split("^")
        if len(fields) < 20:
            return

        try:
            tick = WSTickData(
                code=fields[0],
                price=int(fields[2]),
                volume=int(fields[12]),
                timestamp=fields[1],
                change_rate=float(fields[5]) if fields[5] else 0.0,
                ask_price=int(fields[3]) if fields[3] else 0,
                bid_price=int(fields[4]) if fields[4] else 0,
            )
            if self.on_tick:
                self.on_tick(tick)
        except (ValueError, IndexError) as e:
            logger.debug(f"틱 파싱 오류: {e}")

    def _handle_execution_notice(self, body: str) -> None:
        """Parse personal execution notice."""
        fields = body.split("^")
        if len(fields) < 10:
            return

        try:
            execution = {
                "order_id": fields[1],
                "stock_code": fields[0],
                "side": fields[4],
                "quantity": int(fields[6]) if fields[6] else 0,
                "price": int(fields[5]) if fields[5] else 0,
            }
            if self.on_execution:
                self.on_execution(execution)
        except (ValueError, IndexError) as e:
            logger.debug(f"체결통보 파싱 오류: {e}")
