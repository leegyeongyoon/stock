"""공격/균형 인트라데이 전략 공통 베이스.

테마/상한가 데이터 주입(injector)과 돌파/거래량비/시간 지표 사전계산을 공유한다.
모든 전략은 IntradayStrategy ABC를 따르며 V2 백테스트와 라이브 러너에서 동일 코드로 돈다.

주입 데이터 형식:
  theme_data:   {code: {date: {"in_hot_theme": bool, "is_leader": bool,
                                "theme_rank": int|None, "theme_name": str|None}}}
  limitup_data: {code: {date: {"limit_price": int, "first_hit_time": datetime.time|None}}}

데이터가 없으면 해당 필터는 fail-closed(진입 안 함)로 동작한다.
"""

from typing import Optional

import numpy as np

from src.strategies.intraday.base import IntradayStrategy, rolling_mean_np


class AggressiveIntradayBase(IntradayStrategy):
    """테마/상한가 주입 + 돌파/거래량비/시간 사전계산을 제공하는 베이스."""

    def __init__(
        self,
        name: str,
        breakout_lookback: int = 5,
        bar_minutes: int = 1,
        vol_avg_window: int = 20,
    ):
        super().__init__(name=name)
        self.breakout_lookback = breakout_lookback
        self.bar_minutes = bar_minutes  # 분봉 간격(1=1분봉, 5=5분봉) — 시간스톱 계산용
        # 거래량 급증 판정 기준 윈도우(봉 수). 이 윈도우가 차야 vol_ratio가 생긴다.
        self.vol_avg_window = vol_avg_window
        self._theme_data: dict = {}
        self._limitup_data: dict = {}
        self._orderflow: dict = {}  # {code: {"exec_strength": float, "bid_ask_ratio": float}}
        self._current_code: Optional[str] = None
        self._current_date = None

    # --- 외부 주입 ---

    def set_theme_data(self, data: dict) -> None:
        """{code: {date: theme_info}} 주입."""
        self._theme_data = data or {}

    def set_limitup_data(self, data: dict) -> None:
        """{code: {date: limit_info}} 주입."""
        self._limitup_data = data or {}

    def set_orderflow(self, data: dict) -> None:
        """현재 호가/체결강도 주입. {code: {"exec_strength": float, "bid_ask_ratio": float}}.

        라이브 러너가 KISClient.get_orderflow() 결과를 매 스캔마다 갱신해 넣는다.
        """
        self._orderflow = data or {}

    def orderflow_ok(self, *, min_strength: float = 100.0, min_bid_ratio: float = 1.0) -> bool:
        """현재 종목의 체결강도/잔량비가 매수 우위인지(데이터 없으면 True=통과).

        OHLC 봉엔 없는 신호. 데이터가 주입됐을 때만 게이트로 작동(fail-open).
        """
        of = self._orderflow.get(self._current_code)
        if not of:
            return True
        strength = of.get("exec_strength")
        ratio = of.get("bid_ask_ratio")
        if strength is not None and strength < min_strength:
            return False
        if ratio is not None and ratio < min_bid_ratio:
            return False
        return True

    def set_daily_context(self, code, trade_date, context=None):
        super().set_daily_context(code, trade_date, context)
        self._current_code = code
        self._current_date = trade_date

    # --- 주입 데이터 조회 ---

    def _theme_info(self) -> Optional[dict]:
        return self._theme_data.get(self._current_code, {}).get(self._current_date)

    def _limit_info(self) -> Optional[dict]:
        return self._limitup_data.get(self._current_code, {}).get(self._current_date)

    def in_hot_theme(self) -> bool:
        info = self._theme_info()
        return bool(info and info.get("in_hot_theme"))

    # --- 시간 ---

    def elapsed_minutes(self, position, idx: int) -> int:
        """진입 봉 대비 경과 분(분봉 간격 반영)."""
        return max(0, idx - position.entry_bar_idx) * self.bar_minutes

    # --- 사전계산 ---

    def precompute_day(self, day_df) -> dict:
        ind = super().precompute_day(day_df)
        n = ind["n_bars"]
        highs = ind["high"]
        vols = ind["volume"]

        # 직전 N봉 고가(현재 봉 제외) → 돌파 기준
        prior_high = np.full(n, np.nan)
        N = self.breakout_lookback
        for i in range(1, n):
            lo = max(0, i - N)
            prior_high[i] = highs[lo:i].max()
        ind["prior_high"] = prior_high

        # 봉별 거래량비 = 거래량 / (직전 window봉 평균). 급증 판정은 '현재 봉을 제외한'
        # 직전 베이스라인과 비교해야 한다(현재 봉을 포함하면 급증이 베이스라인을 끌어올려 희석됨).
        rmean = rolling_mean_np(vols, self.vol_avg_window)
        vbase = np.full(n, np.nan)
        vbase[1:] = rmean[:-1]  # 한 봉 시프트 → 현재 봉 제외
        vr = np.full(n, np.nan)
        mask = (~np.isnan(vbase)) & (vbase > 0)
        vr[mask] = vols[mask] / vbase[mask]
        ind["vol_ratio"] = vr

        # 시각
        ind["hours"] = np.array([getattr(ts, "hour", 0) for ts in ind["timestamps"]])
        ind["minutes"] = np.array([getattr(ts, "minute", 0) for ts in ind["timestamps"]])

        return ind

    # ABC 충족 (slow-path 미사용)
    def check_entry(self, code, current_bar, historical):
        return None

    def check_exit(self, position, current_bar, historical):
        return None
