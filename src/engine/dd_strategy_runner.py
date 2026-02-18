"""데이터드리븐 전략 Runner - strategy 1 + strategy 3.

시뮬레이션(simulate_combined_v2.py)과 동일하게
- MorningRSINeutralATRStrategy (전략1: 09:30~11시)
- ModifiedRSINeutralATRStrategy (전략3: 09~14시)
를 실시간 5분봉(aggregator) 기반으로 실행.

SL=3%, TP=5% (전량매도), 포지션사이징=40%.
GyleeRunner와 포지션 한도 공유 (총 max_positions=3).
"""

import asyncio
from datetime import datetime, time
from typing import Optional

from loguru import logger

from src.config.settings import settings
from src.engine.scheduler import is_market_hours
from src.strategies.data_driven.intraday_strategy_1 import (
    MorningRSINeutralATRStrategy,
)
from src.strategies.data_driven.intraday_strategy_3 import (
    ModifiedRSINeutralATRStrategy,
)


class DDStrategyRunner:
    """데이터드리븐 전략 라이브 Runner."""

    STRATEGY_PREFIX = "DD_"

    # 시뮬레이션 동일 파라미터
    DD_SL = 0.03           # 3% 손절
    DD_TP = 0.05           # 5% 익절 (전량)
    DD_POSITION_PCT = 0.40  # 포지션당 40%

    def __init__(self, engine):
        self.engine = engine
        self.enabled = False
        self._scan_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None

        # 전략 인스턴스
        self.strategies = [
            MorningRSINeutralATRStrategy(),
            ModifiedRSINeutralATRStrategy(),
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

    async def start(self) -> dict:
        """DD 자동매매 시작."""
        if self.enabled:
            return {"success": False, "message": "DD Runner 이미 실행 중"}

        self.enabled = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._position_monitor_loop())

        self._add_event("DD_STARTED", "DD 전략 시작 (전략1+3)")
        logger.info("DD 전략 Runner 시작")
        return {"success": True, "message": "DD 전략 시작 (전략1+3)"}

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
        """3분 간격 DD 전략 스캔.

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
                    await asyncio.sleep(180)
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
                            # daily_context 없이 실행 (hong_filter bypass)
                            strategy.set_daily_context(code, now.date(), None)
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

                await asyncio.sleep(180)

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
        """5초 간격 DD 포지션 모니터.

        시뮬레이션과 동일:
        - SL 3% → 전량 매도
        - TP 5% → 전량 매도 (분매 없음)
        """
        while self.enabled:
            try:
                # 장 시간 외에는 SL/TP 체크 안 함 (휴장일/시간외 손절 방지)
                if not is_market_hours():
                    await asyncio.sleep(5)
                    continue

                dd_positions = self._get_dd_positions()
                if not dd_positions:
                    await asyncio.sleep(5)
                    continue

                for code, pos in dd_positions:
                    if pos.current_price <= 0:
                        continue

                    pnl_pct = pos.unrealized_pnl_pct / 100

                    # 1. 손절 (-3%)
                    if pnl_pct <= -self.DD_SL:
                        await self._execute_sell(code, pos.quantity, "손절")
                        self._add_event(
                            "DD_SL",
                            f"DD 손절: {pos.stock_name} "
                            f"({pnl_pct * 100:+.1f}%)",
                            severity="WARNING",
                        )
                        continue

                    # 2. 익절 (+5%) - 전량 매도
                    if pnl_pct >= self.DD_TP:
                        await self._execute_sell(code, pos.quantity, "익절")
                        self._add_event(
                            "DD_TP",
                            f"DD 익절: {pos.stock_name} "
                            f"({pnl_pct * 100:+.1f}%)",
                        )
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
                    stop_loss_pct=self.DD_SL,
                    take_profit_pct=self.DD_TP,
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
        self, stock_code: str, quantity: int, reason: str
    ):
        """DD 매도 실행 (전량)."""
        try:
            from src.broker.kis_models import OrderSide, OrderType

            pos = self.engine.position_manager.get_position(stock_code)
            if not pos:
                return

            price = pos.current_price
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
            from src.server.websocket_hub import hub

            asyncio.create_task(hub.broadcast_stockking(event))
        except Exception:
            pass

        self.engine.add_log(f"DD_{event_type}", message, severity)
