"""공격 티어 — 모멘텀 급등 연속성 (상한가 의존 없음).

진입: 연속 상승봉 + 거래량 급증 + 직전 N봉 고가 돌파 + VWAP 상방.
청산: 트레일링 스톱으로 연속 상승을 태운다. 하드 손절/EOD는 엔진.
"""

import numpy as np

from src.strategies.aggressive.base import AggressiveIntradayBase


class MomentumSurgeStrategy(AggressiveIntradayBase):
    """모멘텀 급등 연속성 (공격 티어)."""

    def __init__(
        self,
        name: str = "momentum_surge",
        vol_mult: float = 2.0,
        breakout_lookback: int = 5,
        consecutive: int = 2,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
        trail_pct: float = 0.025,
        require_theme: bool = False,
        bar_minutes: int = 1,
        min_bar_idx: int = 5,
        vol_avg_window: int = 20,
    ):
        super().__init__(
            name=name, breakout_lookback=breakout_lookback,
            bar_minutes=bar_minutes, vol_avg_window=vol_avg_window,
        )
        self.vol_mult = vol_mult
        self.consecutive = consecutive
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trail_pct = trail_pct
        self.require_theme = require_theme
        self.min_bar_idx = min_bar_idx

    def _is_rising_streak(self, closes, idx: int) -> bool:
        if idx < self.consecutive:
            return False
        for k in range(idx - self.consecutive + 1, idx + 1):
            if closes[k] <= closes[k - 1]:
                return False
        return True

    def check_entry_fast(self, code, idx, ind):
        n = ind["n_bars"]
        if idx < self.min_bar_idx or idx >= n:
            return None

        closes = ind["close"]
        if not self._is_rising_streak(closes, idx):
            return None

        vr = ind["vol_ratio"][idx]
        if np.isnan(vr) or vr < self.vol_mult:
            return None

        close = closes[idx]
        prior_high = ind["prior_high"][idx]
        if np.isnan(prior_high) or close <= prior_high:
            return None
        if close <= ind["vwap"][idx]:
            return None

        theme_conf = 1.0
        if self.require_theme:
            info = self._theme_info()
            if not info or not info.get("in_hot_theme"):
                return None
            if info.get("is_leader"):
                theme_conf = 1.3

        confidence = min(2.0, vr / self.vol_mult) * theme_conf
        return {
            "reason": f"모멘텀 {self.consecutive}연속+vol{vr:.1f}x",
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
        peak = position.peak_price if position.peak_price > 0 else position.entry_price
        if gain > 0 and price <= peak * (1 - self.trail_pct):
            return {"action": "close", "reason": "트레일링"}
        return None
