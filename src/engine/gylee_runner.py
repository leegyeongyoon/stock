"""경윤 v6.2 매매법 Runner - 시뮬레이션(simulate_combined_v2.py)과 완전 동일 로직.

HongStyleRunner를 상속하되, 스캔 로직은 시뮬레이션과 동일하게 독립 구현:
1. 유니버스: 거래대금 TOP100 OR 등락률 >= 3%
2. 필터: 시총 5000억+ AND 기관 50~200억
3. 오전 모멘텀(vol × pchg) TOP20 → TOP1 스킵 → TOP2~5 진입
4. 돌파매매: 5봉 고점돌파 + 거래량 1.2x (09:30~11:00)
5. 눌림매매: 95% 깊이 눌림 + 오전거래량 >= 중간값 (13:00~14:30)
6. 품질점수 100점: 시총15 + 기관15 + 등락률20 + 오전등락률20 + 종가강도20 + 리더순위10
7. 품질 60+, 70-79 스킵
"""

import asyncio
from datetime import datetime, time
from typing import Optional

import numpy as np
from loguru import logger

from src.config.settings import settings
from src.engine.hongstyle_runner import HongStyleRunner
from src.strategies.hongstyle.daily_filter_provider import (
    DailyFilterProvider,
    get_daily_filter_provider,
)


class GyleeRunner(HongStyleRunner):
    """경윤 v6.2 매매법 Runner - simulate_combined_v2.py와 동일."""

    STRATEGY_PREFIX = "경윤_"

    # v6.2 파라미터 (simulate_combined_v2.py 동일)
    V6_SKIP_TOP_N = 1           # TOP1 스킵
    V6_ENTER_TOP_N = 4          # TOP2~5 진입
    V6_MIN_DAILY_CHANGE = 6.0   # 등락률 6%+
    V6_MIN_QUALITY = 60         # 품질점수 60+
    V6_MIN_CONFIDENCE = 0.70    # 최소 확신도 (돌파=0.75만 통과, 눌림=0.60은 비활성)
    V6_MIN_CAP_BIL = 5000       # 시총 5000억+
    V6_MIN_INST = 50            # 기관순매수 50억+
    V6_MAX_INST = 200           # 기관순매수 200억 이하

    def __init__(self, engine):
        super().__init__(engine)
        self.filter_provider: DailyFilterProvider = get_daily_filter_provider()

        # v6.2 상태
        self._quality_scores: dict = {}       # {code: quality_score}
        self._v6_entries: list = []            # 당일 감지된 진입 시그널
        self._v6_entered_today: set = set()    # 당일 진입한 종목
        self._leader_ranking: list = []        # 오전 모멘텀 TOP20
        self._v6_universe: set = set()

        # 필터 통계 (대시보드용)
        self._filter_stats: dict = {
            "total_candidates": 0,
            "cap_inst_filtered": 0,
            "change_filtered": 0,
            "quality_filtered": 0,
            "passed": 0,
        }

    async def start(self) -> dict:
        """경윤 자동매매 시작 - 필터 데이터 로드 후 스캔 시작."""
        if self.enabled:
            return {"success": False, "message": "이미 실행 중"}

        # 필터 데이터 갱신 (실패해도 무조건 시작)
        try:
            refresh_result = await self.filter_provider.refresh()
            if not refresh_result.get("success"):
                logger.warning(
                    f"필터 데이터 로드 실패: {refresh_result.get('error')}, "
                    "필터 없이 시작합니다"
                )
        except Exception as e:
            logger.warning(f"필터 데이터 로드 중 예외 발생: {e}, 필터 없이 시작합니다")

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

    # ══════════════════════════════════════════════════════
    #  v6.2 유니버스/리더 선별 (시뮬레이션 동일)
    # ══════════════════════════════════════════════════════

    def _v6_select_universe(self) -> set[str]:
        """거래대금 TOP100 OR 등락률 >= 3%. 시뮬레이션 v6_select_universe()와 동일."""
        if not self.engine.data_manager:
            return set()

        all_bars = self.engine.data_manager.aggregator._completed_bars
        code_stats = {}

        for code, bars in all_bars.items():
            if not bars:
                continue
            total_value = sum(b.close * b.volume for b in bars)
            change = 0.0
            if bars[0].open > 0:
                change = (bars[-1].close / bars[0].open - 1) * 100
            code_stats[code] = {"value": total_value, "change_rate": change}

        if not code_stats:
            return set()

        # 거래대금 TOP100
        by_value = sorted(
            code_stats.items(), key=lambda x: x[1]["value"], reverse=True
        )
        top100 = {code for code, _ in by_value[:100]}

        # 등락률 >= 3%
        strong = {
            code
            for code, d in code_stats.items()
            if d["change_rate"] >= 3.0
        }

        return top100 | strong

    def _v6_filter_cap_inst(self, universe: set[str]) -> set[str]:
        """시총 5000억+ AND 기관 50~200억 필터."""
        if not self.filter_provider.is_loaded:
            return universe

        eligible = set()
        for code in universe:
            if not self.filter_provider.passes_market_cap(
                code, self.V6_MIN_CAP_BIL
            ):
                continue
            if not self.filter_provider.passes_inst_filter(
                code, self.V6_MIN_INST, self.V6_MAX_INST
            ):
                continue
            eligible.add(code)
        return eligible

    def _v6_select_leaders(
        self, eligible: set[str]
    ) -> tuple[list[dict], list[dict]]:
        """오전 모멘텀 TOP20 → TOP2~5 선별.

        시뮬레이션 v6_select_leaders()와 동일:
        - 09:00~09:30 바의 거래량 × 등락률 = 모멘텀
        - 모멘텀 TOP20 → TOP1 스킵 → TOP2~5
        """
        if not self.engine.data_manager:
            return [], []

        scores = []
        for code in eligible:
            bars = self.engine.data_manager.aggregator.get_bars(code)
            if not bars:
                continue

            # 09:00~09:30 bars
            morning = [
                b for b in bars
                if b.datetime.hour == 9 and b.datetime.minute < 30
            ]
            if len(morning) < 2:
                continue

            vol_sum = sum(b.volume for b in morning)
            pchg = 0.0
            if morning[0].open > 0:
                pchg = (morning[-1].close / morning[0].open - 1) * 100
            momentum = vol_sum * max(pchg, 0)

            scores.append({
                "code": code,
                "momentum": momentum,
                "pchg": pchg,
                "vol_sum": vol_sum,
            })

        scores.sort(key=lambda x: x["momentum"], reverse=True)
        top20 = scores[:20]

        # TOP1 스킵, TOP2~5
        leaders = top20[
            self.V6_SKIP_TOP_N : self.V6_SKIP_TOP_N + self.V6_ENTER_TOP_N
        ]
        return leaders, top20

    # ══════════════════════════════════════════════════════
    #  v6.2 진입 시그널 감지 (시뮬레이션 동일)
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _v6_find_breakout(bars) -> Optional[dict]:
        """5봉 고점 돌파 + 거래량 1.2x (09:30~11:00).

        시뮬레이션 v6_find_breakout()와 동일.
        """
        window = [
            b for b in bars
            if (b.datetime.hour == 9 and b.datetime.minute >= 30)
            or b.datetime.hour == 10
        ]
        if len(window) < 6:
            return None

        for i in range(5, len(window)):
            ph = max(b.high for b in window[i - 5 : i])
            bar = window[i]

            if bar.high > ph and bar.close > ph:
                avg_vol = sum(b.volume for b in window[i - 5 : i]) / 5
                if avg_vol > 0 and bar.volume >= avg_vol * 1.2:
                    return {
                        "price": bar.close,
                        "time": bar.datetime,
                        "confidence": 0.75,
                    }
        return None

    @staticmethod
    def _v6_find_pullback(bars, vol_median: float) -> Optional[dict]:
        """95% 깊이 눌림 + 오전거래량 >= 중간값 (13:00~14:30).

        시뮬레이션 v6_find_pullback()와 동일.
        """
        # 오전 거래량 체크
        morning_full = [b for b in bars if 9 <= b.datetime.hour < 12]
        if not morning_full:
            return None
        morning_vol = sum(b.volume for b in morning_full)
        if morning_vol < vol_median:
            return None

        # 오후 윈도우 (13:00~14:30)
        window = [
            b for b in bars
            if b.datetime.hour >= 13
            and b.datetime.hour < 15
            and not (b.datetime.hour == 14 and b.datetime.minute > 30)
        ]
        if len(window) < 5:
            return None

        # 오전 고/저
        morning = [b for b in bars if b.datetime.hour < 12]
        if not morning:
            return None

        mh = max(b.high for b in morning)
        ml = min(b.low for b in morning)
        r50 = mh - (mh - ml) * 0.5

        for i in range(2, len(window)):
            bar = window[i]
            prev = window[i - 1]
            if (
                prev.low <= mh * 0.95
                and bar.close > prev.close
                and bar.close > r50
                and bar.low > ml
            ):
                return {
                    "price": bar.close,
                    "time": bar.datetime,
                    "confidence": 0.6,
                }
        return None

    def _v6_morning_vol_median(self, leader_codes: list[str]) -> float:
        """리더 종목 오전 거래량 중간값.

        시뮬레이션 v6_morning_vol_median()와 동일.
        """
        if not self.engine.data_manager:
            return 0

        vols = []
        for code in leader_codes:
            bars = self.engine.data_manager.aggregator.get_bars(code)
            morning = [b for b in bars if 9 <= b.datetime.hour < 12]
            if morning:
                vols.append(sum(b.volume for b in morning))
        return float(np.median(vols)) if vols else 0

    # ══════════════════════════════════════════════════════
    #  v6.2 품질점수 (시뮬레이션 동일)
    # ══════════════════════════════════════════════════════

    def _calc_v6_quality_score(
        self, code: str, bars, leader_rank: int
    ) -> int:
        """v6.2 품질점수 계산 (100점 만점).

        시뮬레이션 v6_calc_quality_score()와 완전 동일:
        1. 시가총액 (15점)
        2. 기관순매수 (15점) - 전일 기준
        3. 당일 등락률 (20점)
        4. 오전 등락률 (20점)
        5. 종가 강도 (20점)
        6. 리더 순위 (10점) - 순위별 차등
        """
        score = 0

        # 1. 시가총액 (15점)
        cap_bil = 0
        stock_info = None
        if self.filter_provider.is_loaded:
            stock_info = self.filter_provider.get_stock_info(code)
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
        daily_change = 0.0
        if bars and bars[0].open > 0:
            daily_change = (bars[-1].close / bars[0].open - 1) * 100
        if daily_change >= 15:
            score += 20
        elif daily_change >= 10:
            score += 15
        elif daily_change >= 6:
            score += 10

        # 4. 오전 등락률 (20점)
        morning = [b for b in bars if 9 <= b.datetime.hour < 12]
        morning_change = 0.0
        if morning and morning[0].open > 0:
            morning_change = (
                morning[-1].close / morning[0].open - 1
            ) * 100
        if morning_change >= 15:
            score += 20
        elif morning_change >= 10:
            score += 15
        elif morning_change >= 5:
            score += 10

        # 5. 종가 강도 (20점)
        cs = 50.0
        if bars:
            dh = max(b.high for b in bars)
            dl = min(b.low for b in bars)
            cc = bars[-1].close
            if dh > dl:
                cs = (cc - dl) / (dh - dl) * 100
        if cs >= 90:
            score += 20
        elif cs >= 75:
            score += 15
        elif cs >= 60:
            score += 10

        # 6. 리더 순위 (10점) - 순위별 차등 (시뮬레이션 동일)
        if leader_rank == 2:
            score += 10
        elif leader_rank == 3:
            score += 7
        elif leader_rank == 4:
            score += 5
        elif leader_rank == 5:
            score += 3

        return score

    # ══════════════════════════════════════════════════════
    #  스캔 루프 (시뮬레이션 동일 로직)
    # ══════════════════════════════════════════════════════

    async def _scan_loop(self):
        """3분 간격 v6.2 스캔 루프 - 시뮬레이션과 동일 로직.

        1. HongStyleEngine → 매매자제일 체크 + 대시보드용 데이터
        2. 유니버스 선별 (거래대금 TOP100 OR 등락률 3%+)
        3. 시총/기관 필터
        4. 오전 모멘텀 TOP20 → TOP1 스킵 → TOP2~5
        5. 돌파매매/눌림매매 시그널 감지
        6. 품질점수 필터 (60+, 70-79 스킵)
        7. 진입 실행
        """
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
                self._add_event(
                    "SCAN",
                    f"경윤 v6.2 스캔 ({now.strftime('%H:%M:%S')})",
                )

                # ── HongStyleEngine: 대시보드 데이터 (자제일 체크 무시) ──
                # 경윤 v6.2는 자체 유니버스/리더 선별 로직으로 독립 판단.
                # HongStyleEngine 자제일(섹터 분산) 기준이 너무 보수적이라
                # 거의 매일 차단되므로 경윤에서는 무시.
                result = await self.hongstyle_engine.run_analysis()

                if result.is_caution_day:
                    self._add_event("CAUTION_SKIP", "자제일 판정이나 경윤 v6.2 독립 진행")

                # 연속손실 차단 확인
                if self.engine.risk_manager.is_entry_paused():
                    self._add_event("RISK_PAUSE", "연속손실 차단 - 진입 중단")
                    await asyncio.sleep(180)
                    continue

                # ── v6.2 독립 스캔 (시뮬레이션 동일) ──

                # 1. 유니버스: 거래대금 TOP100 OR 등락률 >= 3%
                universe = self._v6_select_universe()
                self._v6_universe = universe
                self._filter_stats["total_candidates"] = len(universe)

                if not universe:
                    self._add_event("SCAN", "유니버스 0종목 - 스킵")
                    await asyncio.sleep(180)
                    continue

                # 2. 필터: 시총 5000억+ AND 기관 50~200억
                eligible = self._v6_filter_cap_inst(universe)
                self._filter_stats["cap_inst_filtered"] = (
                    len(universe) - len(eligible)
                )

                # 3. 오전 모멘텀 TOP20 → TOP2~5
                leaders, top20 = self._v6_select_leaders(eligible)
                leader_codes = [s["code"] for s in leaders]
                self._leader_ranking = top20
                vol_median = self._v6_morning_vol_median(leader_codes)

                if leaders:
                    top1_code = top20[0]["code"] if top20 else "?"
                    top1_name = (
                        self.engine.data_manager.get_stock_name(top1_code)
                        if self.engine.data_manager
                        else top1_code
                    )
                    self._add_event(
                        "LEADERS",
                        f"TOP20 선정 완료. TOP1(스킵): {top1_name}, "
                        f"리더 {len(leaders)}종목, vol_median={vol_median:,.0f}",
                    )

                # 4. 리더별 돌파/눌림 시그널 탐색
                v6_entries = []
                change_filtered = 0
                quality_filtered = 0

                for rank_idx, s in enumerate(leaders):
                    code = s["code"]
                    actual_rank = self.V6_SKIP_TOP_N + rank_idx + 1

                    bars = self.engine.data_manager.aggregator.get_bars(code)
                    if not bars:
                        continue

                    # 등락률 필터
                    daily_change = 0.0
                    if bars[0].open > 0:
                        daily_change = (
                            bars[-1].close / bars[0].open - 1
                        ) * 100
                    if daily_change < self.V6_MIN_DAILY_CHANGE:
                        change_filtered += 1
                        continue

                    # 돌파매매 (09:30~11:00)
                    breakout = self._v6_find_breakout(bars)
                    breakout_entry = False
                    if breakout:
                        qs = self._calc_v6_quality_score(
                            code, bars, actual_rank
                        )
                        if qs >= self.V6_MIN_QUALITY and not (
                            70 <= qs < 80
                        ):
                            v6_entries.append({
                                "code": code,
                                "time": breakout["time"],
                                "price": breakout["price"],
                                "confidence": breakout["confidence"],
                                "quality": qs,
                                "method": "돌파매매",
                                "rank": actual_rank,
                            })
                            breakout_entry = True
                        else:
                            quality_filtered += 1

                    # 눌림매매 (13:00~14:30) - 돌파 엔트리 없을 때만
                    if not breakout_entry:
                        pullback = self._v6_find_pullback(bars, vol_median)
                        if pullback:
                            qs = self._calc_v6_quality_score(
                                code, bars, actual_rank
                            )
                            if qs >= self.V6_MIN_QUALITY and not (
                                70 <= qs < 80
                            ):
                                v6_entries.append({
                                    "code": code,
                                    "time": pullback["time"],
                                    "price": pullback["price"],
                                    "confidence": pullback["confidence"],
                                    "quality": qs,
                                    "method": "눌림매매",
                                    "rank": actual_rank,
                                })
                            else:
                                quality_filtered += 1

                self._filter_stats["change_filtered"] = change_filtered
                self._filter_stats["quality_filtered"] = quality_filtered
                self._filter_stats["passed"] = len(v6_entries)
                self._v6_entries = v6_entries

                # 5. 진입 실행 (품질순, 시간순)
                v6_entries.sort(key=lambda x: (-x["quality"], x["time"]))

                # 공유 포지션 한도: 전략 전체 (기존보유 제외)
                total_strategy_pos = sum(
                    1
                    for pos in self.engine.position_manager.positions.values()
                    if pos.strategy_name != "기존보유"
                )
                for e in v6_entries:
                    if total_strategy_pos >= settings.max_positions:
                        break
                    if e["code"] in self._v6_entered_today:
                        continue
                    if self.engine.position_manager.has_position(e["code"]):
                        continue
                    # 종목 쿨다운 체크 (SL 후 재진입 차단)
                    if self.engine.risk_manager.is_stock_cooled_down(e["code"]):
                        continue
                    if e["confidence"] < self.V6_MIN_CONFIDENCE:
                        continue

                    stock_name = (
                        self.engine.data_manager.get_stock_name(e["code"])
                        if self.engine.data_manager
                        else e["code"]
                    ) or e["code"]

                    self._quality_scores[e["code"]] = e["quality"]

                    self._add_event(
                        "V6_ENTRY",
                        f"v6.2 진입: {stock_name} [{e['method']}] "
                        f"품질={e['quality']}점 TOP{e['rank']} "
                        f"@{e['price']:,}",
                    )

                    await self._execute_v6_buy(
                        stock_code=e["code"],
                        stock_name=stock_name,
                        method=e["method"],
                        confidence=e["confidence"],
                        quality=e["quality"],
                    )
                    self._v6_entered_today.add(e["code"])
                    total_strategy_pos += 1

                # 대시보드용 순위 구성
                self._build_display_ranking(result, top20, v6_entries)

                await asyncio.sleep(180)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"경윤 v6.2 스캔 루프 오류: {e}")
                self._add_event(
                    "ERROR", f"스캔 오류: {e}", severity="WARNING"
                )
                await asyncio.sleep(60)

    # ══════════════════════════════════════════════════════
    #  매수 실행
    # ══════════════════════════════════════════════════════

    async def _execute_v6_buy(
        self,
        stock_code: str,
        stock_name: str,
        method: str,
        confidence: float,
        quality: int,
    ):
        """v6.2 매수 실행 - 시뮬레이션과 동일한 포지션 사이징.

        confidence >= 0.7 → HIGH_CONFIDENCE_PCT (40%)
        confidence < 0.7  → LOW_CONFIDENCE_PCT (20%)
        (ki_score 무관 - 시뮬레이션과 동일)
        """
        try:
            from src.broker.kis_models import OrderSide, OrderType

            price = await self.engine.data_manager.fetch_current_price(
                stock_code
            )
            if price <= 0:
                self._add_event(
                    "BUY_FAIL",
                    f"매수 실패: {stock_name} - 현재가 조회 실패 (price=0)",
                    severity="WARNING",
                )
                return

            # 포지션 사이징 (confidence만 사용 - 시뮬레이션 동일)
            total_equity = self.engine.position_manager.total_equity
            if total_equity <= 0:
                self._add_event(
                    "BUY_FAIL",
                    f"매수 실패: {stock_name} - equity=0",
                    severity="WARNING",
                )
                return

            if confidence >= self.V6_MIN_CONFIDENCE:
                alloc_pct = self.HIGH_CONFIDENCE_PCT
            else:
                alloc_pct = self.LOW_CONFIDENCE_PCT

            max_amount = total_equity * alloc_pct
            qty = int(max_amount / price)
            if qty <= 0:
                self._add_event(
                    "BUY_FAIL",
                    f"매수 실패: {stock_name} - 수량 0 "
                    f"(equity={total_equity:,.0f}, price={price:,})",
                    severity="WARNING",
                )
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

            strategy_name = f"{self.STRATEGY_PREFIX}{method}"

            order = await self.engine.order_manager.submit_order(
                stock_code=stock_code,
                side=OrderSide.BUY,
                quantity=qty,
                order_type=OrderType.MARKET,
                strategy_name=strategy_name,
            )

            from src.broker.kis_models import OrderStatus

            if order.status != OrderStatus.SUBMITTED:
                self._add_event(
                    "ORDER_FAIL",
                    f"주문 거부: {stock_name} {qty}주 @{price:,} "
                    f"status={order.status.value}",
                    severity="WARNING",
                )
                return

            if order.status == OrderStatus.SUBMITTED:
                self.engine.position_manager.open_position(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    strategy_name=strategy_name,
                    quantity=qty,
                    price=price,
                    stop_loss_pct=self.STOP_LOSS_PCT,
                    take_profit_pct=self.TAKE_PROFIT_PCT,
                    order_id=order.order_id,
                )

                # 리스크매니저 진입 기록
                self.engine.risk_manager.record_entry(stock_code)

                if self.engine.data_manager:
                    self.engine.data_manager.add_priority_codes({stock_code})

                trade_info = {
                    "type": "buy",
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "strategy_name": strategy_name,
                    "quantity": qty,
                    "price": price,
                    "confidence": confidence,
                    "quality_score": quality,
                    "method": method,
                    "time": datetime.now().isoformat(),
                }
                self._trades_today.append(trade_info)

                self._add_event(
                    "BUY",
                    f"매수: {stock_name} {qty}주 @{price:,.0f} "
                    f"[{method}] 품질={quality}점",
                )

                await self.engine._emit_position_update()
                await self.engine._emit_order(order)

                logger.info(
                    f"경윤 v6.2 매수: {stock_name}({stock_code}) "
                    f"{qty}주 @{price:,.0f} [{method}] 품질={quality}"
                )

        except Exception as e:
            logger.error(f"경윤 매수 실행 실패 ({stock_code}): {e}")
            self._add_event(
                "ERROR",
                f"매수 실패: {stock_name} - {e}",
                severity="WARNING",
            )

    # ══════════════════════════════════════════════════════
    #  포지션 필터 (부모 오버라이드)
    # ══════════════════════════════════════════════════════

    def _get_hong_positions_raw(self):
        """경윤 전략 포지션만 필터."""
        result = []
        for code, pos in self.engine.position_manager.positions.items():
            if pos.strategy_name.startswith(self.STRATEGY_PREFIX):
                result.append((code, pos))
        return result

    # ══════════════════════════════════════════════════════
    #  대시보드 / 상태 조회
    # ══════════════════════════════════════════════════════

    def _build_display_ranking(self, analysis_result, top20, v6_entries):
        """대시보드용 확신도 순위 구성.

        HongStyleEngine 분석 결과 + v6.2 모멘텀 순위를 병합.
        """
        ranking = []

        # v6.2 모멘텀 TOP20 기반 순위
        v6_entry_codes = {e["code"] for e in v6_entries}

        for i, s in enumerate(top20):
            code = s["code"]
            name = (
                self.engine.data_manager.get_stock_name(code)
                if self.engine.data_manager
                else code
            ) or code

            # v6 엔트리 정보
            entry = next(
                (e for e in v6_entries if e["code"] == code), None
            )
            quality = entry["quality"] if entry else 0
            method = entry["method"] if entry else "-"

            is_top = code in v6_entry_codes
            actual_rank = i + 1

            ranking.append({
                "rank": actual_rank,
                "stock_code": code,
                "stock_name": name,
                "score": s["momentum"],
                "confidence": entry["confidence"] if entry else 0,
                "ki_score": 0,
                "is_leader": actual_rank <= 5,
                "leader_bonus": 1.0,
                "daily_position": "-",
                "position_desc": "-",
                "method": method,
                "action": "buy" if is_top else "skip",
                "reason": (
                    f"TOP{actual_rank} 모멘텀={s['momentum']:.0f}"
                ),
                "alloc_pct": (
                    self.HIGH_CONFIDENCE_PCT
                    if entry and entry["confidence"] >= 0.7
                    else self.LOW_CONFIDENCE_PCT
                ),
                "alloc_label": (
                    "확신"
                    if entry and entry["confidence"] >= 0.7
                    else "보통"
                ),
                "is_buyable": is_top,
                "is_top": is_top,
                "quality_score": quality,
                "patterns": [],
                "momentum": s["momentum"],
                "pchg": s["pchg"],
            })

        self._conviction_ranking = ranking

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
                t.get("pnl", 0)
                for t in self._trades_today
                if "pnl" in t
            ),
            "last_scan_time": (
                self._last_scan_time.isoformat()
                if self._last_scan_time
                else None
            ),
            "max_positions": self.MAX_POSITIONS,
            "top_n": (
                f"TOP{self.V6_SKIP_TOP_N + 1}"
                f"~{self.V6_SKIP_TOP_N + self.V6_ENTER_TOP_N}"
            ),
            "high_alloc": self.HIGH_CONFIDENCE_PCT,
            "low_alloc": self.LOW_CONFIDENCE_PCT,
            "filter_loaded": self.filter_provider.is_loaded,
            "filter_date": self.filter_provider.data_date,
            "v6_version": "6.2",
            "universe_size": len(self._v6_universe),
            "leader_count": len(self._leader_ranking),
        }

    def get_filter_stats(self) -> dict:
        """필터 통계 반환 (대시보드용)."""
        provider_stats = self.filter_provider.get_filter_stats()
        return {
            **provider_stats,
            "scan_stats": self._filter_stats,
            "filters": [
                {
                    "name": "거래대금 TOP100 OR 등락률 3%+",
                    "description": "시뮬레이션 동일 유니버스",
                    "condition": "거래대금 TOP100 또는 등락률 >= 3%",
                    "enabled": True,
                },
                {
                    "name": "시총 5000억+ & 기관 50~200억",
                    "description": "시총/기관 필터",
                    "condition": (
                        f"시총 >= {self.V6_MIN_CAP_BIL}억 AND "
                        f"{self.V6_MIN_INST}억 <= 기관 <= {self.V6_MAX_INST}억"
                    ),
                    "enabled": True,
                    "pass_count": provider_stats.get("both_pass", 0),
                    "pass_rate": provider_stats.get("both_rate", 0),
                },
                {
                    "name": "오전 모멘텀 TOP20 → TOP2~5",
                    "description": "09:00~09:30 vol×pchg 모멘텀 순위",
                    "condition": "TOP1 스킵, TOP2~5 진입",
                    "enabled": True,
                },
                {
                    "name": f"당일 등락률 {self.V6_MIN_DAILY_CHANGE}%+",
                    "description": "강한 종목만 진입",
                    "condition": (
                        f"당일 등락률 >= {self.V6_MIN_DAILY_CHANGE}%"
                    ),
                    "enabled": True,
                },
                {
                    "name": "돌파매매 / 눌림매매",
                    "description": "시뮬레이션 동일 시그널",
                    "condition": (
                        "돌파: 5봉고점돌파+vol1.2x (09:30~11:00) | "
                        "눌림: 95%깊이+vol중간값 (13:00~14:30)"
                    ),
                    "enabled": True,
                },
                {
                    "name": f"품질점수 {self.V6_MIN_QUALITY}+, 70-79 스킵",
                    "description": "v6.2 품질점수 시스템",
                    "condition": f"품질 >= {self.V6_MIN_QUALITY} AND NOT(70~79)",
                    "enabled": True,
                },
            ],
            "entry_conditions": {
                "version": "v6.2 (시뮬레이션 동일)",
                "universe": "거래대금 TOP100 OR 등락률 3%+",
                "leader_selection": "오전 모멘텀(vol×pchg) TOP20",
                "skip_top_n": self.V6_SKIP_TOP_N,
                "enter_top_n": self.V6_ENTER_TOP_N,
                "min_daily_change": f"{self.V6_MIN_DAILY_CHANGE}%+",
                "breakout": "5봉고점돌파 + vol 1.2x (09:30~11:00)",
                "pullback": "95%깊이 + oam_vol>=median (13:00~14:30)",
                "min_quality": self.V6_MIN_QUALITY,
                "skip_quality_range": "70~79",
                "min_confidence": self.V6_MIN_CONFIDENCE,
                "max_positions": self.MAX_POSITIONS,
            },
            "risk_rules": {
                "stop_loss": f"-{self.STOP_LOSS_PCT * 100:.0f}%",
                "take_profit": (
                    f"+{self.TAKE_PROFIT_PCT * 100:.0f}% (70% 분매)"
                ),
                "breakeven_cut": "분매 후 원가 복귀 → 잔여 전량",
                "consecutive_stop": (
                    f"{self.MAX_CONSECUTIVE_LOSSES}연속 손절 → 당일종료"
                ),
                "position_sizing": (
                    f"돌파(conf=0.75) {self.HIGH_CONFIDENCE_PCT:.0%} / "
                    f"눌림(conf=0.60) {self.LOW_CONFIDENCE_PCT:.0%}"
                ),
            },
        }

    def reset_daily(self):
        """일일 리셋 (부모 + v6.2 상태)."""
        super().reset_daily()
        self._quality_scores.clear()
        self._v6_entries.clear()
        self._v6_entered_today.clear()
        self._leader_ranking.clear()
        self._v6_universe.clear()
        self._filter_stats = {
            "total_candidates": 0,
            "cap_inst_filtered": 0,
            "change_filtered": 0,
            "quality_filtered": 0,
            "passed": 0,
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
            loop = asyncio.get_running_loop()
            from src.server.websocket_hub import hub
            loop.create_task(hub.broadcast_gylee(event))
        except RuntimeError:
            pass
        except Exception:
            pass

        self.engine.add_log(f"GYLEE_{event_type}", message, severity)
