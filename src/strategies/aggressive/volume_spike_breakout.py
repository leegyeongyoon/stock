"""균형 티어 — 거래량 급증 돌파 스캘프 (2~3% 목표).

진입: 거래량 급증(20봉 평균 대비) + 직전 N봉 고가 돌파 + VWAP 상방 + 테마 확인.
청산: +2% 부분익절(절반) → 손익분기 잠금, 30분 내 진척 없으면 시간 청산. 하드 손절은 엔진 SL.
"""

import numpy as np

from src.strategies.aggressive.base import AggressiveIntradayBase


class VolumeSpikeBreakoutStrategy(AggressiveIntradayBase):
    """거래량 급증 돌파 스캘프 (균형 티어)."""

    def __init__(
        self,
        name: str = "vol_spike_scalp",
        vol_mult: float = 2.0,
        breakout_lookback: int = 5,
        stop_loss_pct: float = 0.015,
        take_profit_pct: float = 0.04,   # 엔진 하드TP는 천장 역할; 실제 익절은 partial_tp 우선
        partial_tp: float = 0.02,
        breakeven_lock: float = 0.005,
        time_stop_min: int = 30,
        min_progress: float = 0.01,
        require_theme: bool = True,
        bar_minutes: int = 1,
        min_bar_idx: int = 5,
        vol_avg_window: int = 20,
        max_entry_hour: int = 0,  # 0=제한없음. 예: 11이면 11시 이후 진입 금지(초반 상승만)
    ):
        super().__init__(
            name=name, breakout_lookback=breakout_lookback,
            bar_minutes=bar_minutes, vol_avg_window=vol_avg_window,
        )
        self.vol_mult = vol_mult
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.partial_tp = partial_tp
        self.breakeven_lock = breakeven_lock
        self.time_stop_min = time_stop_min
        self.min_progress = min_progress
        self.require_theme = require_theme
        self.min_bar_idx = min_bar_idx
        self.max_entry_hour = max_entry_hour

    def check_entry_fast(self, code, idx, ind):
        n = ind["n_bars"]
        if idx < self.min_bar_idx or idx >= n:
            return None

        # 초반 상승만 노릴 때: max_entry_hour 이후 진입 금지
        if self.max_entry_hour and ind["hours"][idx] >= self.max_entry_hour:
            return None

        vr = ind["vol_ratio"][idx]
        if np.isnan(vr) or vr < self.vol_mult:
            return None

        close = ind["close"][idx]
        prior_high = ind["prior_high"][idx]
        if np.isnan(prior_high) or close <= prior_high:  # 돌파 아님
            return None
        if close <= ind["vwap"][idx]:  # VWAP 하방
            return None

        # 테마 확인 (데이터 없으면 fail-closed)
        theme_conf = 1.0
        if self.require_theme:
            info = self._theme_info()
            if not info or not info.get("in_hot_theme"):
                return None
            if info.get("is_leader"):
                theme_conf = 1.3

        confidence = min(2.0, vr / self.vol_mult) * theme_conf
        return {
            "reason": f"vol{vr:.1f}x 돌파",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
            "confidence": confidence,
        }

    def check_exit_fast(self, position, idx, ind):
        n = ind["n_bars"]
        if idx >= n:
            return None

        price = ind["close"][idx]
        gain = price / position.entry_price - 1.0
        elapsed = self.elapsed_minutes(position, idx)

        # +2% 부분익절(절반)
        if not position.partial_done and gain >= self.partial_tp:
            return {"action": "partial", "fraction": 0.5, "reason": f"TP1 +{self.partial_tp:.0%}"}

        # 부분익절 후 손익분기 아래로 빠지면 잔량 청산
        if position.partial_done and gain <= self.breakeven_lock:
            return {"action": "close", "reason": "잠금청산"}

        # 시간 청산: 진척 없으면 정리
        if elapsed >= self.time_stop_min and gain < self.min_progress:
            return {"action": "close", "reason": "시간청산"}

        return None
