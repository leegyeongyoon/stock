"""Main trading engine - orchestrates all components."""

import asyncio
from datetime import datetime, time, timedelta
from enum import Enum

from loguru import logger

from src.broker.kis_auth import KISAuth
from src.broker.kis_client import KISClient
from src.broker.kis_models import OrderSide, OrderStatus, OrderType
from src.broker.kis_websocket import KISWebSocket
from src.config.settings import settings
from src.engine.order_manager import OrderManager
from src.engine.position_manager import PositionManager
from src.engine.risk_manager import RiskManager
from src.engine.strategy_runner import STRATEGY_META, StrategyRunner
from src.engine.trade_store import TradeStore
from src.pipeline.data_manager import DataManager
from src.pipeline.stock_universe import StockUniverse


class EngineState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class TradingEngine:
    """Main trading engine that orchestrates the full trading lifecycle.

    Schedule:
        08:50  Start: auth, load universe, init data
        09:00  Market open: start data collection + strategy scanning
        09:00-15:20  Main loop: poll → scan → trade → monitor
        15:20  Market close: cancel open orders, force close
        15:30  Generate daily report
    """

    def __init__(self):
        self.state = EngineState.IDLE
        self.broker_connected = False

        # KIS broker (initialized in start())
        self.auth: KISAuth | None = None
        self.client: KISClient | None = None
        self.ws: KISWebSocket | None = None
        self.order_manager: OrderManager | None = None
        self.data_manager: DataManager | None = None

        # KIS 무관 컴포넌트 - 즉시 초기화
        self.universe = StockUniverse()
        try:
            self.universe.load_from_db()
        except Exception as e:
            logger.warning(f"종목 유니버스 DB 로드 실패 (빈 목록 사용): {e}")

        self.position_manager = PositionManager(
            initial_capital=settings.initial_capital,
        )
        self.risk_manager = RiskManager(
            position_mgr=self.position_manager,
            max_position_pct=settings.max_position_size,
            max_positions=settings.max_positions,
            max_daily_loss_pct=settings.max_daily_loss,
        )
        self.strategy_runner = StrategyRunner(data_manager=None)
        self.trade_store = TradeStore()

        # Tasks
        self._main_loop_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None

        # Event log (in-memory, 최근 200개)
        self._event_log: list[dict] = []

        # Event callbacks for WebSocket hub
        self._on_signal_callbacks: list = []
        self._on_order_callbacks: list = []
        self._on_position_callbacks: list = []
        self._on_system_callbacks: list = []

        self.add_log("INIT", f"엔진 초기화 완료 - 전략 {len(self.strategy_runner.strategies)}개")
        logger.info(
            f"엔진 초기화: 전략 {len(self.strategy_runner.strategies)}개, "
            f"종목 {self.universe.count}개, "
            f"자본금 {settings.initial_capital:,}원"
        )

    async def init_balance(self) -> None:
        """서버 시작 시 KIS 잔고 한번 조회하여 초기 자본금 세팅."""
        try:
            auth = KISAuth(
                app_key=settings.kis_app_key,
                app_secret=settings.kis_app_secret,
                account_no=settings.kis_account_no,
                is_mock=settings.kis_is_mock,
            )
            client = KISClient(auth)
            await client.start()
            balance = await client.get_balance()
            await client.stop()

            self.position_manager.cash = balance.total_deposit
            self.position_manager.initial_capital = balance.total_eval if balance.total_eval > 0 else balance.total_deposit

            self.add_log(
                "INIT",
                f"초기 잔고 조회: 예수금 {balance.total_deposit:,}원, "
                f"총평가 {balance.total_eval:,}원",
            )
            logger.info(
                f"초기 잔고 조회: 예수금={balance.total_deposit:,}원 "
                f"평가={balance.total_eval:,}원"
            )
        except Exception as e:
            logger.warning(f"초기 잔고 조회 실패 (기본값 사용): {e}")

    # ── Lifecycle ──────────────────────────────────────────

    async def start(self) -> None:
        """Initialize broker connection and start trading."""
        if self.state == EngineState.RUNNING:
            logger.warning("엔진이 이미 실행 중입니다")
            return

        self.state = EngineState.STARTING
        logger.info("=== 트레이딩 엔진 시작 ===")

        try:
            # 1. KIS Auth
            self.auth = KISAuth(
                app_key=settings.kis_app_key,
                app_secret=settings.kis_app_secret,
                account_no=settings.kis_account_no,
                is_mock=settings.kis_is_mock,
            )

            # 2. REST Client
            self.client = KISClient(self.auth)
            await self.client.start()
            self.broker_connected = True

            # 3. Data Manager (needs client)
            self.data_manager = DataManager(
                client=self.client,
                universe=self.universe,
            )
            self.strategy_runner.data_manager = self.data_manager

            # 4. Order Manager
            self.order_manager = OrderManager(self.client)

            # 5. WebSocket (optional)
            self.ws = KISWebSocket(
                app_key=settings.kis_app_key,
                app_secret=settings.kis_app_secret,
                is_mock=settings.kis_is_mock,
                on_tick=self.data_manager.on_tick,
            )

            # 6. Sync balance
            await self._sync_balance()

            # 7. Start main loop
            self.state = EngineState.RUNNING
            self._main_loop_task = asyncio.create_task(self._main_loop())
            self._monitor_task = asyncio.create_task(self._position_monitor_loop())

            await self._emit_system("ENGINE_STARTED", "트레이딩 엔진 시작")
            logger.info("=== 트레이딩 엔진 시작 완료 ===")

        except Exception as e:
            self.state = EngineState.ERROR
            self.broker_connected = False
            logger.error(f"엔진 시작 실패: {e}")
            raise

    async def stop(self) -> None:
        """Gracefully stop the engine."""
        if self.state not in (EngineState.RUNNING, EngineState.ERROR):
            return

        self.state = EngineState.STOPPING
        logger.info("=== 트레이딩 엔진 중지 ===")

        # Cancel loops
        for task in [self._main_loop_task, self._monitor_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Cancel open orders
        if self.order_manager:
            cancelled = await self.order_manager.cancel_all_open()
            logger.info(f"미체결 주문 {cancelled}건 취소")

        # Stop data collection
        if self.data_manager:
            await self.data_manager.stop_polling()

        # Stop WebSocket
        if self.ws:
            await self.ws.stop()

        # Stop REST client
        if self.client:
            await self.client.stop()

        self.state = EngineState.STOPPED
        await self._emit_system("ENGINE_STOPPED", "트레이딩 엔진 중지")
        logger.info("=== 트레이딩 엔진 중지 완료 ===")

    async def emergency_stop(self) -> None:
        """Emergency stop - close all positions immediately."""
        logger.critical("!!! 긴급 정지 !!!")
        await self._emit_system("EMERGENCY_STOP", "긴급 정지 발동", severity="CRITICAL")

        # Close all positions at market
        if self.position_manager and self.order_manager:
            for code, pos in list(self.position_manager.positions.items()):
                await self.order_manager.submit_order(
                    stock_code=code,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    order_type=OrderType.MARKET,
                    strategy_name=pos.strategy_name,
                )

        await self.stop()

    # ── Main Loop ──────────────────────────────────────────

    async def _main_loop(self) -> None:
        """Main trading loop - runs during market hours."""
        MARKET_OPEN = time(9, 0)
        SCAN_START = time(9, 5)       # Wait 5 min for data
        MARKET_CLOSE = time(15, 20)
        REPORT_TIME = time(15, 30)

        # Start data polling
        await self.data_manager.start_polling()

        while self.state == EngineState.RUNNING:
            try:
                now = datetime.now()
                current_time = now.time()

                # Before market open: wait
                if current_time < MARKET_OPEN:
                    await asyncio.sleep(10)
                    continue

                # During market hours: scan and trade
                if SCAN_START <= current_time < MARKET_CLOSE:
                    await self._scan_and_trade()
                    await asyncio.sleep(30)  # Scan every 30 seconds
                    continue

                # Market close: cleanup
                if MARKET_CLOSE <= current_time < REPORT_TIME:
                    await self._market_close_routine()
                    await asyncio.sleep(60)
                    continue

                # After report: idle until next day
                if current_time >= REPORT_TIME:
                    await asyncio.sleep(300)
                    continue

                await asyncio.sleep(10)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {e}")
                await asyncio.sleep(5)

    async def _scan_and_trade(self) -> None:
        """Scan for signals and execute trades."""
        if self.risk_manager.check_circuit_breaker():
            return

        held = self.position_manager.get_held_codes()
        codes = self.universe.codes

        # Run all strategies
        signals = self.strategy_runner.scan_for_signals(codes, held)

        for signal in signals:
            # Risk check
            price_data = self.data_manager.get_today_df(signal.stock_code)
            if price_data.empty:
                continue
            current_price = int(price_data.iloc[-1]["close"])

            qty = self.risk_manager.calculate_position_size(
                current_price, signal.stop_loss
            )
            if qty <= 0:
                continue

            order_value = current_price * qty
            risk_check = self.risk_manager.check_pre_trade(
                signal.stock_code, order_value
            )
            if not risk_check.allowed:
                logger.debug(f"리스크 거부: {signal.stock_code} - {risk_check.reason}")
                continue

            # Place order
            order = await self.order_manager.submit_order(
                stock_code=signal.stock_code,
                side=OrderSide.BUY,
                quantity=qty,
                order_type=OrderType.MARKET,
                strategy_name=signal.strategy_name,
            )

            if order.status == OrderStatus.SUBMITTED:
                # Assume market order fills immediately at current price
                self.position_manager.open_position(
                    stock_code=signal.stock_code,
                    stock_name=self.universe.get_name(signal.stock_code),
                    strategy_name=signal.strategy_name,
                    quantity=qty,
                    price=current_price,
                    stop_loss_pct=signal.stop_loss,
                    take_profit_pct=signal.take_profit,
                    order_id=order.order_id,
                )

                await self._emit_signal(signal)
                await self._emit_position_update()

                # Update WS subscriptions
                if self.ws and self.ws.subscribed_count < 40:
                    await self.ws.subscribe_trade(signal.stock_code)

    async def _position_monitor_loop(self) -> None:
        """Monitor positions for SL/TP triggers every 5 seconds."""
        while self.state == EngineState.RUNNING:
            try:
                # Update prices
                for code in list(self.position_manager.get_held_codes()):
                    df = self.data_manager.get_today_df(code)
                    if not df.empty:
                        current_price = float(df.iloc[-1]["close"])
                        self.position_manager.update_price(code, current_price)

                # Check SL/TP
                to_close = self.risk_manager.check_stop_loss_tp()
                for code, reason in to_close:
                    pos = self.position_manager.get_position(code)
                    if not pos:
                        continue

                    # Submit sell order
                    await self.order_manager.submit_order(
                        stock_code=code,
                        side=OrderSide.SELL,
                        quantity=pos.quantity,
                        order_type=OrderType.MARKET,
                        strategy_name=pos.strategy_name,
                    )

                    # Close position
                    self.position_manager.close_position(
                        code, pos.current_price, reason
                    )
                    await self._emit_position_update()

                    # Unsubscribe WS
                    if self.ws:
                        await self.ws.unsubscribe_trade(code)

                # Check circuit breaker
                self.risk_manager.check_circuit_breaker()

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"포지션 모니터 오류: {e}")
                await asyncio.sleep(5)

    async def _market_close_routine(self) -> None:
        """End-of-day: cancel orders, force close positions."""
        # Cancel all open orders
        await self.order_manager.cancel_all_open()

        # Force close all positions
        for code, pos in list(self.position_manager.positions.items()):
            await self.order_manager.submit_order(
                stock_code=code,
                side=OrderSide.SELL,
                quantity=pos.quantity,
                order_type=OrderType.MARKET,
                strategy_name=pos.strategy_name,
            )
            self.position_manager.close_position(code, pos.current_price, "CLOSE")

        await self._emit_system("MARKET_CLOSE", "장 마감 처리 완료")

    async def _sync_balance(self) -> None:
        """Sync account balance from broker → PositionManager에 실제 잔고 반영."""
        try:
            balance = await self.client.get_balance()

            # PositionManager에 실제 예수금/자본금 반영
            self.position_manager.cash = balance.total_deposit
            self.position_manager.initial_capital = balance.total_eval

            # 기존 보유 종목이 있으면 포지션으로 등록
            for h in balance.holdings:
                if not self.position_manager.has_position(h.stock_code):
                    self.position_manager.open_position(
                        stock_code=h.stock_code,
                        stock_name=h.stock_name,
                        strategy_name="기존보유",
                        quantity=h.quantity,
                        price=h.avg_price,
                    )
                    # open_position이 cash를 차감하므로 다시 보정
                    self.position_manager.cash = balance.total_deposit

            self.add_log(
                "INIT",
                f"계좌 동기화: 예수금 {balance.total_deposit:,}원, "
                f"총평가 {balance.total_eval:,}원, "
                f"보유 {len(balance.holdings)}종목",
            )
            logger.info(
                f"계좌 동기화: 예수금={balance.total_deposit:,}원 "
                f"평가={balance.total_eval:,}원 보유={len(balance.holdings)}종목"
            )
        except Exception as e:
            self.add_log("INIT", f"계좌 동기화 실패: {e}", severity="WARNING")
            logger.warning(f"계좌 동기화 실패: {e}")

    # ── Event Emitters ─────────────────────────────────────

    def on_signal(self, callback) -> None:
        self._on_signal_callbacks.append(callback)

    def on_order(self, callback) -> None:
        self._on_order_callbacks.append(callback)

    def on_position(self, callback) -> None:
        self._on_position_callbacks.append(callback)

    def on_system(self, callback) -> None:
        self._on_system_callbacks.append(callback)

    async def _emit_signal(self, signal) -> None:
        for cb in self._on_signal_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(signal)
                else:
                    cb(signal)
            except Exception as e:
                logger.error(f"시그널 콜백 오류: {e}")

    async def _emit_position_update(self) -> None:
        data = self.position_manager.get_summary()
        for cb in self._on_position_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                logger.error(f"포지션 콜백 오류: {e}")

    async def _emit_system(
        self, event_type: str, message: str, severity: str = "INFO"
    ) -> None:
        data = {
            "event_type": event_type,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now().isoformat(),
        }
        self._event_log.append(data)
        # 최대 200개 유지
        if len(self._event_log) > 200:
            self._event_log = self._event_log[-200:]
        for cb in self._on_system_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                logger.error(f"시스템 콜백 오류: {e}")

    def add_log(self, event_type: str, message: str, severity: str = "INFO") -> None:
        """동기 로그 추가 (엔진 외부에서 호출 가능)."""
        data = {
            "event_type": event_type,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now().isoformat(),
        }
        self._event_log.append(data)
        if len(self._event_log) > 200:
            self._event_log = self._event_log[-200:]

    def get_event_log(self, limit: int = 50) -> list[dict]:
        """최근 이벤트 로그 반환."""
        return list(reversed(self._event_log[-limit:]))

    # ── Public API ─────────────────────────────────────────

    def get_strategy_detail(self, strategy_name: str) -> dict:
        """전략 상세 정보 + 근접 종목 반환."""
        meta = STRATEGY_META.get(strategy_name, {})
        time_window = meta.get("time_window", "")

        # 현재 시간이 활성 시간대인지 체크
        is_active = False
        if time_window:
            try:
                parts = time_window.replace(" ", "").split("~")
                now = datetime.now().time()
                start = datetime.strptime(parts[0], "%H:%M").time()
                end = datetime.strptime(parts[1], "%H:%M").time()
                is_active = start <= now <= end
            except (ValueError, IndexError):
                pass

        # 이 전략의 포지션
        strategy_positions = [
            p for p in self.get_positions()
            if p["strategy_name"] == strategy_name
        ]

        # 이 전략의 오늘 거래
        strategy_trades = [
            t for t in self.get_trades_today()
            if t["strategy_name"] == strategy_name
        ]

        # Near entry 스캔 (데이터가 있을 때만)
        near_entry = []
        if self.data_manager and self.strategy_runner:
            held = self.position_manager.get_held_codes() if self.position_manager else set()
            codes = self.universe.codes[:100] if self.universe else []
            near_entry = self.strategy_runner.scan_near_entry(
                strategy_name, codes, held, top_k=5
            )

        return {
            "meta": meta,
            "enabled": self.strategy_runner.is_enabled(strategy_name) if self.strategy_runner else False,
            "signals_today": self.strategy_runner._signal_count.get(strategy_name, 0) if self.strategy_runner else 0,
            "positions": strategy_positions,
            "trades": strategy_trades,
            "near_entry": near_entry,
            "is_active_time": is_active,
        }

    def get_holdings_detail(self) -> list[dict]:
        """보유종목 상세 (현재가, 수익률, 전략 등)."""
        positions = self.get_positions()
        for pos in positions:
            cost = pos["avg_price"] * pos["quantity"]
            market_val = pos["current_price"] * pos["quantity"]
            pos["market_value"] = market_val
            pos["cost_basis"] = cost
            pos["pnl_amount"] = market_val - cost
            pos["pnl_pct"] = ((pos["current_price"] / pos["avg_price"]) - 1) * 100 if pos["avg_price"] > 0 else 0
        return positions

    def get_dashboard_summary(self) -> dict:
        """Get complete dashboard summary."""
        return {
            "state": self.state.value,
            "portfolio": self.position_manager.get_summary() if self.position_manager else {},
            "risk": self.risk_manager.get_risk_status() if self.risk_manager else {},
            "strategies": self.strategy_runner.get_status() if self.strategy_runner else [],
            "timestamp": datetime.now().isoformat(),
        }

    def get_positions(self) -> list[dict]:
        if not self.position_manager:
            return []
        return [
            {
                "stock_code": pos.stock_code,
                "stock_name": pos.stock_name,
                "strategy_name": pos.strategy_name,
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "stop_loss_price": pos.stop_loss_price,
                "take_profit_price": pos.take_profit_price,
                "entry_time": pos.entry_time.isoformat(),
            }
            for pos in self.position_manager.positions.values()
        ]

    def get_trades_today(self) -> list[dict]:
        if not self.position_manager:
            return []
        return [
            {
                "stock_code": t.stock_code,
                "stock_name": t.stock_name,
                "strategy_name": t.strategy_name,
                "quantity": t.quantity,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "exit_reason": t.exit_reason,
                "exit_time": t.exit_time.isoformat(),
            }
            for t in self.position_manager.trades_today
        ]
