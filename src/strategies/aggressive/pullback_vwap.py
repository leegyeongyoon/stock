"""고수 눌림목 + VWAP 기법 (대형주 평균회귀를 역이용).

돌파 추격이 아니라, '초반에 거래량 터지며 급등한 끼 있는 종목'이 VWAP 위에서 눌릴 때
반등 전환봉을 사서 짧게 익절한다. 한국 단타 고수들의 전형적 눌림목 매매.

진입 조건:
  1) 추세 유지: 현재가 > VWAP
  2) 끼 확인: 장중 고점이 시가 대비 +morning_surge_min 이상 (한 번 치고 올라왔음)
  3) 초반 거래량 끼: 장중 누적 최대 거래량비 >= vol_spike_min
  4) 눌림: 현재가가 장중 고점 대비 pullback_min ~ pullback_max 하락
  5) 과열 회피: VWAP 대비 +max_vwap_ext 이내, RSI 과열 아님
  6) 반등 트리거: 현재 봉 상승전환(close>open AND close>직전 종가)
청산:
  - VWAP 이탈 시 즉시 청산(추세 훼손)
  - +partial_tp 부분익절 → 손익분기 잠금 → 시간 청산. 하드 손절은 엔진 SL.
"""

import numpy as np

from src.strategies.aggressive.base import AggressiveIntradayBase


class PullbackVWAPStrategy(AggressiveIntradayBase):
    """초반 급등 후 VWAP 위 눌림목 반등 (공격/균형 공용 고수 기법)."""

    def __init__(
        self,
        name: str = "pullback_vwap",
        morning_surge_min: float = 0.02,  # 장중 고점이 시가 대비 +2% 이상(끼)
        pullback_min: float = 0.008,      # 고점 대비 -0.8% 이상 눌림
        pullback_max: float = 0.04,       # 고점 대비 -4% 이내(너무 깊으면 추세훼손)
        max_vwap_ext: float = 0.03,       # VWAP 대비 +3% 이내(과열 회피)
        vol_spike_min: float = 2.0,       # 장중 누적 최대 거래량비
        rsi_overheat: float = 78.0,
        stop_loss_pct: float = 0.015,
        take_profit_pct: float = 0.03,
        partial_tp: float = 0.02,
        breakeven_lock: float = 0.005,
        time_stop_min: int = 40,
        min_progress: float = 0.008,
        max_entry_hour: int = 12,         # 오전 위주(12시 이후 진입 금지). 0=제한없음
        bar_minutes: int = 5,
        vol_avg_window: int = 20,
        min_bar_idx: int = 4,
        use_orderflow: bool = False,      # 체결강도/잔량비 게이트(데이터 주입 시)
        min_exec_strength: float = 110.0,
        min_bid_ratio: float = 1.0,
    ):
        super().__init__(name=name, bar_minutes=bar_minutes, vol_avg_window=vol_avg_window)
        self.morning_surge_min = morning_surge_min
        self.pullback_min = pullback_min
        self.pullback_max = pullback_max
        self.max_vwap_ext = max_vwap_ext
        self.vol_spike_min = vol_spike_min
        self.rsi_overheat = rsi_overheat
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.partial_tp = partial_tp
        self.breakeven_lock = breakeven_lock
        self.time_stop_min = time_stop_min
        self.min_progress = min_progress
        self.max_entry_hour = max_entry_hour
        self.min_bar_idx = min_bar_idx
        self.use_orderflow = use_orderflow
        self.min_exec_strength = min_exec_strength
        self.min_bid_ratio = min_bid_ratio

    def precompute_day(self, day_df) -> dict:
        ind = super().precompute_day(day_df)
        n = ind["n_bars"]
        if n == 0:
            ind["run_high"] = ind["high"]
            ind["run_max_volratio"] = ind["vol_ratio"]
            ind["day_open"] = 0.0
            return ind
        ind["run_high"] = np.maximum.accumulate(ind["high"])         # 장중 누적 고가
        vr = np.where(np.isnan(ind["vol_ratio"]), 0.0, ind["vol_ratio"])
        ind["run_max_volratio"] = np.maximum.accumulate(vr)          # 장중 누적 최대 거래량비
        ind["day_open"] = float(ind["open"][0])
        return ind

    def check_entry_fast(self, code, idx, ind):
        n = ind["n_bars"]
        if idx < self.min_bar_idx or idx >= n:
            return None
        if self.max_entry_hour and ind["hours"][idx] >= self.max_entry_hour:
            return None

        close = ind["close"][idx]
        vwap = ind["vwap"][idx]
        run_high = ind["run_high"][idx]
        day_open = ind["day_open"]
        if close <= 0 or vwap <= 0 or run_high <= 0 or day_open <= 0:
            return None

        # 1) 추세: VWAP 위
        if close <= vwap:
            return None
        # 2) 끼: 장중 고점이 시가 대비 충분히 올라왔나
        if (run_high / day_open - 1.0) < self.morning_surge_min:
            return None
        # 3) 초반 거래량 끼
        if ind["run_max_volratio"][idx] < self.vol_spike_min:
            return None
        # 4) 눌림: 고점 대비 적당히 하락
        drop = run_high / close - 1.0
        if drop < self.pullback_min or drop > self.pullback_max:
            return None
        # 5) 과열 회피
        if (close / vwap - 1.0) > self.max_vwap_ext:
            return None
        rsi = ind["rsi_14"][idx]
        if not np.isnan(rsi) and rsi > self.rsi_overheat:
            return None
        # 6) 반등 전환봉
        if close <= ind["open"][idx]:
            return None
        if idx >= 1 and close <= ind["close"][idx - 1]:
            return None
        # 7) 호가/체결강도 확인 (OHLC 봉 밖의 매수세 — 데이터 주입 시에만)
        if self.use_orderflow and not self.orderflow_ok(
            min_strength=self.min_exec_strength, min_bid_ratio=self.min_bid_ratio
        ):
            return None

        conf = min(2.0, ind["run_max_volratio"][idx] / self.vol_spike_min)
        return {
            "reason": f"눌림목 VWAP+ 눌림{drop:.1%}",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
            "confidence": conf,
        }

    def check_exit_fast(self, position, idx, ind):
        n = ind["n_bars"]
        if idx >= n:
            return None
        price = ind["close"][idx]
        vwap = ind["vwap"][idx]
        gain = price / position.entry_price - 1.0
        elapsed = self.elapsed_minutes(position, idx)

        # VWAP 이탈 → 추세 훼손, 즉시 청산
        if vwap > 0 and price < vwap:
            return {"action": "close", "reason": "VWAP이탈"}
        # +2% 부분익절
        if not position.partial_done and gain >= self.partial_tp:
            return {"action": "partial", "fraction": 0.5, "reason": f"TP1 +{self.partial_tp:.0%}"}
        # 부분익절 후 손익분기 아래 → 잔량 청산
        if position.partial_done and gain <= self.breakeven_lock:
            return {"action": "close", "reason": "잠금청산"}
        # 시간 청산
        if elapsed >= self.time_stop_min and gain < self.min_progress:
            return {"action": "close", "reason": "시간청산"}
        return None
