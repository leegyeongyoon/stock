"""공격 티어 — 연속 양봉 + 거래량 (단순 연속성 변형).

진입: N연속 양봉(close>open) + 거래량 평균 상회 + VWAP 상방. 청산: 트레일링.
돌파 조건이 없는 단순 모멘텀 변형으로, momentum_surge 보다 진입이 잦다.
"""

import numpy as np

from src.strategies.aggressive.base import AggressiveIntradayBase


class ConsecutiveSurgeStrategy(AggressiveIntradayBase):
    """연속 양봉 + 거래량 (공격 티어, 단순 변형)."""

    def __init__(
        self,
        name: str = "consecutive_surge",
        consecutive: int = 3,
        vol_mult: float = 1.5,
        stop_loss_pct: float = 0.025,
        take_profit_pct: float = 0.05,
        trail_pct: float = 0.025,
        bar_minutes: int = 1,
        min_bar_idx: int = 5,
        vol_avg_window: int = 20,
    ):
        super().__init__(name=name, bar_minutes=bar_minutes, vol_avg_window=vol_avg_window)
        self.consecutive = consecutive
        self.vol_mult = vol_mult
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trail_pct = trail_pct
        self.min_bar_idx = min_bar_idx

    def _bullish_streak(self, opens, closes, idx: int) -> bool:
        if idx < self.consecutive - 1:
            return False
        for k in range(idx - self.consecutive + 1, idx + 1):
            if closes[k] <= opens[k]:
                return False
        return True

    def check_entry_fast(self, code, idx, ind):
        n = ind["n_bars"]
        if idx < self.min_bar_idx or idx >= n:
            return None
        if not self._bullish_streak(ind["open"], ind["close"], idx):
            return None
        vr = ind["vol_ratio"][idx]
        if np.isnan(vr) or vr < self.vol_mult:
            return None
        if ind["close"][idx] <= ind["vwap"][idx]:
            return None
        return {
            "reason": f"{self.consecutive}연속양봉 vol{vr:.1f}x",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
            "confidence": min(2.0, vr / self.vol_mult),
        }

    def check_exit_fast(self, position, idx, ind):
        if idx >= ind["n_bars"]:
            return None
        price = ind["close"][idx]
        gain = price / position.entry_price - 1.0
        peak = position.peak_price if position.peak_price > 0 else position.entry_price
        if gain > 0 and price <= peak * (1 - self.trail_pct):
            return {"action": "close", "reason": "트레일링"}
        return None
