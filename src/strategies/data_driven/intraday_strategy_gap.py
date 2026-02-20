"""Opening Gap Reversal Strategy - 오프닝 갭 반전 전략.

"강한 종목이 갭다운" = 매수 기회.

핵심 발견: Hong 신고가/전고점돌파(Hong Strong) 필터가 +14.9%p 승률 엣지.
  - Hong Strong O: 57.0% WR vs X: 42.1% WR

진입 조건:
  1. 전일종가 대비 갭다운 (gap_min ~ gap_max)
  2. 첫 봉(09:00) 양봉 (close > open)
  3. 첫 봉 거래량 1x+ (전일 봉당 평균 대비)
  4. bar_idx 1~2 (09:05~09:10)에 진입
  5. Hong 필터 (옵션): 시총 5000억+, 기관 50~200억
  6. Hong Strong 필터 (필수): 일봉자리 = 신고가 or 전고점돌파
  7. 뉴스 확신 점수 (옵션): 양호 이상

청산:
  - SL: -2.5%
  - TP: +5%
  - 시간 청산: 11:30까지 TP 미달 시 청산
"""

import numpy as np
from datetime import time

from src.strategies.intraday.base import IntradayStrategy, vwap_np
from src.strategies.data_driven.hong_filter_mixin import HongFilterMixin


class OpeningGapReversalStrategy(HongFilterMixin, IntradayStrategy):
    """오프닝 갭 반전 전략 - Hong Strong 기반."""

    HONG_MIN_KI_SCORE = 20
    HONG_MIN_CAP_BIL = 5000
    HONG_MIN_INST_BIL = 50
    HONG_MAX_INST_BIL = 200

    def __init__(
        self,
        gap_min=-0.05,
        gap_max=-0.003,  # -0.3% (뉴스 그리드 최적)
        vol_ratio_min=1.0,
        vol_ratio_max=0,  # 0 = 상한 없음
        max_entry_bar=2,
        stop_loss_pct=0.03,  # 3% (뉴스 그리드 최적)
        take_profit_pct=0.05,
        exit_hour=11,
        exit_minute=30,
        require_hong_strong=True,
        use_hong_filter=False,
        min_news_score=0,
    ):
        super().__init__(name="opening_gap_reversal")

        self.gap_min = gap_min
        self.gap_max = gap_max
        self.vol_ratio_min = vol_ratio_min
        self.vol_ratio_max = vol_ratio_max
        self.max_entry_bar = max_entry_bar
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.exit_time = time(exit_hour, exit_minute)
        self.require_hong_strong = require_hong_strong
        self.use_hong_filter = use_hong_filter
        self.min_news_score = min_news_score

        # 전일 데이터 (외부 주입)
        # 형식: {code: {date: {"close": float, "avg_vol": float}}}
        self._prev_day_data = {}
        # 뉴스 확신 점수 (외부 주입)
        # 형식: {code: {date: float}} (-1 ~ +1, 양수=긍정)
        self._news_scores = {}
        self._current_code = None
        self._current_date = None

    def set_prev_day_data(self, data: dict):
        """전일 종가/거래량 데이터 주입."""
        self._prev_day_data = data

    def set_news_scores(self, data: dict):
        """뉴스 확신 점수 주입. {code: {date: float}}."""
        self._news_scores = data

    def set_daily_context(self, code, trade_date, context=None):
        """V2 엔진 호출 - 현재 종목코드/날짜 저장."""
        super().set_daily_context(code, trade_date, context)
        self._current_code = code
        self._current_date = trade_date

    def precompute_day(self, day_df):
        """일봉 지표 사전 계산 - 갭/첫봉/거래량 분석."""
        ind = super().precompute_day(day_df)

        code = self._current_code
        date_key = self._current_date
        prev_data = None
        if code and date_key:
            prev_data = self._prev_day_data.get(code, {}).get(date_key)

        n = ind["n_bars"]

        # 전일 종가 기반 갭 계산
        if prev_data and prev_data["close"] > 0 and n > 0:
            prev_close = prev_data["close"]
            first_open = ind["open"][0]
            gap_pct = (first_open - prev_close) / prev_close
            prev_avg_vol = prev_data["avg_vol"]
        else:
            gap_pct = 0.0
            prev_close = 0.0
            prev_avg_vol = 0.0

        ind["gap_pct"] = gap_pct
        ind["prev_close"] = prev_close
        ind["prev_avg_vol"] = prev_avg_vol

        # 첫 봉 분석
        if n > 0:
            ind["first_bar_bullish"] = bool(ind["close"][0] > ind["open"][0])
            # 전일 평균 봉당 거래량 대비 (일거래량 / 78봉)
            avg_bar_vol = prev_avg_vol / 78.0 if prev_avg_vol > 0 else 0
            ind["first_bar_vol_ratio"] = (
                ind["volume"][0] / avg_bar_vol if avg_bar_vol > 0 else 0.0
            )
        else:
            ind["first_bar_bullish"] = False
            ind["first_bar_vol_ratio"] = 0.0

        # 시간 정보
        hours = np.array([
            ts.hour if hasattr(ts, 'hour') else 0
            for ts in ind["timestamps"]
        ])
        minutes = np.array([
            ts.minute if hasattr(ts, 'minute') else 0
            for ts in ind["timestamps"]
        ])
        ind["hours"] = hours
        ind["minutes"] = minutes

        # 누적 거래대금 (Hong intraday filter)
        ind["bar_trading_value"] = ind["close"] * ind["volume"]
        ind["cum_trading_value"] = np.cumsum(ind["bar_trading_value"])

        return ind

    def check_entry_fast(self, code, bar_idx, indicators):
        """빠른 진입 체크."""
        n = indicators["n_bars"]
        if bar_idx >= n:
            return None

        # bar 1~2에서만 진입 (09:05~09:10)
        if bar_idx < 1 or bar_idx > self.max_entry_bar:
            return None

        # 갭다운 필터
        gap_pct = indicators["gap_pct"]
        if gap_pct < self.gap_min or gap_pct > self.gap_max:
            return None

        # 첫 봉 양봉 확인
        if not indicators["first_bar_bullish"]:
            return None

        # 거래량 배수 확인
        vol_ratio = indicators["first_bar_vol_ratio"]
        if vol_ratio < self.vol_ratio_min:
            return None
        if self.vol_ratio_max > 0 and vol_ratio > self.vol_ratio_max:
            return None

        # Hong Strong 필터 (핵심: +14.9%p 승률 엣지)
        hong_reason = "no_ctx"
        ctx = self.get_daily_context()
        if self.require_hong_strong:
            if ctx is None:
                return None
            if ctx.daily_position_type not in ("신고가", "전고점돌파"):
                return None
            hong_reason = f"strong:{ctx.daily_position_type}"

        # 기본 Hong 필터 (옵션)
        if self.use_hong_filter:
            passes, hong_reason = self.passes_hong_filter()
            if not passes:
                return None
            if not self.passes_intraday_value_filter(bar_idx, indicators):
                return None

        # 뉴스 확신 점수 필터 (옵션)
        news_score = 0.0
        if self.min_news_score > 0 and self._news_scores:
            news_score = (
                self._news_scores
                .get(self._current_code, {})
                .get(self._current_date, 0.0)
            )
            if news_score < self.min_news_score:
                return None

        return {
            "reason": (
                f"gap={gap_pct:.2%}, vol={vol_ratio:.1f}x, "
                f"hong={hong_reason}"
                + (f", news={news_score:.2f}" if news_score else "")
            ),
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
            "confidence": 1.0 * self.hong_confidence_boost(),
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        """빠른 청산 체크 - 시간 청산."""
        if bar_idx >= indicators["n_bars"]:
            return None

        h = indicators["hours"][bar_idx]
        m = indicators["minutes"][bar_idx]
        exit_h = self.exit_time.hour
        exit_m = self.exit_time.minute

        if h > exit_h or (h == exit_h and m >= exit_m):
            return "시간청산"

        return None

    def check_entry(self, code, current_bar, historical):
        return None

    def check_exit(self, position, current_bar, historical):
        return None
