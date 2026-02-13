"""경윤 v6.2 매매법 Runner.

HongStyleRunner를 상속하여 v6.2 품질점수 시스템 적용.
- 품질점수 60+, 70-79 스킵
- TOP2~5 진입 (TOP1 스킵)
- 등락률 6%+ 필터
- 오버나잇 홀딩 (점수 >= 60)
시뮬레이션(simulate_combined_v2.py)과 동일한 로직.
"""

import asyncio
from datetime import datetime, time, date, timedelta
from typing import Optional

import numpy as np
from loguru import logger

from src.engine.hongstyle_runner import HongStyleRunner
from src.strategies.hongstyle.daily_filter_provider import (
    DailyFilterProvider,
    get_daily_filter_provider,
)


class GyleeRunner(HongStyleRunner):
    """경윤 v6.2 매매법 Runner - 품질점수 + TOP2~5 + 등락률 필터."""

    STRATEGY_PREFIX = "경윤_"

    # v6.2 파라미터 (simulate_combined_v2.py 동일)
    V6_SKIP_TOP_N = 1           # TOP1 스킵
    V6_ENTER_TOP_N = 4          # TOP2~5 진입
    V6_MIN_DAILY_CHANGE = 6.0   # 등락률 6%+
    V6_MIN_QUALITY = 60         # 품질점수 60+
    V6_MIN_CONFIDENCE = 0.70    # 최소 확신도
    V6_MIN_CAP_BIL = 5000       # 시총 5000억+
    V6_MIN_INST = 50            # 기관순매수 50억+
    V6_MAX_INST = 200           # 기관순매수 200억 이하

    def __init__(self, engine):
        super().__init__(engine)
        self.filter_provider: DailyFilterProvider = get_daily_filter_provider()

        # v6.2 상태
        self._quality_scores: dict = {}  # {code: quality_score}
        self._leader_ranking: list = []  # 오전 모멘텀 TOP20
        self._v6_universe: set = set()

        # 필터 통계 (대시보드용)
        self._filter_stats: dict = {
            "total_candidates": 0,
            "cap_filtered": 0,
            "inst_filtered": 0,
            "change_filtered": 0,
            "quality_filtered": 0,
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

        self._add_event("GYLEE_STARTED", "경윤 v6.2 매매법 시작")
        logger.info("경윤 v6.2 매매법 시작")
        return {"success": True, "message": "경윤 v6.2 매매법 시작"}

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
        self._add_event("GYLEE_STOPPED", "경윤 v6.2 매매법 중지")
        logger.info("경윤 v6.2 매매법 중지")
        return {"success": True, "message": "경윤 v6.2 매매법 중지"}

    async def _scan_loop(self):
        """3분 간격 스캔 루프 - v6.2 품질점수 기반."""
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
                self._add_event("SCAN", f"경윤 v6.2 스캔 시작 ({now.strftime('%H:%M:%S')})")

                # 분석 실행
                result = await self.hongstyle_engine.run_analysis()

                if result.is_caution_day:
                    self._add_event("CAUTION", "매매 자제일 - 스킵")
                    await asyncio.sleep(180)
                    continue

                # ── v6.2 확신도 순위 + 품질점수 계산 ──
                ranking = []
                for sa in result.stock_analyses:
                    sig = sa.entry_signal
                    ki = sa.ki_score.score
                    score = self._calc_conviction_score(
                        sig.confidence, ki, sa.is_leader
                    )

                    # v6.2 품질점수 계산
                    quality = self._calc_v6_quality_score(sa)
                    self._quality_scores[sa.code] = quality

                    is_buyable = (
                        sig.action == "buy"
                        and sig.confidence >= self.V6_MIN_CONFIDENCE
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
                        "quality_score": quality,
                        "patterns": [p.pattern_name for p in sa.patterns],
                    })

                # ── v6.2 필터 적용 ──
                buyable_pre = [r for r in ranking if r["is_buyable"]]
                self._filter_stats["total_candidates"] = len(buyable_pre)

                buyable = []
                cap_filtered = 0
                inst_filtered = 0
                change_filtered = 0
                quality_filtered = 0

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

                    # 필터 3: 등락률 6%+ (v6.2 핵심)
                    daily_change = self._get_daily_change_rate(code)
                    if daily_change < self.V6_MIN_DAILY_CHANGE:
                        change_filtered += 1
                        continue

                    # 필터 4: 품질점수 60+, 70-79 스킵 (v6.2 핵심)
                    quality = item["quality_score"]
                    if quality < self.V6_MIN_QUALITY:
                        quality_filtered += 1
                        continue
                    if 70 <= quality <= 79:
                        quality_filtered += 1
                        continue

                    # 필터 5: 시간대 필터 (돌파=오전, 눌림=오후)
                    if item["method"] == "돌파매매":
                        if not (self.MORNING_START <= current_time <= self.MORNING_END):
                            continue
                    elif item["method"] == "눌림매매":
                        if not (self.AFTERNOON_START <= current_time <= self.AFTERNOON_END):
                            continue

                    buyable.append(item)

                self._filter_stats["cap_filtered"] = cap_filtered
                self._filter_stats["inst_filtered"] = inst_filtered
                self._filter_stats["change_filtered"] = change_filtered
                self._filter_stats["quality_filtered"] = quality_filtered
                self._filter_stats["passed"] = len(buyable)

                # 확신도순 정렬
                buyable.sort(key=lambda x: x["score"], reverse=True)

                # v6.2: TOP1 스킵, TOP2~5 선정
                top_codes = set()
                entered = 0
                skipped = 0
                for item in buyable:
                    if skipped < self.V6_SKIP_TOP_N:
                        skipped += 1
                        self._add_event(
                            "SKIP_TOP1",
                            f"TOP1 스킵: {item['stock_name']} "
                            f"(점수={item['score']:.3f}, 품질={item['quality_score']})",
                        )
                        continue
                    if entered >= self.V6_ENTER_TOP_N:
                        break
                    item["is_top"] = True
                    top_codes.add(item["stock_code"])
                    entered += 1

                # 전체 순위 재정렬
                ranking.sort(key=lambda x: x["score"], reverse=True)
                for i, item in enumerate(ranking):
                    item["rank"] = i + 1

                self._conviction_ranking = ranking
                self._top_codes = top_codes

                # ── TOP2~5 중 진입 실행 ──
                gylee_pos_count = len(self._get_hong_positions_raw())
                for item in buyable:
                    if item["stock_code"] not in top_codes:
                        continue
                    if gylee_pos_count >= self.MAX_POSITIONS:
                        break
                    if self.engine.position_manager.has_position(item["stock_code"]):
                        continue

                    self._add_event(
                        "V6_ENTRY",
                        f"v6.2 진입: {item['stock_name']} "
                        f"품질={item['quality_score']}점 "
                        f"[{item['method']}] 확신={item['confidence']:.0%}",
                    )

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
                logger.error(f"경윤 v6.2 스캔 루프 오류: {e}")
                self._add_event("ERROR", f"스캔 오류: {e}", severity="WARNING")
                await asyncio.sleep(60)

    def _calc_v6_quality_score(self, stock_analysis) -> int:
        """v6.2 품질점수 계산 (100점 만점).

        시뮬레이션 v6_calc_quality_score()와 동일한 로직:
        1. 시가총액 (15점)
        2. 기관순매수 (15점) - 전일 기준
        3. 당일 등락률 (20점)
        4. 오전 등락률 (20점)
        5. 종가 강도 (20점)
        6. 리더 순위 (10점)
        """
        score = 0
        sa = stock_analysis

        # 1. 시가총액 (15점) - filter_provider에서 가져옴
        cap_bil = 0
        stock_info = None
        if self.filter_provider.is_loaded:
            stock_info = self.filter_provider.get_stock_info(sa.code)
            if stock_info:
                cap_bil = stock_info.get("cap_bil", 0)
        if cap_bil >= 30000:
            score += 15
        elif cap_bil >= 10000:
            score += 10
        elif cap_bil >= 5000:
            score += 5

        # 2. 기관순매수 - 전일 (15점)
        inst = 0
        if stock_info:
            inst = stock_info.get("inst_bil", 0)
        if inst >= 150:
            score += 15
        elif inst >= 100:
            score += 10
        elif inst >= 50:
            score += 5

        # 3. 당일 등락률 (20점)
        daily_change = self._get_daily_change_rate(sa.code)
        if daily_change >= 15:
            score += 20
        elif daily_change >= 10:
            score += 15
        elif daily_change >= 6:
            score += 10

        # 4. 오전 등락률 (20점) - 5분봉에서 계산
        morning_change = self._get_morning_change(sa.code)
        if morning_change >= 15:
            score += 20
        elif morning_change >= 10:
            score += 15
        elif morning_change >= 5:
            score += 10

        # 5. 종가 강도 (20점) - 당일 고저 대비 현재가
        close_strength = self._get_close_strength(sa.code)
        if close_strength >= 90:
            score += 20
        elif close_strength >= 75:
            score += 15
        elif close_strength >= 60:
            score += 10

        # 6. 리더 순위 (10점) - 대장주 보너스
        if sa.is_leader:
            score += 10

        return score

    def _get_daily_change_rate(self, code: str) -> float:
        """당일 등락률 조회 (실시간 데이터)."""
        try:
            if not self.engine.data_manager:
                return 0
            bars = self.engine.data_manager.aggregator.get_bars(code)
            if not bars or len(bars) < 2:
                return 0
            open_price = bars[0].open
            current_price = bars[-1].close
            if open_price <= 0:
                return 0
            return (current_price / open_price - 1) * 100
        except Exception:
            return 0

    def _get_morning_change(self, code: str) -> float:
        """오전 등락률 (09:00~12:00)."""
        try:
            if not self.engine.data_manager:
                return 0
            bars = self.engine.data_manager.aggregator.get_bars(code)
            if not bars:
                return 0
            morning = [b for b in bars if b.timestamp.hour < 12]
            if len(morning) < 2:
                return 0
            open_price = morning[0].open
            close_price = morning[-1].close
            if open_price <= 0:
                return 0
            return (close_price / open_price - 1) * 100
        except Exception:
            return 0

    def _get_close_strength(self, code: str) -> float:
        """종가 강도: (현재가 - 저가) / (고가 - 저가) * 100."""
        try:
            if not self.engine.data_manager:
                return 50
            bars = self.engine.data_manager.aggregator.get_bars(code)
            if not bars:
                return 50
            high = max(b.high for b in bars)
            low = min(b.low for b in bars)
            current = bars[-1].close
            if high <= low:
                return 50
            return (current - low) / (high - low) * 100
        except Exception:
            return 50

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

                quality = self._quality_scores.get(stock_code, 0)
                trade_info = {
                    "type": "buy",
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "strategy_name": strategy_name,
                    "quantity": qty,
                    "price": price,
                    "confidence": signal.confidence,
                    "ki_score": ki_score,
                    "quality_score": quality,
                    "time": datetime.now().isoformat(),
                }
                self._trades_today.append(trade_info)

                self._add_event(
                    "BUY",
                    f"매수: {stock_name} {qty}주 @{price:,.0f} "
                    f"[{signal.method}] 확신도={signal.confidence:.0%} "
                    f"품질={quality}점",
                )

                await self.engine._emit_position_update()
                await self.engine._emit_order(order)

                logger.info(
                    f"경윤 v6.2 매수: {stock_name}({stock_code}) "
                    f"{qty}주 @{price:,.0f} [{signal.method}] 품질={quality}"
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
            "top_n": f"TOP{self.V6_SKIP_TOP_N+1}~{self.V6_SKIP_TOP_N+self.V6_ENTER_TOP_N}",
            "high_alloc": self.HIGH_CONFIDENCE_PCT,
            "low_alloc": self.LOW_CONFIDENCE_PCT,
            "filter_loaded": self.filter_provider.is_loaded,
            "filter_date": self.filter_provider.data_date,
            "v6_version": "6.2",
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
                    "description": "소형주 제거",
                    "condition": "시가총액 >= 5,000억원",
                    "enabled": True,
                    "pass_count": provider_stats.get("market_cap_pass", 0),
                    "pass_rate": provider_stats.get("market_cap_rate", 0),
                },
                {
                    "name": "전일 기관 순매수 50~200억",
                    "description": "기관 수급 확인",
                    "condition": "50억 <= 기관순매수 <= 200억",
                    "enabled": True,
                    "pass_count": provider_stats.get("inst_filter_pass", 0),
                    "pass_rate": provider_stats.get("inst_filter_rate", 0),
                },
                {
                    "name": "당일 등락률 6%+",
                    "description": "v6.2 강한 종목만 진입",
                    "condition": "당일 등락률 >= 6%",
                    "enabled": True,
                },
                {
                    "name": "품질점수 60+, 70-79 스킵",
                    "description": "v6.2 품질점수 시스템",
                    "condition": "품질 >= 60 AND NOT(70~79)",
                    "enabled": True,
                },
                {
                    "name": "TOP1 스킵, TOP2~5 진입",
                    "description": "v6.2 1등 회피, 2~5등 진입",
                    "condition": "확신도 순위 2~5위만",
                    "enabled": True,
                },
            ],
            "entry_conditions": {
                "version": "v6.2",
                "min_daily_change": f"{self.V6_MIN_DAILY_CHANGE}%+",
                "min_quality": self.V6_MIN_QUALITY,
                "skip_quality_range": "70~79",
                "skip_top_n": self.V6_SKIP_TOP_N,
                "enter_top_n": self.V6_ENTER_TOP_N,
                "min_confidence": self.V6_MIN_CONFIDENCE,
                "max_positions": self.MAX_POSITIONS,
            },
            "risk_rules": {
                "stop_loss": f"-{self.STOP_LOSS_PCT*100:.0f}%",
                "take_profit": f"+{self.TAKE_PROFIT_PCT*100:.0f}% (70% 분매)",
                "breakeven_cut": "분매 후 원가 복귀 → 잔여 전량",
                "consecutive_stop": f"{self.MAX_CONSECUTIVE_LOSSES}연속 손절 → 당일종료",
                "position_sizing": f"확신 {self.HIGH_CONFIDENCE_PCT:.0%} / 보통 {self.LOW_CONFIDENCE_PCT:.0%}",
            },
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
