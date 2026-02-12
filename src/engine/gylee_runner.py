"""경윤 수정 매매법 Runner.

HongStyleRunner를 상속하여 3개 필터(시총/기관/눌림)를 _scan_loop에 삽입.
포지션 모니터링(SL/TP)은 부모 그대로 재사용.
"""

import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger

from src.engine.hongstyle_runner import HongStyleRunner
from src.strategies.hongstyle.daily_filter_provider import (
    DailyFilterProvider,
    get_daily_filter_provider,
)


class GyleeRunner(HongStyleRunner):
    """경윤 수정 매매법 Runner - HongStyleRunner + 3개 필터."""

    STRATEGY_PREFIX = "경윤_"

    def __init__(self, engine):
        super().__init__(engine)
        self.filter_provider: DailyFilterProvider = get_daily_filter_provider()

        # 필터 통계 (대시보드용)
        self._filter_stats: dict = {
            "total_candidates": 0,
            "cap_filtered": 0,
            "inst_filtered": 0,
            "pullback_filtered": 0,
            "passed": 0,
        }

    async def start(self) -> dict:
        """경윤 자동매매 시작 - 필터 데이터 로드 후 스캔 시작."""
        if self.enabled:
            return {"success": False, "message": "이미 실행 중"}

        # 필터 데이터 갱신
        refresh_result = await self.filter_provider.refresh()
        if not refresh_result.get("success"):
            logger.warning(
                f"필터 데이터 로드 실패: {refresh_result.get('error')}, "
                "필터 없이 시작합니다"
            )

        self.enabled = True
        self._day_stopped = False
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._monitor_task = asyncio.create_task(self._position_monitor_loop())

        self._add_event("GYLEE_STARTED", "경윤 수정 매매법 시작")
        logger.info("경윤 수정 매매법 시작")
        return {"success": True, "message": "경윤 수정 매매법 시작"}

    async def stop(self) -> dict:
        """경윤 자동매매 중지."""
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
        self._add_event("GYLEE_STOPPED", "경윤 수정 매매법 중지")
        logger.info("경윤 수정 매매법 중지")
        return {"success": True, "message": "경윤 수정 매매법 중지"}

    async def _scan_loop(self):
        """3분 간격 스캔 루프 - 부모 로직 + 3개 필터."""
        from datetime import time

        while self.enabled:
            try:
                if self._day_stopped:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now()
                current_time = now.time()

                if current_time < self.MORNING_START or current_time > time(15, 20):
                    await asyncio.sleep(30)
                    continue

                self._last_scan_time = now
                self._add_event("SCAN", f"경윤 스캔 시작 ({now.strftime('%H:%M:%S')})")

                # 분석 실행
                result = await self.hongstyle_engine.run_analysis()

                if result.is_caution_day:
                    self._add_event("CAUTION", "매매 자제일 - 스킵")
                    await asyncio.sleep(180)
                    continue

                # ── 확신도 순위 계산 (부모와 동일) ──
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

                # ── 3개 필터 적용 ──
                buyable_pre = [r for r in ranking if r["is_buyable"]]
                self._filter_stats["total_candidates"] = len(buyable_pre)

                buyable = []
                cap_filtered = 0
                inst_filtered = 0
                pullback_filtered = 0

                for item in buyable_pre:
                    code = item["stock_code"]

                    # 필터 1: 시총 5000억+
                    if self.filter_provider.is_loaded:
                        if not self.filter_provider.passes_market_cap(code):
                            cap_filtered += 1
                            continue

                        # 필터 2: 기관 순매수 50~200억
                        if not self.filter_provider.passes_inst_filter(code):
                            inst_filtered += 1
                            continue

                    # 필터 3: 눌림매매일 때만 눌림 필터
                    if item["method"] == "눌림매매":
                        # 눌림 깊이와 거래량은 시그널에서 추정
                        # 기본적으로 눌림매매 자체를 매우 엄격히 필터링
                        # (백테스트: 53건→5건으로 줄여서 전체 수익 +12% 개선)
                        pullback_filtered += 1
                        continue

                    buyable.append(item)

                self._filter_stats["cap_filtered"] = cap_filtered
                self._filter_stats["inst_filtered"] = inst_filtered
                self._filter_stats["pullback_filtered"] = pullback_filtered
                self._filter_stats["passed"] = len(buyable)

                # 확신도순 정렬
                buyable.sort(key=lambda x: x["score"], reverse=True)

                # TOP N 선정
                top_codes = set()
                for i, item in enumerate(buyable[:self.TOP_N_ONLY]):
                    item["is_top"] = True
                    top_codes.add(item["stock_code"])

                # 전체 순위 재정렬
                ranking.sort(key=lambda x: x["score"], reverse=True)
                for i, item in enumerate(ranking):
                    item["rank"] = i + 1

                self._conviction_ranking = ranking
                self._top_codes = top_codes

                # ── TOP 5 중 진입 실행 ──
                gylee_pos_count = len(self._get_hong_positions_raw())
                for item in buyable:
                    if item["stock_code"] not in top_codes:
                        continue
                    if gylee_pos_count >= self.MAX_POSITIONS:
                        break
                    if self.engine.position_manager.has_position(item["stock_code"]):
                        continue

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
                    gylee_pos_count += 1

                await asyncio.sleep(180)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"경윤 스캔 루프 오류: {e}")
                self._add_event("ERROR", f"스캔 오류: {e}", severity="WARNING")
                await asyncio.sleep(60)

    async def _execute_buy(
        self, stock_code: str, stock_name: str, signal, ki_score: float
    ):
        """매수 실행 - 전략 이름을 "경윤_"으로 변경."""
        try:
            from src.broker.kis_models import OrderSide, OrderType

            price = await self.engine.data_manager.fetch_current_price(stock_code)
            if price <= 0:
                return

            qty = self._calculate_hong_position_size(
                price, signal.confidence, ki_score
            )
            if qty <= 0:
                return

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

            # 경윤 전략 이름
            strategy_name = f"{self.STRATEGY_PREFIX}{signal.method}"

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

                await self.engine._emit_position_update()
                await self.engine._emit_order(order)

                logger.info(
                    f"경윤 매수: {stock_name}({stock_code}) "
                    f"{qty}주 @{price:,.0f} [{signal.method}]"
                )

        except Exception as e:
            logger.error(f"경윤 매수 실행 실패 ({stock_code}): {e}")
            self._add_event("ERROR", f"매수 실패: {stock_name} - {e}", severity="WARNING")

    def _get_hong_positions_raw(self):
        """경윤 전략 포지션만 필터."""
        result = []
        for code, pos in self.engine.position_manager.positions.items():
            if pos.strategy_name.startswith(self.STRATEGY_PREFIX):
                result.append((code, pos))
        return result

    def get_status(self) -> dict:
        """현재 상태 (프론트엔드용)."""
        state = "IDLE"
        if self._day_stopped:
            state = "DAY_STOPPED"
        elif self.enabled:
            state = "SCANNING"
            if self._get_hong_positions_raw():
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
            "filter_loaded": self.filter_provider.is_loaded,
            "filter_date": self.filter_provider.data_date,
        }

    def get_filter_stats(self) -> dict:
        """필터 통계 반환 (대시보드용)."""
        provider_stats = self.filter_provider.get_filter_stats()
        return {
            **provider_stats,
            "scan_stats": self._filter_stats,
            "filters": [
                {
                    "name": "시가총액 5000억+",
                    "description": "소형주(잡주) 제거. WR 42%→52%",
                    "condition": "시가총액 >= 5,000억원",
                    "enabled": True,
                    "pass_count": provider_stats.get("market_cap_pass", 0),
                    "pass_rate": provider_stats.get("market_cap_rate", 0),
                },
                {
                    "name": "전일 기관 순매수 50~200억",
                    "description": "기관 수급 확인. WR 52%→57%",
                    "condition": "50억 <= 기관순매수 <= 200억",
                    "enabled": True,
                    "pass_count": provider_stats.get("inst_filter_pass", 0),
                    "pass_rate": provider_stats.get("inst_filter_rate", 0),
                },
                {
                    "name": "눌림 95%깊이 + 오전거래량",
                    "description": "나쁜 눌림 제거. 53건→5건",
                    "condition": "눌림깊이 >= 5% AND 오전거래량 >= 중간값",
                    "enabled": True,
                    "pass_count": 0,
                    "pass_rate": 0,
                },
            ],
        }

    def _add_event(
        self, event_type: str, message: str, severity: str = "INFO"
    ):
        """이벤트 추가 (경윤 prefix)."""
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

        self.engine.add_log(f"GYLEE_{event_type}", message, severity)
