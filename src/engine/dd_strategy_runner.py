"""데이터드리븐 전략 Runner - 갭 반전 전략 전용.

최적화 결과 (2026-02-27):
- 전략1(morning_rsi) WR 41.7%, 전략3(modified_rsi) WR 53.4% → 제거
- 갭 반전(opening_gap_reversal) WR 62.1% → 단독 실행
- SL 3%→4% (넓은 손절로 WR +7.4%p, MDD -5%→-3.1%)
- 경윤 v6.2는 GyleeRunner에서 별도 실행

SL=4%, TP=5% (전량매도), 포지션사이징=40%.
GyleeRunner와 포지션 한도 공유 (총 max_positions=3).
"""

import asyncio
from datetime import datetime, time
from typing import Optional

from loguru import logger

from src.config.settings import settings
from src.engine.scheduler import is_market_hours
from src.strategies.data_driven.intraday_strategy_gap import (
    OpeningGapReversalStrategy,
)


class DDStrategyRunner:
    """데이터드리븐 전략 라이브 Runner."""

    STRATEGY_PREFIX = "DD_"

    # 최적화 파라미터 (2026-02-27)
    DD_SL = 0.04           # 4% 손절 (WR +7.4%p, MDD 개선)
    DD_TP = 0.05           # 5% 익절 (전량)
    DD_POSITION_PCT = 0.40  # 포지션당 40%

    def __init__(self, engine):
        self.engine = engine
        self.enabled = False
        self._scan_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None

        # 전략 인스턴스 (갭 반전만 - 최적화 결과)
        self.strategies = [
            OpeningGapReversalStrategy(),
        ]

        # 상태
        self._trades_today: list[dict] = []
        self._events: list[dict] = []
        self._last_scan_time: Optional[datetime] = None
        self._entered_today: dict[str, set] = {
            s.name: set() for s in self.strategies
        }
        self._scan_stats: dict = {
            "stocks_scanned": 0,
            "signals_found": 0,
            "entries_executed": 0,
        }
        self._daily_context: dict = {}  # {code: {date: StockDailyContext}}

    async def start(self) -> dict:
        """DD 자동매매 시작."""
        if self.enabled:
            return {"success": False, "message": "DD Runner 이미 실행 중"}

        self.enabled = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._position_monitor_loop())

        self._add_event("DD_STARTED", "DD 전략 시작 (갭반전 SL4%)")
        logger.info("DD 전략 Runner 시작 (갭반전 SL4%)")
        return {"success": True, "message": "DD 전략 시작 (전략1+3+갭반전)"}

    async def stop(self) -> dict:
        """DD 자동매매 중지."""
        self.enabled = False
        for task in [self._scan_task, self._monitor_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._scan_task = None
        self._monitor_task = None
        self._add_event("DD_STOPPED", "DD 전략 중지")
        logger.info("DD 전략 Runner 중지")
        return {"success": True, "message": "DD 전략 중지"}

    def _count_strategy_positions(self) -> int:
        """전략이 진입한 포지션만 카운트 (기존보유 제외)."""
        return sum(
            1
            for pos in self.engine.position_manager.positions.values()
            if pos.strategy_name != "기존보유"
        )

    # ══════════════════════════════════════════════════════
    #  스캔 루프
    # ══════════════════════════════════════════════════════

    async def _scan_loop(self):
        """1분 간격 DD 전략 스캔.

        모든 종목의 최신 5분봉에서 전략1/3의 진입 시그널 확인.
        시뮬레이션과 동일하게 precompute_day + check_entry_fast 사용.
        """
        while self.enabled:
            try:
                now = datetime.now()
                current_time = now.time()

                # 장 시간 체크 (09:05 ~ 15:20)
                if current_time < time(9, 5) or current_time > time(15, 20):
                    await asyncio.sleep(30)
                    continue

                self._last_scan_time = now

                if not self.engine.data_manager:
                    await asyncio.sleep(60)
                    continue

                # 포지션 한도 체크
                total_pos = self._count_strategy_positions()
                if total_pos >= settings.max_positions:
                    await asyncio.sleep(60)
                    continue

                # 모든 종목 스캔
                all_bars = self.engine.data_manager.aggregator._completed_bars
                stocks_scanned = 0
                pending_signals = []

                for code, bars in all_bars.items():
                    if not bars or len(bars) < 15:
                        continue

                    # DataFrame 변환
                    df = self.engine.data_manager.aggregator.to_dataframe(code)
                    if df.empty or len(df) < 15:
                        continue

                    stocks_scanned += 1

                    for si, strategy in enumerate(self.strategies):
                        # 이미 오늘 진입한 종목 스킵
                        if code in self._entered_today[strategy.name]:
                            continue

                        # 이미 보유 중인 종목 스킵
                        if self.engine.position_manager.has_position(code):
                            continue

                        try:
                            # daily_context 로드 (Hong Strong 등 필터용)
                            ctx = None
                            if code in self._daily_context:
                                ctx = self._daily_context[code].get(now.date())
                            strategy.set_daily_context(code, now.date(), ctx)
                            indicators = strategy.precompute_day(df)
                            last_idx = indicators["n_bars"] - 1

                            signal = strategy.check_entry_fast(
                                code, last_idx, indicators
                            )

                            if signal:
                                price = float(indicators["close"][last_idx])
                                pending_signals.append({
                                    "code": code,
                                    "strategy_idx": si,
                                    "strategy_name": strategy.name,
                                    "price": price,
                                    "signal": signal,
                                    "confidence": signal.get(
                                        "confidence", 1.0
                                    ),
                                })
                        except Exception as e:
                            logger.debug(
                                f"DD 전략 체크 실패 {code}/{strategy.name}: {e}"
                            )

                self._scan_stats["stocks_scanned"] = stocks_scanned
                self._scan_stats["signals_found"] = len(pending_signals)

                # 확신도순 정렬
                pending_signals.sort(
                    key=lambda x: x["confidence"], reverse=True
                )

                # 진입 실행
                entries_executed = 0
                for sig in pending_signals:
                    total_pos = self._count_strategy_positions()
                    if total_pos >= settings.max_positions:
                        break

                    if self.engine.position_manager.has_position(sig["code"]):
                        continue

                    stock_name = (
                        self.engine.data_manager.get_stock_name(sig["code"])
                        or sig["code"]
                    )

                    self._add_event(
                        "DD_SIGNAL",
                        f"DD 시그널: {stock_name} [{sig['strategy_name']}] "
                        f"conf={sig['confidence']:.2f}",
                    )

                    await self._execute_buy(
                        stock_code=sig["code"],
                        stock_name=stock_name,
                        strategy_name=sig["strategy_name"],
                        price=sig["price"],
                        signal=sig["signal"],
                    )
                    self._entered_today[sig["strategy_name"]].add(sig["code"])
                    entries_executed += 1

                self._scan_stats["entries_executed"] = entries_executed

                if pending_signals:
                    self._add_event(
                        "DD_SCAN",
                        f"DD 스캔: {stocks_scanned}종목, "
                        f"시그널 {len(pending_signals)}건, "
                        f"진입 {entries_executed}건",
                    )

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DD 스캔 루프 오류: {e}")
                self._add_event(
                    "ERROR", f"DD 스캔 오류: {e}", severity="WARNING"
                )
                await asyncio.sleep(60)

    # ══════════════════════════════════════════════════════
    #  포지션 모니터 (SL 3% / TP 5% 전량매도)
    # ══════════════════════════════════════════════════════

    async def _position_monitor_loop(self):
        """5분봉 기반 DD 포지션 모니터.

        백테스트(intraday_engine_v2)와 동일한 방법론:
        - 5분봉 완성 시에만 SL/TP 체크
        - bar LOW <= stop_loss_price → 손절
        - bar HIGH >= take_profit_price → 익절
        - 전량 매도 (분매 없음)
        """
        last_checked_bar: dict[str, datetime] = {}

        while self.enabled:
            try:
                if not is_market_hours():
                    await asyncio.sleep(5)
                    continue

                dd_positions = self._get_dd_positions()
                if not dd_positions:
                    await asyncio.sleep(5)
                    continue

                for code, pos in dd_positions:
                    # 5분봉 데이터 가져오기
                    df = self.engine.data_manager.get_today_df(code)

                    if df.empty:
                        # 봉 데이터 없음 → 실시간 가격으로 fallback (재시작 직후 등)
                        if pos.current_price > 0:
                            if pos.current_price <= pos.stop_loss_price:
                                await self._execute_sell(
                                    code, pos.quantity, "손절",
                                    exit_price=pos.stop_loss_price,
                                )
                                self._add_event(
                                    "DD_SL",
                                    f"DD 손절(fallback): {pos.stock_name}",
                                    severity="WARNING",
                                )
                            elif pos.current_price >= pos.take_profit_price:
                                await self._execute_sell(
                                    code, pos.quantity, "익절",
                                    exit_price=pos.take_profit_price,
                                )
                                self._add_event(
                                    "DD_TP",
                                    f"DD 익절(fallback): {pos.stock_name}",
                                )
                        continue

                    # 새 봉이 완성됐는지 확인
                    latest_bar_time = df.index[-1]
                    prev = last_checked_bar.get(code)
                    if prev is not None and latest_bar_time <= prev:
                        # 새 봉 없음 → 실시간 가격으로 SL/TP 체크
                        cp = pos.current_price
                        if cp > 0:
                            if cp <= pos.stop_loss_price:
                                pnl_pct = (
                                    pos.stop_loss_price / pos.avg_price - 1
                                ) * 100
                                await self._execute_sell(
                                    code, pos.quantity, "손절",
                                    exit_price=pos.stop_loss_price,
                                )
                                self._add_event(
                                    "DD_SL",
                                    f"DD 손절(실시간): {pos.stock_name} "
                                    f"({pnl_pct:+.1f}%) "
                                    f"[현재가={cp:,.0f}]",
                                    severity="WARNING",
                                )
                                last_checked_bar.pop(code, None)
                            elif cp >= pos.take_profit_price:
                                pnl_pct = (
                                    pos.take_profit_price / pos.avg_price - 1
                                ) * 100
                                await self._execute_sell(
                                    code, pos.quantity, "익절",
                                    exit_price=pos.take_profit_price,
                                )
                                self._add_event(
                                    "DD_TP",
                                    f"DD 익절(실시간): {pos.stock_name} "
                                    f"({pnl_pct:+.1f}%) "
                                    f"[현재가={cp:,.0f}]",
                                )
                                last_checked_bar.pop(code, None)
                        continue

                    last_checked_bar[code] = latest_bar_time

                    # bar LOW/HIGH로 SL/TP 판단 (백테스트와 동일)
                    bar_low = float(df.iloc[-1]["low"])
                    bar_high = float(df.iloc[-1]["high"])

                    # 1. 손절: bar LOW가 SL 가격 이하
                    if bar_low <= pos.stop_loss_price:
                        pnl_pct = (pos.stop_loss_price / pos.avg_price - 1) * 100
                        await self._execute_sell(
                            code, pos.quantity, "손절",
                            exit_price=pos.stop_loss_price,
                        )
                        self._add_event(
                            "DD_SL",
                            f"DD 손절: {pos.stock_name} "
                            f"({pnl_pct:+.1f}%) [5분봉 LOW={bar_low:,.0f}]",
                            severity="WARNING",
                        )
                        last_checked_bar.pop(code, None)
                        continue

                    # 2. 익절: bar HIGH가 TP 가격 이상
                    if bar_high >= pos.take_profit_price:
                        pnl_pct = (pos.take_profit_price / pos.avg_price - 1) * 100
                        await self._execute_sell(
                            code, pos.quantity, "익절",
                            exit_price=pos.take_profit_price,
                        )
                        self._add_event(
                            "DD_TP",
                            f"DD 익절: {pos.stock_name} "
                            f"({pnl_pct:+.1f}%) [5분봉 HIGH={bar_high:,.0f}]",
                        )
                        last_checked_bar.pop(code, None)
                        continue

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DD 모니터 오류: {e}")
                await asyncio.sleep(5)

    # ══════════════════════════════════════════════════════
    #  매수/매도 실행
    # ══════════════════════════════════════════════════════

    async def _execute_buy(
        self,
        stock_code: str,
        stock_name: str,
        strategy_name: str,
        price: float,
        signal: dict,
    ):
        """DD 매수 실행."""
        try:
            from src.broker.kis_models import OrderSide, OrderType

            current_price = (
                await self.engine.data_manager.fetch_current_price(stock_code)
            )
            if current_price <= 0:
                current_price = int(price)

            # 포지션 사이징 (40%)
            total_equity = self.engine.position_manager.total_equity
            if total_equity <= 0:
                return

            max_amount = total_equity * self.DD_POSITION_PCT
            qty = int(max_amount / current_price)
            if qty <= 0:
                return

            # 리스크 체크
            order_value = current_price * qty
            risk_check = self.engine.risk_manager.check_pre_trade(
                stock_code, order_value
            )
            if not risk_check.allowed:
                self._add_event(
                    "RISK_REJECT",
                    f"리스크 거부: {stock_name} - {risk_check.reason}",
                )
                return

            full_name = f"{self.STRATEGY_PREFIX}{strategy_name}"

            order = await self.engine.order_manager.submit_order(
                stock_code=stock_code,
                side=OrderSide.BUY,
                quantity=qty,
                order_type=OrderType.MARKET,
                strategy_name=full_name,
            )

            from src.broker.kis_models import OrderStatus

            if order.status == OrderStatus.SUBMITTED:
                self.engine.position_manager.open_position(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    strategy_name=full_name,
                    quantity=qty,
                    price=current_price,
                    stop_loss_pct=signal.get("stop_loss", self.DD_SL),
                    take_profit_pct=signal.get("take_profit", self.DD_TP),
                    order_id=order.order_id,
                )

                if self.engine.data_manager:
                    self.engine.data_manager.add_priority_codes({stock_code})

                trade_info = {
                    "type": "buy",
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "strategy_name": full_name,
                    "quantity": qty,
                    "price": current_price,
                    "time": datetime.now().isoformat(),
                }
                self._trades_today.append(trade_info)

                self._add_event(
                    "DD_BUY",
                    f"DD 매수: {stock_name} {qty}주 @{current_price:,.0f} "
                    f"[{strategy_name}]",
                )

                await self.engine._emit_position_update()
                await self.engine._emit_order(order)

                logger.info(
                    f"DD 매수: {stock_name}({stock_code}) "
                    f"{qty}주 @{current_price:,.0f} [{strategy_name}]"
                )

        except Exception as e:
            logger.error(f"DD 매수 실행 실패 ({stock_code}): {e}")
            self._add_event(
                "ERROR",
                f"DD 매수 실패: {stock_name} - {e}",
                severity="WARNING",
            )

    async def _execute_sell(
        self, stock_code: str, quantity: int, reason: str,
        exit_price: float = 0,
    ):
        """DD 매도 실행 (전량).

        exit_price: 백테스트 호환용 SL/TP 가격. 0이면 현재가 사용.
        """
        try:
            from src.broker.kis_models import OrderSide, OrderType

            pos = self.engine.position_manager.get_position(stock_code)
            if not pos:
                return

            # 백테스트 호환: SL/TP 가격이 지정되면 그 가격으로 청산 기록
            price = exit_price if exit_price > 0 else pos.current_price
            if price <= 0:
                price = (
                    await self.engine.data_manager.fetch_current_price(
                        stock_code
                    )
                )

            order = await self.engine.order_manager.submit_order(
                stock_code=stock_code,
                side=OrderSide.SELL,
                quantity=quantity,
                order_type=OrderType.MARKET,
                strategy_name=pos.strategy_name,
            )

            # 주문 거부 시 포지션 유지
            from src.broker.kis_models import OrderStatus
            if order.status == OrderStatus.REJECTED:
                logger.warning(
                    f"DD 매도 주문 거부됨: {stock_code} - 포지션 유지"
                )
                self._add_event(
                    "SELL_REJECTED",
                    f"매도 거부: {pos.stock_name} - 포지션 유지",
                    severity="WARNING",
                )
                return

            trade = self.engine.position_manager.close_position(
                stock_code, price, reason
            )

            if trade:
                trade_info = {
                    "type": "sell",
                    "stock_code": stock_code,
                    "stock_name": pos.stock_name,
                    "strategy_name": pos.strategy_name,
                    "quantity": quantity,
                    "price": price,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "exit_reason": reason,
                    "time": datetime.now().isoformat(),
                }
                self._trades_today.append(trade_info)

                # DB에 거래 기록 저장
                self.engine.trade_store.save_trade({
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

                await self.engine._emit_position_update()
                await self.engine._emit_order(order)

                if self.engine.data_manager:
                    self.engine.data_manager.remove_priority_codes(
                        {stock_code}
                    )

        except Exception as e:
            logger.error(f"DD 매도 실행 실패 ({stock_code}): {e}")

    # ══════════════════════════════════════════════════════
    #  유틸리티
    # ══════════════════════════════════════════════════════

    def _get_dd_positions(self):
        """DD 전략 포지션만 필터."""
        result = []
        for code, pos in self.engine.position_manager.positions.items():
            if pos.strategy_name.startswith(self.STRATEGY_PREFIX):
                result.append((code, pos))
        return result

    def get_status(self) -> dict:
        """DD Runner 상태."""
        return {
            "enabled": self.enabled,
            "strategies": [s.name for s in self.strategies],
            "positions_count": len(self._get_dd_positions()),
            "trades_today": len(self._trades_today),
            "day_pnl": sum(
                t.get("pnl", 0)
                for t in self._trades_today
                if "pnl" in t
            ),
            "last_scan_time": (
                self._last_scan_time.isoformat()
                if self._last_scan_time
                else None
            ),
            "scan_stats": self._scan_stats,
        }

    def get_trades(self) -> list[dict]:
        """DD 오늘 거래 반환."""
        return list(self._trades_today)

    def get_events(self, limit: int = 50) -> list[dict]:
        """최근 이벤트."""
        return list(reversed(self._events[-limit:]))

    def reset_daily(self):
        """일일 리셋."""
        self._trades_today.clear()
        self._events.clear()
        self._last_scan_time = None
        self._entered_today = {s.name: set() for s in self.strategies}
        self._scan_stats = {
            "stocks_scanned": 0,
            "signals_found": 0,
            "entries_executed": 0,
        }
        self._load_daily_context()
        self._load_prev_day_data()
        self._load_news_scores()

    def _load_daily_context(self):
        """Hong Strong 필터용 일별 컨텍스트 로드 (하루 1회).

        DailyContextLoader로 시총/기관/일봉자리 등 로드.
        갭 전략의 Hong Strong 필터에 필수.
        """
        try:
            from src.strategies.data_driven.daily_context import DailyContextLoader

            today = datetime.now().date()

            # aggregator에서 종목 코드 수집
            codes = []
            if self.engine.data_manager:
                all_bars = self.engine.data_manager.aggregator._completed_bars
                codes = list(all_bars.keys())

            if not codes:
                # fallback: DB에서 최근 거래 종목
                from sqlalchemy import text
                from src.database.connection import get_backtest_engine as get_db_engine
                db_engine = get_db_engine()
                with db_engine.connect() as conn:
                    rows = conn.execute(text(
                        "SELECT DISTINCT code FROM ohlcv_daily "
                        "WHERE date = (SELECT MAX(date) FROM ohlcv_daily)"
                    )).fetchall()
                codes = [r[0] for r in rows]

            if not codes:
                logger.warning("daily_context: 종목 코드 없음")
                return

            loader = DailyContextLoader()
            from datetime import timedelta
            start = today - timedelta(days=5)
            self._daily_context = loader.load(codes, start, today)

            ctx_count = sum(len(v) for v in self._daily_context.values())
            logger.info(f"daily_context 로드: {len(codes)}종목, {ctx_count}건")

        except Exception as e:
            logger.error(f"daily_context 로드 실패: {e}")
            self._daily_context = {}

    def _load_prev_day_data(self):
        """갭 전략용 전일 종가/일간 거래량 로드 (하루 1회).

        avg_vol = 전일 일간 총 거래량 (전략에서 /78로 봉당 환산).
        """
        try:
            from sqlalchemy import text
            from src.database.connection import get_backtest_engine as get_db_engine

            today = datetime.now().date()
            db_engine = get_db_engine()

            with db_engine.connect() as conn:
                # 전일 종가 (가장 최근 거래일)
                rows = conn.execute(
                    text(
                        "SELECT code, close, volume FROM ohlcv_daily "
                        "WHERE date = (SELECT MAX(date) FROM ohlcv_daily WHERE date < :today)"
                    ),
                    {"today": today},
                ).fetchall()

            if not rows:
                logger.warning("갭 전략: 전일 일봉 데이터 없음")
                return

            prev_day_data = {}
            for code, close_price, volume in rows:
                if close_price and close_price > 0:
                    prev_day_data[code] = {
                        today: {
                            "close": float(close_price),
                            "avg_vol": float(volume or 0),
                        }
                    }

            for strategy in self.strategies:
                if hasattr(strategy, "_prev_day_data"):
                    strategy._prev_day_data = prev_day_data

            logger.info(f"갭 전략: 전일 데이터 {len(prev_day_data)}종목 로드")

        except Exception as e:
            logger.error(f"갭 전략 전일 데이터 로드 실패: {e}")

    def _load_news_scores(self):
        """갭 전략용 뉴스 확신 점수 로드 (하루 1회, 장 시작 전).

        네이버 금융에서 뉴스 크롤링 → GPT 감성분석.
        갭다운 후보 종목만 분석하여 비용 절감.
        """
        try:
            from src.news.news_score import compute_news_scores

            today = datetime.now().date()

            # 갭 전략에 전일 데이터가 있는 종목만 뉴스 조회
            gap_strategy = None
            for strategy in self.strategies:
                if hasattr(strategy, "_news_scores"):
                    gap_strategy = strategy
                    break

            if not gap_strategy:
                return

            # 전일 데이터가 있는 종목 중 상위 100개만 (비용 절감)
            codes_with_data = []
            for strategy in self.strategies:
                if hasattr(strategy, "_prev_day_data"):
                    codes_with_data = list(strategy._prev_day_data.keys())[:100]
                    break

            if not codes_with_data:
                return

            scores = compute_news_scores(
                codes_with_data,
                target_date=today,
                max_articles=5,
            )

            if scores:
                # {code: {date: score}} 형식으로 변환
                news_data = {}
                for code, score in scores.items():
                    news_data[code] = {today: score}

                for strategy in self.strategies:
                    if hasattr(strategy, "_news_scores"):
                        strategy._news_scores = news_data

                self._add_event(
                    "NEWS_LOADED",
                    f"뉴스 분석: {len(scores)}종목 "
                    f"(긍정 {sum(1 for s in scores.values() if s > 0)}건)",
                )
                logger.info(f"뉴스 점수 로드: {len(scores)}종목")

        except Exception as e:
            logger.warning(f"뉴스 점수 로드 실패 (무시): {e}")

    def _add_event(
        self, event_type: str, message: str, severity: str = "INFO"
    ):
        """이벤트 추가."""
        event = {
            "event_type": event_type,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now().isoformat(),
        }
        self._events.append(event)
        if len(self._events) > 200:
            self._events = self._events[-200:]

        try:
            loop = asyncio.get_running_loop()
            from src.server.websocket_hub import hub
            loop.create_task(hub.broadcast_stockking(event))
        except RuntimeError:
            pass
        except Exception:
            pass

        self.engine.add_log(f"DD_{event_type}", message, severity)
