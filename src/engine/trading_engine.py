"""Main trading engine - orchestrates all components."""

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
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
from src.engine.hongstyle_runner import HongStyleRunner
from src.engine.gylee_runner import GyleeRunner
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
        self._balance_synced = False

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

        # 홍인기 전략 Runner (자동시작은 안 함 - API로 토글)
        self.hongstyle_runner = HongStyleRunner(self)

        # 경윤 수정 매매법 Runner
        self.gylee_runner = GyleeRunner(self)

        # Tasks
        self._main_loop_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None
        self._close_done: bool = False

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

            # 5. WebSocket (optional) with execution callback
            self.ws = KISWebSocket(
                app_key=settings.kis_app_key,
                app_secret=settings.kis_app_secret,
                is_mock=settings.kis_is_mock,
                on_tick=self.data_manager.on_tick,
                on_execution=self._on_execution_received,
            )

            # 6. Sync balance
            await self._sync_balance()

            # 7. Recover state from DB
            await self._recover_state_from_db()

            # 8. Start main loop
            self.state = EngineState.RUNNING
            self._main_loop_task = asyncio.create_task(self._main_loop())
            self._monitor_task = asyncio.create_task(self._position_monitor_loop())
            self._balance_sync_task = asyncio.create_task(self._periodic_balance_sync())

            # 9. Subscribe to execution notices (after WS start)
            try:
                approval_key = await self.client.get_ws_approval_key()
                await self.ws.start(approval_key)
                await self.ws.subscribe_my_executions()
            except Exception as e:
                logger.warning(f"WS 체결통보 구독 실패 (시세만 사용): {e}")

            await self._emit_system("ENGINE_STARTED", "트레이딩 엔진 시작")
            logger.info("=== 트레이딩 엔진 시작 완료 ===")

            # 경윤 자동매매 자동 시작
            try:
                await self.start_gylee()
                logger.info("경윤 자동매매 자동 시작 완료")
            except Exception as e:
                logger.warning(f"경윤 자동매매 자동 시작 실패: {e}")

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
        for task in [self._main_loop_task, self._monitor_task, getattr(self, '_balance_sync_task', None)]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Stop 홍인기 Runner
        if self.hongstyle_runner and self.hongstyle_runner.enabled:
            await self.hongstyle_runner.stop()

        # Stop 경윤 Runner
        if self.gylee_runner and self.gylee_runner.enabled:
            await self.gylee_runner.stop()

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

                # Before market open: reset close flag for new day
                if current_time < MARKET_OPEN:
                    self._close_done = False
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
        """Scan for signals and execute trades.

        Uses real-time current price API for:
        - Accurate position sizing (vs stale 5-min bar close)
        - Better fill price estimation
        """
        if self.risk_manager.check_circuit_breaker():
            return

        held = self.position_manager.get_held_codes()
        codes = self.universe.codes

        # Update priority codes: held positions + near-entry candidates
        await self._update_priority_codes(held)

        # Run all strategies (uses 5-min bar data for indicator calculation)
        signals = self.strategy_runner.scan_for_signals(codes, held)

        for signal in signals:
            # Get real-time current price (fallback to last bar close)
            real_price = await self.data_manager.fetch_current_price(
                signal.stock_code
            )
            if real_price <= 0:
                price_data = self.data_manager.get_today_df(signal.stock_code)
                if price_data.empty:
                    continue
                real_price = int(price_data.iloc[-1]["close"])

            current_price = real_price

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
                # Use real-time price for position entry
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

                # Add to priority polling
                self.data_manager.add_priority_codes({signal.stock_code})

                await self._emit_signal(signal)
                await self._emit_order(order)
                await self._emit_position_update()

                # Update WS subscriptions
                if self.ws and self.ws.subscribed_count < 40:
                    await self.ws.subscribe_trade(signal.stock_code)

    async def _position_monitor_loop(self) -> None:
        """Monitor positions for SL/TP triggers every 5 seconds.

        Uses real-time current price API for held positions (most accurate).
        Falls back to last bar close if API fails.
        """
        while self.state == EngineState.RUNNING:
            try:
                # Update prices with real-time current price API
                held_codes = list(self.position_manager.get_held_codes())
                if held_codes:
                    live_prices = await self.data_manager.fetch_current_prices(
                        held_codes
                    )
                    # Update from API results
                    for code, price in live_prices.items():
                        self.position_manager.update_price(code, float(price))
                    # Fallback for codes that failed API call
                    for code in held_codes:
                        if code not in live_prices:
                            df = self.data_manager.get_today_df(code)
                            if not df.empty:
                                fallback = float(df.iloc[-1]["close"])
                                self.position_manager.update_price(code, fallback)

                # Check SL/TP (홍인기 포지션은 HongStyleRunner가 자체 관리)
                to_close = self.risk_manager.check_stop_loss_tp()
                for code, reason in to_close:
                    pos = self.position_manager.get_position(code)
                    if not pos:
                        continue
                    if pos.strategy_name.startswith("홍스타일"):
                        continue  # HongStyleRunner 자체 모니터에서 처리
                    if pos.strategy_name.startswith("경윤_"):
                        continue  # GyleeRunner 자체 모니터에서 처리

                    # Submit sell order
                    sell_order = await self.order_manager.submit_order(
                        stock_code=code,
                        side=OrderSide.SELL,
                        quantity=pos.quantity,
                        order_type=OrderType.MARKET,
                        strategy_name=pos.strategy_name,
                    )

                    # Close position
                    trade = self.position_manager.close_position(
                        code, pos.current_price, reason
                    )
                    await self._emit_order(sell_order)
                    await self._emit_position_update()

                    # Save to trade store
                    if trade:
                        self.trade_store.save_trade({
                            "stock_code": trade.stock_code,
                            "stock_name": trade.stock_name,
                            "strategy_name": trade.strategy_name,
                            "side": trade.side,
                            "quantity": trade.quantity,
                            "entry_price": trade.entry_price,
                            "exit_price": trade.exit_price,
                            "entry_time": trade.entry_time.isoformat(),
                            "exit_time": trade.exit_time.isoformat(),
                            "pnl": trade.pnl,
                            "pnl_pct": trade.pnl_pct,
                            "exit_reason": trade.exit_reason,
                        })

                    # Unsubscribe WS + remove from priority
                    if self.ws:
                        await self.ws.unsubscribe_trade(code)
                    self.data_manager.remove_priority_codes({code})

                # Check circuit breaker
                self.risk_manager.check_circuit_breaker()

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"포지션 모니터 오류: {e}")
                await asyncio.sleep(5)

    async def _market_close_routine(self) -> None:
        """End-of-day: cancel orders, force close positions, save snapshots."""
        if self._close_done:
            return
        self._close_done = True

        # 홍인기 Runner 중지 + 일일 리셋
        if self.hongstyle_runner and self.hongstyle_runner.enabled:
            await self.hongstyle_runner.stop()
        if self.hongstyle_runner:
            self.hongstyle_runner.reset_daily()

        # 경윤 Runner 중지 + 일일 리셋
        if self.gylee_runner and self.gylee_runner.enabled:
            await self.gylee_runner.stop()
        if self.gylee_runner:
            self.gylee_runner.reset_daily()

        # Cancel all open orders
        await self.order_manager.cancel_all_open()

        # Force close all positions (전략이 진입한 것만, "기존보유"는 스킵)
        for code, pos in list(self.position_manager.positions.items()):
            if pos.strategy_name == "기존보유":
                logger.info(f"기존보유 포지션 스킵: {code} {pos.stock_name}")
                continue

            await self.order_manager.submit_order(
                stock_code=code,
                side=OrderSide.SELL,
                quantity=pos.quantity,
                order_type=OrderType.MARKET,
                strategy_name=pos.strategy_name,
            )
            trade = self.position_manager.close_position(code, pos.current_price, "CLOSE")
            if trade:
                self.trade_store.save_trade({
                    "stock_code": trade.stock_code,
                    "stock_name": trade.stock_name,
                    "strategy_name": trade.strategy_name,
                    "side": trade.side,
                    "quantity": trade.quantity,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "entry_time": trade.entry_time.isoformat(),
                    "exit_time": trade.exit_time.isoformat(),
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "exit_reason": trade.exit_reason,
                })

        # Save daily portfolio snapshot
        self._save_daily_snapshot()

        await self._emit_system("MARKET_CLOSE", "장 마감 처리 완료")

    async def _sync_balance(self, max_retries: int = 3) -> None:
        """Sync account balance from broker → PositionManager에 실제 잔고 반영.

        KIS 모의투자 서버가 간헐적으로 500 에러를 반환하므로 재시도 로직 포함.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                balance = await self.client.get_balance()

                # 보유종목 KIS 평가금액 합계
                holdings_eval = int(sum(h.eval_amount for h in balance.holdings))

                # 현금 계산: KIS 모의투자에서 예수금(dnca_tot_amt)은 매수해도 안 줄어듦
                # → 예수금 - 매입금액합계 = 실제 가용 현금
                if balance.purchase_total > 0:
                    # 매입금액합계(pchs_amt_smtl_amt) 사용: 가장 정확
                    actual_cash = int(balance.total_deposit - balance.purchase_total)
                elif holdings_eval > 0:
                    # 폴백: 예수금 - 보유종목 평가금액 (근사값)
                    actual_cash = int(balance.total_deposit - holdings_eval)
                else:
                    actual_cash = int(balance.total_deposit)

                if actual_cash < 0:
                    actual_cash = 0

                # 총자산 = 현금 + 평가금액
                total_equity = actual_cash + holdings_eval
                self.position_manager.cash = actual_cash

                # 기존 보유 종목이 있으면 포지션으로 등록
                for h in balance.holdings:
                    if not self.position_manager.has_position(h.stock_code):
                        self.position_manager.open_position(
                            stock_code=h.stock_code,
                            stock_name=h.stock_name,
                            strategy_name="기존보유",
                            quantity=h.quantity,
                            price=int(h.avg_price),
                        )
                        # open_position이 cash를 차감하므로 actual_cash로 보정
                        self.position_manager.cash = actual_cash

                        # KIS 현재가로 시가평가 갱신
                        if h.current_price > 0:
                            self.position_manager.update_price(
                                h.stock_code, int(h.current_price)
                            )

                # 서버 재시작 시 initial_capital = 현재 총자산 → PnL 0%에서 시작
                # 일중 거래 PnL은 이 시점 이후부터 누적
                self.position_manager.initial_capital = self.position_manager.total_equity
                self._balance_synced = True

                self.add_log(
                    "INIT",
                    f"계좌 동기화: 현금 {actual_cash:,.0f}원, "
                    f"총자산 {self.position_manager.total_equity:,.0f}원, "
                    f"보유 {len(balance.holdings)}종목",
                )
                logger.info(
                    f"계좌 동기화: 현금={actual_cash:,}원 "
                    f"총자산={total_equity:,}원 "
                    f"보유={len(balance.holdings)}종목 "
                    f"(KIS 예수금={balance.total_deposit:,}원, "
                    f"매입합계={balance.purchase_total:,}원, "
                    f"평가={holdings_eval:,}원)"
                )
                return  # 성공 시 즉시 반환
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_sec = 5 * (attempt + 1)
                    logger.warning(
                        f"계좌 동기화 실패 ({attempt+1}/{max_retries}): {e}, "
                        f"{wait_sec}초 후 재시도"
                    )
                    self.add_log(
                        "INIT",
                        f"계좌 동기화 재시도 ({attempt+1}/{max_retries}): {e}",
                        severity="WARNING",
                    )
                    await asyncio.sleep(wait_sec)

        # 모든 재시도 실패
        self._balance_synced = False
        self.add_log("INIT", f"계좌 동기화 실패 ({max_retries}회 시도): {last_error}", severity="WARNING")
        logger.warning(f"계좌 동기화 실패 ({max_retries}회 시도): {last_error}")

    async def _periodic_balance_sync(self) -> None:
        """주기적으로 KIS 계좌를 재동기화 (초기 동기화 실패 시 복구용).

        - 미동기화 상태: 전체 재동기화
        - 동기화 완료 상태: 현재가 갱신 + 누락 종목 자동 복구
        """
        await asyncio.sleep(60)  # 첫 실행은 60초 후
        while self.state == EngineState.RUNNING:
            try:
                if not getattr(self, '_balance_synced', False):
                    logger.info("계좌 미동기화 상태 → 재동기화 시도")
                    await self._sync_balance(max_retries=2)
                else:
                    try:
                        balance = await self.client.get_balance()

                        # 1) 현재가 갱신
                        for h in balance.holdings:
                            if h.current_price > 0 and self.position_manager.has_position(h.stock_code):
                                self.position_manager.update_price(
                                    h.stock_code, int(h.current_price)
                                )

                        # 2) KIS에 있지만 position_manager에 없는 종목 자동 복구
                        for h in balance.holdings:
                            if h.quantity <= 0:
                                continue
                            if self.position_manager.has_position(h.stock_code):
                                continue

                            # 누락된 종목 발견 → 기존보유로 등록
                            logger.warning(
                                f"KIS 보유종목 누락 발견: {h.stock_name} ({h.stock_code}) "
                                f"{h.quantity}주 → 자동 복구"
                            )
                            self.position_manager.open_position(
                                stock_code=h.stock_code,
                                stock_name=h.stock_name,
                                strategy_name="기존보유",
                                quantity=h.quantity,
                                price=int(h.avg_price),
                            )
                            # open_position이 cash를 차감하므로 올바른 현금으로 재계산
                            holdings_eval = int(sum(
                                hh.eval_amount for hh in balance.holdings
                            ))
                            actual_cash = int(
                                balance.total_deposit - balance.purchase_total
                            )
                            if actual_cash < 0:
                                actual_cash = 0
                            self.position_manager.cash = actual_cash

                            if h.current_price > 0:
                                self.position_manager.update_price(
                                    h.stock_code, int(h.current_price)
                                )

                        # 3) 현금 정합성 체크 (KIS 기준으로 보정)
                        if balance.purchase_total > 0:
                            kis_cash = int(
                                balance.total_deposit - balance.purchase_total
                            )
                            if kis_cash >= 0 and abs(self.position_manager.cash - kis_cash) > 100000:
                                logger.warning(
                                    f"현금 불일치 보정: "
                                    f"{self.position_manager.cash:,} → {kis_cash:,}"
                                )
                                self.position_manager.cash = kis_cash

                    except Exception as e:
                        logger.debug(f"주기적 동기화 실패 (무시): {e}")
            except Exception as e:
                logger.warning(f"주기적 동기화 오류: {e}")
            await asyncio.sleep(120)  # 2분 간격

    # ── Recovery & Execution ────────────────────────────────

    async def _recover_state_from_db(self) -> None:
        """Recover positions from DB on server restart, verify against broker."""
        try:
            from src.database.connection import get_session
            from src.database.repositories import (
                LivePositionRepository,
                SystemEventRepository,
            )

            with get_session() as session:
                repo = LivePositionRepository(session)
                db_positions = repo.get_all()
                # 세션 닫히기 전에 plain data로 변환 (detached instance 방지)
                positions_data = [
                    {
                        "stock_code": p.stock_code,
                        "strategy_name": p.strategy_name,
                        "quantity": p.quantity,
                        "avg_price": float(p.avg_price) if p.avg_price else 0.0,
                    }
                    for p in db_positions
                ]

            if not positions_data:
                logger.info("DB에 복구할 포지션 없음")
                return

            # Load broker balance for verification
            balance = await self.client.get_balance()
            broker_codes = {h.stock_code for h in balance.holdings}

            # 올바른 현금 계산 (total_eval - 보유종목 평가)
            total_eval = balance.total_eval or balance.total_deposit
            holdings_eval = sum(h.eval_amount for h in balance.holdings)
            actual_cash = total_eval - holdings_eval
            if actual_cash < 0:
                actual_cash = balance.total_deposit
            self.position_manager.cash = actual_cash
            saved_cash = actual_cash

            recovered = 0
            for pos_data in positions_data:
                code = pos_data["stock_code"]
                if self.position_manager.has_position(code):
                    continue  # Already loaded from _sync_balance

                if code in broker_codes:
                    self.position_manager.open_position(
                        stock_code=code,
                        stock_name=self.universe.get_name(code) or code,
                        strategy_name=pos_data["strategy_name"] or "복구",
                        quantity=pos_data["quantity"],
                        price=pos_data["avg_price"],
                        order_id="",
                    )
                    # open_position이 cash를 차감하므로 복원
                    self.position_manager.cash = saved_cash
                    recovered += 1
                else:
                    # DB has position but broker doesn't - log mismatch
                    logger.warning(
                        f"불일치 발견: DB에 {code} 포지션 있지만 브로커에 없음 - DB에서 제거"
                    )
                    try:
                        with get_session() as session:
                            repo = LivePositionRepository(session)
                            repo.delete_by_code(code)
                    except Exception:
                        pass

                    try:
                        with get_session() as session:
                            event_repo = SystemEventRepository(session)
                            event_repo.create({
                                "event_type": "POSITION_MISMATCH",
                                "severity": "WARNING",
                                "message": f"DB 포지션 {code} 브로커에 없음 - 자동 제거",
                                "meta": {
                                    "stock_code": code,
                                    "db_quantity": pos_data["quantity"],
                                },
                            })
                    except Exception:
                        pass

            # 복구 후 initial_capital 재계산 (총자산 = 현금 + 보유종목)
            self.position_manager.initial_capital = self.position_manager.total_equity

            if recovered > 0:
                self.add_log("RECOVERY", f"DB에서 {recovered}개 포지션 복구")
                logger.info(f"DB에서 {recovered}개 포지션 복구 완료")

        except Exception as e:
            logger.warning(f"DB 복구 실패 (브로커 잔고만 사용): {e}")

    async def _update_priority_codes(self, held: set[str]) -> None:
        """Update priority polling set: held positions + near-entry candidates.

        Called every scan cycle (~30sec) to keep priority list fresh.
        Near-entry: stocks where ≥3 out of 5 strategy conditions are met.
        """
        priority = set(held)

        # Add near-entry candidates from strategy runner
        try:
            codes = self.universe.codes[:200]  # Top 200 for performance
            for strategy in self.strategy_runner.strategies:
                if not self.strategy_runner.is_enabled(strategy.name):
                    continue
                near = self.strategy_runner.scan_near_entry(
                    strategy.name, codes, held, top_k=10
                )
                for item in near:
                    priority.add(item["stock_code"])
        except Exception as e:
            logger.debug(f"근접 종목 스캔 오류: {e}")

        self.data_manager.set_priority_codes(priority)

    def _on_execution_received(self, execution: dict) -> None:
        """Handle execution notice from KIS WebSocket."""
        try:
            order_id = execution.get("order_id", "")
            stock_code = execution.get("stock_code", "")
            filled_qty = execution.get("quantity", 0)
            filled_price = execution.get("price", 0)

            logger.info(
                f"체결 통보 수신: {stock_code} order={order_id} "
                f"{filled_qty}주 @{filled_price:,}"
            )

            # Update order state
            if self.order_manager and order_id:
                order = self.order_manager.update_from_execution(
                    order_id, filled_qty, float(filled_price)
                )
                if order:
                    asyncio.create_task(self._emit_order(order))

            # Update position avg price if buy
            side = execution.get("side", "")
            if side in ("매수", "BUY", "02"):
                pos = self.position_manager.get_position(stock_code)
                if pos and filled_price > 0:
                    pos.avg_price = float(filled_price)
                    pos.current_price = float(filled_price)

            # Log to system events
            self._log_event_to_db(
                "EXECUTION",
                f"체결: {stock_code} {filled_qty}주 @{filled_price:,}",
                metadata=execution,
            )

        except Exception as e:
            logger.error(f"체결통보 처리 오류: {e}")

    def _save_daily_snapshot(self) -> None:
        """Save daily portfolio snapshot and strategy performance to DB."""
        try:
            from src.database.connection import get_session
            from src.database.repositories import (
                PortfolioSnapshotRepository,
                StrategyPerformanceRepository,
                SystemEventRepository,
            )

            today = date.today()
            summary = self.position_manager.get_summary()
            initial = self.position_manager.initial_capital

            daily_return = Decimal("0")
            if initial > 0:
                daily_return = Decimal(str(summary["daily_pnl"])) / Decimal(str(initial)) * 100

            with get_session() as session:
                # Portfolio snapshot
                snap_repo = PortfolioSnapshotRepository(session)
                snap_repo.upsert({
                    "date": today,
                    "total_equity": Decimal(str(summary["total_equity"])),
                    "daily_pnl": Decimal(str(summary["daily_pnl"])),
                    "daily_return": daily_return,
                    "total_trades": summary["trades_today"],
                    "win_rate": Decimal(str(summary["win_rate"])),
                })

                # Strategy performance
                perf_repo = StrategyPerformanceRepository(session)
                strategy_trades: dict[str, dict] = {}
                for t in self.position_manager.trades_today:
                    sn = t.strategy_name
                    if sn not in strategy_trades:
                        strategy_trades[sn] = {"trades": 0, "wins": 0, "pnl": 0.0}
                    strategy_trades[sn]["trades"] += 1
                    strategy_trades[sn]["pnl"] += t.pnl
                    if t.pnl > 0:
                        strategy_trades[sn]["wins"] += 1

                for sn, stats in strategy_trades.items():
                    perf_repo.upsert({
                        "date": today,
                        "strategy_name": sn,
                        "trades": stats["trades"],
                        "wins": stats["wins"],
                        "pnl": Decimal(str(stats["pnl"])),
                    })

                # System event
                event_repo = SystemEventRepository(session)
                event_repo.create({
                    "event_type": "DAILY_CLOSE",
                    "severity": "INFO",
                    "message": (
                        f"일일 마감: 총자산 {summary['total_equity']:,.0f}원, "
                        f"일일PnL {summary['daily_pnl']:,.0f}원, "
                        f"거래 {summary['trades_today']}건"
                    ),
                    "meta": summary,
                })

            logger.info(f"일일 스냅샷 저장 완료: {today}")

        except Exception as e:
            logger.warning(f"일일 스냅샷 저장 실패: {e}")

    def _log_event_to_db(
        self, event_type: str, message: str, severity: str = "INFO", metadata: dict = None
    ) -> None:
        """Log event to system_events table (fire-and-forget)."""
        try:
            from src.database.connection import get_session
            from src.database.repositories import SystemEventRepository

            with get_session() as session:
                repo = SystemEventRepository(session)
                repo.create({
                    "event_type": event_type,
                    "severity": severity,
                    "message": message,
                    "meta": metadata,
                })
        except Exception as e:
            logger.debug(f"시스템 이벤트 DB 저장 실패: {e}")

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

    async def _emit_order(self, order) -> None:
        """Broadcast order event to WebSocket clients."""
        data = {
            "order_id": order.order_id,
            "stock_code": order.stock_code,
            "side": order.side.value if hasattr(order.side, "value") else str(order.side),
            "quantity": order.quantity,
            "price": order.price,
            "status": order.status.value if hasattr(order.status, "value") else str(order.status),
            "strategy_name": order.strategy_name,
            "timestamp": datetime.now().isoformat(),
        }
        for cb in self._on_order_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                logger.error(f"주문 콜백 오류: {e}")

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
            pos["market_value"] = int(market_val)
            pos["cost_basis"] = int(cost)
            pos["pnl_amount"] = int(market_val - cost)
            pos["pnl_pct"] = round(((pos["current_price"] / pos["avg_price"]) - 1) * 100, 2) if pos["avg_price"] > 0 else 0
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
                "avg_price": int(pos.avg_price),
                "current_price": int(pos.current_price),
                "unrealized_pnl": int(pos.unrealized_pnl),
                "unrealized_pnl_pct": round(pos.unrealized_pnl_pct, 2),
                "stop_loss_price": int(pos.stop_loss_price) if pos.stop_loss_price else 0,
                "take_profit_price": int(pos.take_profit_price) if pos.take_profit_price else 0,
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
                "entry_price": int(t.entry_price),
                "exit_price": int(t.exit_price),
                "pnl": int(t.pnl),
                "pnl_pct": round(t.pnl_pct, 2),
                "exit_reason": t.exit_reason,
                "exit_time": t.exit_time.isoformat(),
            }
            for t in self.position_manager.trades_today
        ]

    # ── 홍인기 전략 제어 ─────────────────────────────────

    async def start_hongstyle(self) -> dict:
        """홍인기 자동매매 시작."""
        if not self.hongstyle_runner:
            return {"success": False, "message": "홍인기 Runner 미초기화"}
        return await self.hongstyle_runner.start()

    async def stop_hongstyle(self) -> dict:
        """홍인기 자동매매 중지."""
        if not self.hongstyle_runner:
            return {"success": False, "message": "홍인기 Runner 미초기화"}
        return await self.hongstyle_runner.stop()

    def get_hongstyle_status(self) -> dict:
        """홍인기 자동매매 상태."""
        if not self.hongstyle_runner:
            return {"enabled": False, "state": "IDLE"}
        return self.hongstyle_runner.get_status()

    # ── 경윤 수정 매매법 제어 ─────────────────────────────

    async def start_gylee(self) -> dict:
        """경윤 자동매매 시작."""
        if not self.gylee_runner:
            return {"success": False, "message": "경윤 Runner 미초기화"}
        return await self.gylee_runner.start()

    async def stop_gylee(self) -> dict:
        """경윤 자동매매 중지."""
        if not self.gylee_runner:
            return {"success": False, "message": "경윤 Runner 미초기화"}
        return await self.gylee_runner.stop()

    def get_gylee_status(self) -> dict:
        """경윤 자동매매 상태."""
        if not self.gylee_runner:
            return {"enabled": False, "state": "IDLE"}
        return self.gylee_runner.get_status()
