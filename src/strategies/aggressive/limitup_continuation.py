"""공격 티어 — 상따(상한가 따라잡기) 연속성 전략.

현실 제약: 잠긴 상한가는 못 산다. 그래서 '상한가 *접근* + 연속 상승'을 노린다.
  진입: 상한가 정보 존재 + 아직 미잠김(first_hit 전) + 잔여 상승폭 충분 + 상한가 근접 + 상승 모멘텀.
  청산: 트레일링 스톱으로 연속 상승을 태운다. 하드 손절/EOD는 엔진.

상한가가 이미 잠겼으면 진입하지 않고, realism의 limit_locked 체결불가와도 일관된다.
"""

import numpy as np

from src.strategies.aggressive.base import AggressiveIntradayBase


class LimitUpContinuationStrategy(AggressiveIntradayBase):
    """상한가 접근 + 연속성 (공격 티어)."""

    def __init__(
        self,
        name: str = "limitup_continuation",
        approach_band: float = 0.10,  # 상한가 대비 -10% 이내 접근
        min_edge: float = 0.03,       # 잔여 상승폭(상한가까지) 최소
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.20,  # 크게 잡고 트레일링으로 관리
        trail_pct: float = 0.03,
        require_rising: bool = True,
        bar_minutes: int = 1,
        min_bar_idx: int = 1,
    ):
        super().__init__(name=name, bar_minutes=bar_minutes)
        self.approach_band = approach_band
        self.min_edge = min_edge
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trail_pct = trail_pct
        self.require_rising = require_rising
        self.min_bar_idx = min_bar_idx

    def check_entry_fast(self, code, idx, ind):
        n = ind["n_bars"]
        if idx < self.min_bar_idx or idx >= n:
            return None

        info = self._limit_info()
        if not info:  # 상한가 정보 없으면 fail-closed
            return None
        limit_price = info.get("limit_price")
        if not limit_price or limit_price <= 0:
            return None

        close = ind["close"][idx]
        if close <= 0:
            return None

        # 이미 잠김(first_hit 이후)이면 진입 안 함
        first_hit = info.get("first_hit_time")
        if first_hit is not None:
            ts = ind["timestamps"][idx]
            cur_t = ts.time() if hasattr(ts, "time") else None
            if cur_t is not None and cur_t >= first_hit:
                return None

        remaining = (limit_price - close) / close
        if remaining < self.min_edge:  # 이미 상한가 코앞 → 잔여 상승폭 부족
            return None
        if close < limit_price * (1 - self.approach_band):  # 너무 멀다
            return None

        # 상승 모멘텀 확인
        if self.require_rising and idx >= 1 and close <= ind["close"][idx - 1]:
            return None

        confidence = min(2.0, remaining / self.min_edge)
        return {
            "reason": f"상따 접근 잔여{remaining:.1%}",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
            "confidence": confidence,
            "limit_locked": False,  # 미잠김에서만 진입
        }

    def check_exit_fast(self, position, idx, ind):
        n = ind["n_bars"]
        if idx >= n:
            return None
        price = ind["close"][idx]
        gain = price / position.entry_price - 1.0
        peak = position.peak_price if position.peak_price > 0 else position.entry_price
        # 트레일링: 이익 구간에서 고점 대비 trail_pct 되돌리면 청산
        if gain > 0 and price <= peak * (1 - self.trail_pct):
            return {"action": "close", "reason": "트레일링"}
        return None
