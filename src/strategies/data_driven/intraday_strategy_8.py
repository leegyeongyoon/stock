import numpy as np
from src.strategies.intraday.base import IntradayStrategy

class MorningWideRSINeutralATRStrategy(IntradayStrategy):
    """9시에서 14시 사이 RSI 중립, VWAP 위, ATR 높음, 2연속 양봉인 경우 진입하는 전략."""

    def __init__(self):
        super().__init__(name="morning_wide_rsi")
        self.min_bars = 15
        self.atr_threshold = 0.005
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.05

        # small changes (1-2): tighten time window, add volume filter
        self.end_hour = 11  # trade only before 11:30
        self.min_vol_ratio = 1.15  # current volume must be >= 1.15x recent avg

    def precompute_day(self, day_df):
        ind = super().precompute_day(day_df)
        closes = ind["close"]
        opens = ind["open"]
        n = ind["n_bars"]

        atr = np.full(n, np.nan)
        for i in range(1, n):
            if i >= 10:
                tr_sum = 0.0
                for j in range(i - 9, i + 1):
                    tr_sum += max(
                        ind["high"][j] - ind["low"][j],
                        abs(ind["high"][j] - closes[j - 1]),
                        abs(ind["low"][j] - closes[j - 1]),
                    )
                atr[i] = (tr_sum / 10.0) / closes[i] if closes[i] > 0 else 0.0
        ind["atr_10_pct"] = atr

        hours = np.array([ts.hour if hasattr(ts, "hour") else 0 for ts in ind["timestamps"]])
        ind["hours"] = hours

        bullish_candle = closes > opens
        ind["bullish_candle"] = bullish_candle

        vols = ind["volume"] if "volume" in ind else np.full(n, np.nan)
        ind["volume"] = vols

        vol_sma10 = np.full(n, np.nan)
        for i in range(n):
            if i >= 10:
                s = 0.0
                for j in range(i - 9, i + 1):
                    v = vols[j]
                    s += 0.0 if np.isnan(v) else float(v)
                vol_sma10[i] = s / 10.0
        ind["vol_sma10"] = vol_sma10

        return ind

    def check_entry_fast(self, code, bar_idx, indicators):
        if bar_idx < self.min_bars:
            return None
        n = indicators["n_bars"]
        if bar_idx >= n:
            return None

        atr = indicators["atr_10_pct"]
        rsi = indicators["rsi_14"]
        vwap = indicators["vwap"]
        closes = indicators["close"]
        hours = indicators["hours"]
        bullish_candle = indicators["bullish_candle"]
        vols = indicators["volume"]
        vol_sma10 = indicators["vol_sma10"]

        hour = hours[bar_idx]
        # 9:30 ~ 11:30 only
        if hour < 9 or (hour == 9 and bar_idx % 12 < 6) or hour > self.end_hour or (hour == self.end_hour and bar_idx % 12 >= 6):
            return None

        if np.isnan(atr[bar_idx]) or np.isnan(rsi[bar_idx]) or np.isnan(vwap[bar_idx]):
            return None
        if atr[bar_idx] < self.atr_threshold:
            return None
        if rsi[bar_idx] < 40 or rsi[bar_idx] > 60:
            return None
        if closes[bar_idx] <= vwap[bar_idx] * 1.002:
            return None
        if not bullish_candle[bar_idx - 1] or not bullish_candle[bar_idx - 2]:
            return None

        if np.isnan(vols[bar_idx]) or np.isnan(vol_sma10[bar_idx]) or vol_sma10[bar_idx] <= 0:
            return None
        if vols[bar_idx] < vol_sma10[bar_idx] * self.min_vol_ratio:
            return None

        return {
            "reason": f"rsi_neutral={rsi[bar_idx]:.2f}, atr={atr[bar_idx]:.4f}, vol_ratio={(vols[bar_idx]/vol_sma10[bar_idx]):.2f}",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        return None

    def check_entry(self, code, current_bar, historical):
        return None

    def check_exit(self, position, current_bar, historical):
        return None