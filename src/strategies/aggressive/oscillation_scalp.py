"""오실레이션(평균회귀) 스캘프 — 반등-하락 반복 사이를 먹고팔고 반복.

움직이는(끼 있는) 종목이 장중 VWAP 아래로 눌리면 매수, VWAP 복귀(또는 +소폭)에 매도.
하루에 같은 종목을 여러 번 먹고팔 수 있다(백테스트 엔진은 청산 후 재진입 허용).

진입:
  1) 끼: 장중 고점이 시가 대비 +morning_surge_min 이상(한 번 치고 올라온 종목)
  2) 오버솔드: 현재가가 VWAP 대비 -vwap_dip 이하로 눌림
  3) 폭락 아님: 시가 대비 -max_down 이내(추세 붕괴 회피)
  4) 반등 전환봉: 현재 봉 상승전환(close>open)
청산:
  - VWAP 복귀 시 익절(평균회귀 완료) / +tp 도달 / 타이트 손절 / 짧은 시간청산
"""

import numpy as np

from src.strategies.aggressive.base import AggressiveIntradayBase


class OscillationScalpStrategy(AggressiveIntradayBase):
    """VWAP 밴드 평균회귀 스캘프 (먹고팔고 반복)."""

    def __init__(
        self,
        name: str = "oscillation_scalp",
        vwap_dip: float = 0.01,          # VWAP 대비 -1% 이하 눌림에 매수
        morning_surge_min: float = 0.02,  # 끼: 장중 고점 시가대비 +2%
        max_down: float = 0.06,          # 시가 대비 -6% 넘게 빠지면 진입 금지
        take_profit_pct: float = 0.015,  # +1.5% 천장
        stop_loss_pct: float = 0.012,    # -1.2% 손절
        time_stop_min: int = 15,
        max_entry_hour: int = 13,
        bar_minutes: int = 5,
        vol_avg_window: int = 20,
        min_bar_idx: int = 4,
    ):
        super().__init__(name=name, bar_minutes=bar_minutes, vol_avg_window=vol_avg_window)
        self.vwap_dip = vwap_dip
        self.morning_surge_min = morning_surge_min
        self.max_down = max_down
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.time_stop_min = time_stop_min
        self.max_entry_hour = max_entry_hour
        self.min_bar_idx = min_bar_idx

    def precompute_day(self, day_df) -> dict:
        ind = super().precompute_day(day_df)
        n = ind["n_bars"]
        ind["run_high"] = np.maximum.accumulate(ind["high"]) if n else ind["high"]
        ind["day_open"] = float(ind["open"][0]) if n else 0.0
        return ind

    def check_entry_fast(self, code, idx, ind):
        n = ind["n_bars"]
        if idx < self.min_bar_idx or idx >= n:
            return None
        if self.max_entry_hour and ind["hours"][idx] >= self.max_entry_hour:
            return None

        close = ind["close"][idx]
        vwap = ind["vwap"][idx]
        day_open = ind["day_open"]
        run_high = ind["run_high"][idx]
        if close <= 0 or vwap <= 0 or day_open <= 0:
            return None
        # 끼: 한 번 치고 올라온 종목
        if (run_high / day_open - 1.0) < self.morning_surge_min:
            return None
        # 오버솔드: VWAP 아래로 충분히 눌림
        if close > vwap * (1 - self.vwap_dip):
            return None
        # 폭락 회피
        if close < day_open * (1 - self.max_down):
            return None
        # 반등 전환봉
        if close <= ind["open"][idx]:
            return None

        dip = vwap / close - 1.0
        return {
            "reason": f"VWAP-{dip:.1%} 반등",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
            "confidence": min(2.0, dip / self.vwap_dip),
        }

    def check_exit_fast(self, position, idx, ind):
        n = ind["n_bars"]
        if idx >= n:
            return None
        price = ind["close"][idx]
        vwap = ind["vwap"][idx]
        gain = price / position.entry_price - 1.0
        elapsed = self.elapsed_minutes(position, idx)
        # VWAP 복귀 = 평균회귀 완료 → 익절 (이익일 때만)
        if vwap > 0 and price >= vwap and gain > 0:
            return {"action": "close", "reason": "VWAP복귀"}
        # 짧은 시간 내 진척 없으면 정리
        if elapsed >= self.time_stop_min and gain < 0.003:
            return {"action": "close", "reason": "시간청산"}
        return None
