"""홍인기 전략 자동매매 Runner.

기존 StrategyRunner와 독립적으로 동작하며,
HongStyleEngine(Phase 1)의 분석 결과를 기반으로 매매 실행.
"""

import asyncio
from datetime import datetime, time
from typing import Optional

from loguru import logger

from src.strategies.hongstyle.hongstyle_engine import get_hongstyle_engine
from src.strategies.hongstyle.signal_generator import SignalGenerator, EntrySignal
from src.engine.scheduler import is_market_hours


class HongStyleRunner:
    """홍인기 전략 자동매매 Runner.

    스캔 간격: 3분 (외부 API rate limit 고려)
    기존 StrategyRunner와 병렬 동작, OrderManager/PositionManager 공유.
    """

    # 시간대 설정
    MORNING_START = time(9, 5)
    MORNING_END = time(11, 30)
    AFTERNOON_START = time(13, 0)
    AFTERNOON_END = time(14, 30)

    # 집중투자 포지션 사이징
    HIGH_CONFIDENCE_PCT = 0.40    # 확신 종목: 총자산 40% (그리드서치 최적)
    LOW_CONFIDENCE_PCT = 0.20     # 보통 종목: 총자산 20% (그리드서치 최적)
    CONFIDENCE_THRESHOLD = 0.7    # 확신/보통 경계
    KI_THRESHOLD = 50             # 끼 50 이상이어야 확신 배분

    # 집중투자 제한
    MAX_POSITIONS = 2             # 최대 2종목만 보유
    TOP_N_ONLY = 5                # 확신도 상위 5개만 진입 대상

    # 리스크 관리
    MIN_CONFIDENCE = 0.5          # 최소 진입 확신도 (TOP 5 내에서)
    MAX_CONSECUTIVE_LOSSES = 2    # 2연속 손절 → 당일 종료
    STOP_LOSS_PCT = 0.04          # -4% 손절
    TAKE_PROFIT_PCT = 0.05        # +5% 1차 익절
    PARTIAL_SELL_RATIO = 0.7      # 70% 분할매도
    BREAKEVEN_CUT_PCT = 0.005     # +0.5% 이하 → 본전컷

    def __init__(self, engine):
        """Initialize HongStyleRunner.

        Args:
            engine: TradingEngine 인스턴스 (부모 엔진)
        """
        self.engine = engine
        self.hongstyle_engine = get_hongstyle_engine()
        self.signal_generator = SignalGenerator()
        self.enabled = False
        self._scan_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None

        # 홍인기 리스크 상태
        self._consecutive_losses = 0
        self._day_stopped = False
        self._trades_today: list[dict] = []
        self._events: list[dict] = []
        self._last_scan_time: Optional[datetime] = None

        # 확신도 순위 (프론트엔드 표시용)
        self._conviction_ranking: list[dict] = []
        self._top_codes: set[str] = set()

    async def start(self) -> dict:
        """홍인기 자동매매 시작."""
        if self.enabled:
            return {"success": False, "message": "이미 실행 중"}

        self.enabled = True
        self._day_stopped = False
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._position_monitor_loop())

        self._add_event("HONG_STARTED", "홍인기 자동매매 시작")
        logger.info("홍인기 자동매매 시작")
        return {"success": True, "message": "홍인기 자동매매 시작"}

    async def stop(self) -> dict:
        """홍인기 자동매매 중지."""
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
        self._add_event("HONG_STOPPED", "홍인기 자동매매 중지")
        logger.info("홍인기 자동매매 중지")
        return {"success": True, "message": "홍인기 자동매매 중지"}

    @staticmethod
    def _calc_conviction_score(confidence: float, ki_score: float, is_leader: bool) -> float:
        """확신도 점수 계산.

        공식: confidence × (ki_score / 100) × 대장주보너스(1.3x)
        """
        score = confidence * (ki_score / 100.0)
        if is_leader:
            score *= 1.3
        return round(score, 4)

    async def _scan_loop(self):
        """3분 간격 스캔 루프 (집중투자 모드).

        1. HongStyleEngine.run_analysis() → 주도 섹터/대장주/시그널
        2. 확신도 점수 계산 → 전체 순위 매기기
        3. TOP 5 선정 → 이 종목만 진입 대상
        4. buy 시그널 + TOP 5 → 포지션 50%/30% 집중 배분
        """
        while self.enabled:
            try:
                if self._day_stopped:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now()
                current_time = now.time()

                # 장 시간 외 스킵
                if current_time < self.MORNING_START or current_time > time(15, 20):
                    await asyncio.sleep(30)
                    continue

                self._last_scan_time = now
                self._add_event("SCAN", f"스캔 시작 ({now.strftime('%H:%M:%S')})")

                # 분석 실행
                result = await self.hongstyle_engine.run_analysis()

                # 자제일 체크
                if result.is_caution_day:
                    self._add_event("CAUTION", "매매 자제일 - 스킵")
                    await asyncio.sleep(180)
                    continue

                # ── 확신도 순위 계산 ──
                ranking = []
                for sa in result.stock_analyses:
                    sig = sa.entry_signal
                    ki = sa.ki_score.score
                    score = self._calc_conviction_score(
                        sig.confidence, ki, sa.is_leader
                    )
                    is_buyable = (
                        sig.action == "buy" and sig.confidence >= self.MIN_CONFIDENCE
                    )

                    # 배분 결정
                    if sig.confidence >= self.CONFIDENCE_THRESHOLD and ki >= self.KI_THRESHOLD:
                        alloc_pct = self.HIGH_CONFIDENCE_PCT
                        alloc_label = "확신"
                    else:
                        alloc_pct = self.LOW_CONFIDENCE_PCT
                        alloc_label = "보통"

                    ranking.append({
                        "rank": 0,
                        "stock_code": sa.code,
                        "stock_name": sa.name,
                        "score": score,
                        "confidence": sig.confidence,
                        "ki_score": ki,
                        "is_leader": sa.is_leader,
                        "leader_bonus": 1.3 if sa.is_leader else 1.0,
                        "daily_position": sa.daily_position.position_type,
                        "position_desc": sa.daily_position.description,
                        "method": sig.method,
                        "action": sig.action,
                        "reason": sig.reason,
                        "alloc_pct": alloc_pct,
                        "alloc_label": alloc_label,
                        "is_buyable": is_buyable,
                        "is_top": False,
                        "patterns": [p.pattern_name for p in sa.patterns],
                    })

                # 매수가능 종목만 확신도순 정렬
                buyable = [r for r in ranking if r["is_buyable"]]
                buyable.sort(key=lambda x: x["score"], reverse=True)

                # TOP N 선정
                top_codes = set()
                for i, item in enumerate(buyable[:self.TOP_N_ONLY]):
                    item["is_top"] = True
                    top_codes.add(item["stock_code"])

                # 전체 순위 (매수불가 포함) 재정렬
                ranking.sort(key=lambda x: x["score"], reverse=True)
                for i, item in enumerate(ranking):
                    item["rank"] = i + 1

                self._conviction_ranking = ranking
                self._top_codes = top_codes

                # ── TOP 5 중 진입 실행 ──
                hong_pos_count = len(self._get_hong_positions_raw())
                for item in buyable:
                    if item["stock_code"] not in top_codes:
                        continue
                    if hong_pos_count >= self.MAX_POSITIONS:
                        break
                    if self.engine.position_manager.has_position(item["stock_code"]):
                        continue

                    # 시간대에 따른 확신도 조정
                    adjusted_confidence = item["confidence"]
                    if not (self.MORNING_START <= current_time <= self.MORNING_END):
                        adjusted_confidence -= 0.1
                    if adjusted_confidence < self.MIN_CONFIDENCE:
                        continue

                    await self._execute_buy(
                        stock_code=item["stock_code"],
                        stock_name=item["stock_name"],
                        signal=self._find_signal(result, item["stock_code"]),
                        ki_score=item["ki_score"],
                    )
                    hong_pos_count += 1

                await asyncio.sleep(180)  # 3분 간격

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"홍인기 스캔 루프 오류: {e}")
                self._add_event("ERROR", f"스캔 오류: {e}", severity="WARNING")
                await asyncio.sleep(60)

    @staticmethod
    def _find_signal(result, stock_code: str) -> EntrySignal:
        """분석 결과에서 특정 종목의 EntrySignal 찾기."""
        for sa in result.stock_analyses:
            if sa.code == stock_code:
                return sa.entry_signal
        return EntrySignal(
            action="skip", method="", confidence=0, reason="시그널 없음"
        )

    async def _position_monitor_loop(self):
        """5초 간격 홍인기 포지션 모니터.

        - strategy_name이 "홍스타일_"로 시작하는 포지션만 대상
        - 패턴 감지 → 즉시 매도 (가분수, 끼소진, 거래량고점)
        - 분할매도: +5% → 70% 익절
        - 본전컷: partial_sold 후 원가 복귀 → 잔여 전량 매도
        - 손절: -4% → 전량 매도 + 연속손절 카운트
        """
        while self.enabled:
            try:
                # 장 시간 외에는 SL/TP 체크 안 함 (휴장일/시간외 손절 방지)
                if not is_market_hours():
                    await asyncio.sleep(5)
                    continue

                hong_positions = self._get_hong_positions_raw()
                if not hong_positions:
                    await asyncio.sleep(5)
                    continue

                for code, pos in hong_positions:
                    if pos.current_price <= 0:
                        continue

                    pnl_pct = pos.unrealized_pnl_pct / 100  # % → ratio

                    # 1. 손절 체크 (-4%)
                    if pnl_pct <= -self.STOP_LOSS_PCT:
                        await self._execute_sell(
                            code, pos.quantity, "손절"
                        )
                        self._consecutive_losses += 1
                        self._add_event(
                            "STOP_LOSS",
                            f"손절: {pos.stock_name} ({pnl_pct*100:+.1f}%) "
                            f"연속손절={self._consecutive_losses}",
                            severity="WARNING",
                        )
                        if self._consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
                            self._day_stopped = True
                            self._add_event(
                                "DAY_STOP",
                                f"2연속 손절 → 당일 매매 종료",
                                severity="CRITICAL",
                            )
                        continue

                    # 2. 분할매도 체크 (+5%, partial 안 한 경우)
                    if (
                        pnl_pct >= self.TAKE_PROFIT_PCT
                        and not pos.partial_sold
                    ):
                        sell_qty = int(pos.quantity * self.PARTIAL_SELL_RATIO)
                        if sell_qty > 0:
                            await self._execute_partial_sell(
                                code, sell_qty, "1차익절"
                            )
                            self._consecutive_losses = 0  # 익절 시 연속손절 리셋
                        continue

                    # 3. 본전컷 (partial_sold 후 원가 복귀)
                    if pos.partial_sold and pnl_pct <= self.BREAKEVEN_CUT_PCT:
                        await self._execute_sell(
                            code, pos.quantity, "본전컷"
                        )
                        continue

                    # 4. 수익 중이면 연속손절 리셋
                    if pnl_pct > 0:
                        self._consecutive_losses = 0

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"홍인기 모니터 오류: {e}")
                await asyncio.sleep(5)

    async def _execute_buy(
        self, stock_code: str, stock_name: str, signal: EntrySignal, ki_score: float
    ):
        """매수 실행 - 끼 기반 포지션 사이징."""
        try:
            from src.broker.kis_models import OrderSide, OrderType

            # 현재가 조회
            price = await self.engine.data_manager.fetch_current_price(stock_code)
            if price <= 0:
                return

            # 포지션 사이징
            qty = self._calculate_hong_position_size(
                price, signal.confidence, ki_score
            )
            if qty <= 0:
                return

            # 리스크 체크
            order_value = price * qty
            risk_check = self.engine.risk_manager.check_pre_trade(
                stock_code, order_value
            )
            if not risk_check.allowed:
                self._add_event(
                    "RISK_REJECT",
                    f"리스크 거부: {stock_name} - {risk_check.reason}",
                )
                return

            # 전략 이름 결정
            strategy_name = f"홍스타일_{signal.method}"

            # 주문 실행
            order = await self.engine.order_manager.submit_order(
                stock_code=stock_code,
                side=OrderSide.BUY,
                quantity=qty,
                order_type=OrderType.MARKET,
                strategy_name=strategy_name,
            )

            from src.broker.kis_models import OrderStatus
            if order.status == OrderStatus.SUBMITTED:
                self.engine.position_manager.open_position(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    strategy_name=strategy_name,
                    quantity=qty,
                    price=price,
                    stop_loss_pct=signal.stop_loss,
                    take_profit_pct=signal.take_profit,
                    order_id=order.order_id,
                )

                # 우선 폴링 등록
                if self.engine.data_manager:
                    self.engine.data_manager.add_priority_codes({stock_code})

                trade_info = {
                    "type": "buy",
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "strategy_name": strategy_name,
                    "quantity": qty,
                    "price": price,
                    "confidence": signal.confidence,
                    "ki_score": ki_score,
                    "time": datetime.now().isoformat(),
                }
                self._trades_today.append(trade_info)

                self._add_event(
                    "BUY",
                    f"매수: {stock_name} {qty}주 @{price:,.0f} "
                    f"[{signal.method}] 확신도={signal.confidence:.0%}",
                )

                # 엔진 이벤트 방출
                await self.engine._emit_position_update()
                await self.engine._emit_order(order)

                logger.info(
                    f"홍인기 매수: {stock_name}({stock_code}) "
                    f"{qty}주 @{price:,.0f} [{signal.method}]"
                )

        except Exception as e:
            logger.error(f"홍인기 매수 실행 실패 ({stock_code}): {e}")
            self._add_event("ERROR", f"매수 실패: {stock_name} - {e}", severity="WARNING")

    async def _execute_sell(self, stock_code: str, quantity: int, reason: str):
        """전량 매도 실행."""
        try:
            from src.broker.kis_models import OrderSide, OrderType

            pos = self.engine.position_manager.get_position(stock_code)
            if not pos:
                return

            # 현재가 조회
            price = pos.current_price
            if price <= 0:
                price = await self.engine.data_manager.fetch_current_price(stock_code)

            # 주문 실행
            order = await self.engine.order_manager.submit_order(
                stock_code=stock_code,
                side=OrderSide.SELL,
                quantity=quantity,
                order_type=OrderType.MARKET,
                strategy_name=pos.strategy_name,
            )

            # 주문 거부 시 포지션 유지 (실제로 안 팔렸으므로)
            from src.broker.kis_models import OrderStatus
            if order.status == OrderStatus.REJECTED:
                logger.warning(
                    f"홍인기 매도 주문 거부됨: {stock_code} - 포지션 유지"
                )
                self._add_event(
                    "SELL_REJECTED",
                    f"매도 거부: {pos.stock_name} - 포지션 유지",
                    severity="WARNING",
                )
                return

            # 포지션 청산 (주문 접수 성공 시에만)
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

                # 엔진 이벤트 방출
                await self.engine._emit_position_update()
                await self.engine._emit_order(order)

                # 우선 폴링 해제
                if self.engine.data_manager:
                    self.engine.data_manager.remove_priority_codes({stock_code})

        except Exception as e:
            logger.error(f"홍인기 매도 실행 실패 ({stock_code}): {e}")
            self._add_event("ERROR", f"매도 실패: {stock_code} - {e}", severity="WARNING")

    async def _execute_partial_sell(self, stock_code: str, sell_quantity: int, reason: str):
        """분할매도 실행."""
        try:
            from src.broker.kis_models import OrderSide, OrderType

            pos = self.engine.position_manager.get_position(stock_code)
            if not pos:
                return

            price = pos.current_price
            if price <= 0:
                price = await self.engine.data_manager.fetch_current_price(stock_code)

            # 분할매도 주문
            order = await self.engine.order_manager.submit_order(
                stock_code=stock_code,
                side=OrderSide.SELL,
                quantity=sell_quantity,
                order_type=OrderType.MARKET,
                strategy_name=pos.strategy_name,
            )

            # 주문 거부 시 포지션 유지
            from src.broker.kis_models import OrderStatus
            if order.status == OrderStatus.REJECTED:
                logger.warning(
                    f"홍인기 분할매도 주문 거부됨: {stock_code} - 포지션 유지"
                )
                return

            # 부분 청산 (주문 접수 성공 시에만)
            trade = self.engine.position_manager.partial_close_position(
                stock_code, sell_quantity, price, reason
            )

            if trade:
                trade_info = {
                    "type": "partial_sell",
                    "stock_code": stock_code,
                    "stock_name": pos.stock_name,
                    "strategy_name": pos.strategy_name,
                    "quantity": sell_quantity,
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

                self._add_event(
                    "PARTIAL_SELL",
                    f"분할매도: {pos.stock_name} {sell_quantity}주 @{price:,.0f} "
                    f"PnL={trade.pnl:+,.0f} 잔여={pos.quantity}주",
                )

                await self.engine._emit_position_update()
                await self.engine._emit_order(order)

        except Exception as e:
            logger.error(f"홍인기 분할매도 실패 ({stock_code}): {e}")

    def _calculate_hong_position_size(
        self, price: float, confidence: float, ki_score: float
    ) -> int:
        """홍인기식 포지션 사이징 (집중투자).

        확신 종목 (confidence >= 0.7 AND 끼 >= 50): 총자산 50%
        보통 종목: 총자산 30%
        최대 2종목이므로 최대 80% 투자
        """
        total_equity = self.engine.position_manager.total_equity
        if total_equity <= 0 or price <= 0:
            return 0

        if (
            confidence >= self.CONFIDENCE_THRESHOLD
            and ki_score >= self.KI_THRESHOLD
        ):
            alloc_pct = self.HIGH_CONFIDENCE_PCT
        else:
            alloc_pct = self.LOW_CONFIDENCE_PCT

        max_amount = total_equity * alloc_pct
        qty = int(max_amount / price)
        return max(qty, 0)

    def _get_hong_positions_raw(self):
        """홍인기 전략 포지션만 필터 (raw LivePosition 리스트)."""
        result = []
        for code, pos in self.engine.position_manager.positions.items():
            if pos.strategy_name.startswith("홍스타일"):
                result.append((code, pos))
        return result

    def get_status(self) -> dict:
        """현재 상태 (프론트엔드용)."""
        state = "IDLE"
        if self._day_stopped:
            state = "DAY_STOPPED"
        elif self.enabled:
            state = "SCANNING"
            hong_positions = self._get_hong_positions_raw()
            if hong_positions:
                state = "TRADING"

        return {
            "enabled": self.enabled,
            "state": state,
            "consecutive_losses": self._consecutive_losses,
            "is_caution_day": self._day_stopped,
            "trades_today": len(self._trades_today),
            "positions_count": len(self._get_hong_positions_raw()),
            "day_pnl": sum(
                t.get("pnl", 0) for t in self._trades_today if "pnl" in t
            ),
            "last_scan_time": (
                self._last_scan_time.isoformat() if self._last_scan_time else None
            ),
            "max_positions": self.MAX_POSITIONS,
            "top_n": self.TOP_N_ONLY,
            "high_alloc": self.HIGH_CONFIDENCE_PCT,
            "low_alloc": self.LOW_CONFIDENCE_PCT,
        }

    def get_conviction_ranking(self) -> list[dict]:
        """확신도 순위 반환 (프론트엔드 표시용)."""
        return list(self._conviction_ranking)

    def get_hong_positions(self) -> list[dict]:
        """홍인기 전략 포지션만 반환."""
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
                "partial_sold": pos.partial_sold,
                "original_quantity": pos.original_quantity,
                "entry_time": pos.entry_time.isoformat(),
            }
            for _, pos in self._get_hong_positions_raw()
        ]

    def get_hong_trades(self) -> list[dict]:
        """홍인기 전략 오늘 거래만 반환."""
        return list(self._trades_today)

    def get_events(self, limit: int = 50) -> list[dict]:
        """최근 이벤트 로그."""
        return list(reversed(self._events[-limit:]))

    def reset_daily(self):
        """일일 리셋."""
        self._consecutive_losses = 0
        self._day_stopped = False
        self._trades_today.clear()
        self._events.clear()
        self._last_scan_time = None
        self._conviction_ranking.clear()
        self._top_codes.clear()

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

        # WebSocket 브로드캐스트 (fire-and-forget)
        try:
            loop = asyncio.get_running_loop()
            from src.server.websocket_hub import hub
            loop.create_task(hub.broadcast_stockking(event))
        except RuntimeError:
            pass
        except Exception:
            pass

        # 엔진 로그에도 기록
        self.engine.add_log(f"HONG_{event_type}", message, severity)
