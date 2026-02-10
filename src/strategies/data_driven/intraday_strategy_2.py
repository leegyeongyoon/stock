import numpy as np
from src.strategies.intraday.base import IntradayStrategy

class LunchRSINeutralATRVolumeStrategy(IntradayStrategy):
    """점심 시간대(11-13시) RSI 중립 + 거래량 급증 + ATR 높음 전략."""

    def __init__(self):
        super().__init__(name="lunch_rsi_neutral_atr_volume")
        self.min_bars = 15
        self.atr_threshold = 0.005389
        self.vol_ratio_threshold = 1.17
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.05

    def precompute_day(self, day_df):
        ind = super().precompute_day(day_df)
        closes = ind["close"]
        highs = ind["high"]
        lows = ind["low"]
        opens = ind["open"]
        volumes = ind["volume"]
        vol_avg_20 = ind["vol_avg_20"]
        n = ind["n_bars"]

        atr = np.full(n, np.nan)
        for i in range(1, n):
            if i >= 10:
                tr_sum = 0.0
                for j in range(i-9, i+1):
                    tr_sum += max(highs[j] - lows[j],
                                  abs(highs[j] - closes[j-1]),
                                  abs(lows[j] - closes[j-1]))
                atr[i] = (tr_sum / 10.0) / closes[i] if closes[i] > 0 else 0.0
        ind["atr_10_pct"] = atr

        vol_ratio = np.full(n, np.nan)
        for i in range(n):
            if vol_avg_20[i] > 0:
                vol_ratio[i] = volumes[i] / vol_avg_20[i]
        ind["vol_ratio"] = vol_ratio

        hours = np.array([ts.hour if hasattr(ts, 'hour') else 0 for ts in ind["timestamps"]])
        ind["hours"] = hours

        bullish_candle = closes > opens
        ind["bullish_candle"] = bullish_candle

        return ind

    def check_entry_fast(self, code, bar_idx, indicators):
        if bar_idx < self.min_bars:
            return None
        n = indicators["n_bars"]
        if bar_idx >= n:
            return None

        atr = indicators["atr_10_pct"]
        rsi = indicators["rsi_14"]
        hours = indicators["hours"]
        vol_ratio = indicators["vol_ratio"]
        bullish_candle = indicators["bullish_candle"]

        hour = hours[bar_idx]
        if hour < 11 or hour >= 13:
            return None
        if np.isnan(atr[bar_idx]) or np.isnan(rsi[bar_idx]) or np.isnan(vol_ratio[bar_idx]):
            return None
        if atr[bar_idx] < self.atr_threshold:
            return None
        if rsi[bar_idx] < 40 or rsi[bar_idx] > 60:
            return None
        if vol_ratio[bar_idx] < self.vol_ratio_threshold:
            return None
        if not bullish_candle[bar_idx - 1]:
            return None

        return {
            "reason": f"rsi_neutral={rsi[bar_idx]:.2f}, atr={atr[bar_idx]:.4f}, vol_ratio={vol_ratio[bar_idx]:.2f}",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        return None
    def check_entry(self, code, current_bar, historical):
        return None
    def check_exit(self, position, current_bar, historical):
        return None