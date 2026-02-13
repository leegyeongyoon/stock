import numpy as np
from src.strategies.intraday.base import IntradayStrategy, rolling_mean_np, rsi_np, vwap_np
from src.strategies.data_driven.hong_filter_mixin import HongFilterMixin

class MorningRSINeutralATRStrategy(HongFilterMixin, IntradayStrategy):
    HONG_MIN_KI_SCORE = 30
    HONG_MIN_CAP_BIL = 5000
    HONG_MIN_INST_BIL = 50

    def __init__(self):
        super().__init__(name="morning_rsi_neutral_atr")
        self.min_bars = 15
        self.atr_threshold = 0.0045
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.05

    def precompute_day(self, day_df):
        ind = super().precompute_day(day_df)

        closes = ind["close"]
        highs = ind["high"]
        lows = ind["low"]
        opens = ind["open"]
        n = ind["n_bars"]

        atr = np.full(n, np.nan)
        for i in range(1, n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
            if i >= 10:
                tr_sum = sum(max(highs[j] - lows[j],
                                 abs(highs[j] - closes[j-1]),
                                 abs(lows[j] - closes[j-1])) for j in range(i-9, i+1))
                atr[i] = (tr_sum / 10.0) / closes[i] if closes[i] > 0 else 0.0
        ind["atr_10_pct"] = atr

        hours = np.array([ts.hour if hasattr(ts, 'hour') else 0 for ts in ind["timestamps"]])
        ind["hours"] = hours

        bullish_candle = closes > opens
        ind["bullish_candle"] = bullish_candle

        cum_volume = np.cumsum(ind["volume"])
        cum_vwap = np.cumsum(ind["volume"] * closes)
        vwap = np.divide(cum_vwap, cum_volume, out=np.zeros_like(cum_vwap), where=cum_volume != 0)
        ind["vwap"] = vwap

        avg_volume = rolling_mean_np(ind["volume"], window=10)
        ind["avg_volume"] = avg_volume

        ind["bar_trading_value"] = closes * ind["volume"]
        ind["cum_trading_value"] = np.cumsum(ind["bar_trading_value"])

        high_diff = highs - np.roll(highs, 1)
        ind["high_diff"] = high_diff

        # 추가된 부분: 거래량 가속도 지표 추가
        volume_acceleration = (ind["volume"] - np.roll(ind["volume"], 1)) / np.roll(ind["volume"], 1)
        ind["volume_acceleration"] = np.where(np.roll(ind["volume"], 1) == 0, 0, volume_acceleration)

        # 추가된 부분: 최근 3봉의 평균 true range 비율 추가
        recent_tr_range = rolling_mean_np(atr, window=3)
        ind["recent_tr_range"] = recent_tr_range

        return ind

    def check_entry_fast(self, code, bar_idx, indicators):
        if bar_idx < self.min_bars:
            return None

        n = indicators["n_bars"]
        if bar_idx >= n:
            return None

        passes, hong_reason = self.passes_hong_filter()
        if not passes:
            return None

        if not self.passes_intraday_value_filter(bar_idx, indicators):
            return None

        atr = indicators["atr_10_pct"]
        rsi = indicators["rsi_14"]
        hours = indicators["hours"]
        bullish_candle = indicators["bullish_candle"]
        vwap = indicators["vwap"]
        closes = indicators["close"]
        volumes = indicators["volume"]
        avg_volume = indicators["avg_volume"]
        high_diff = indicators["high_diff"]
        volume_accel = indicators["volume_acceleration"]
        recent_tr_range = indicators["recent_tr_range"]

        hour = hours[bar_idx]
        if hour < 9 or (hour == 9 and bar_idx % 12 < 6) or hour >= 11:
            return None

        if np.isnan(atr[bar_idx]) or np.isnan(rsi[bar_idx]):
            return None

        if atr[bar_idx] < self.atr_threshold:
            return None

        if rsi[bar_idx] < 40 or rsi[bar_idx] > 60:
            return None

        if not bullish_candle[bar_idx - 1] or not bullish_candle[bar_idx - 2]:
            return None

        if closes[bar_idx] < vwap[bar_idx]:
            return None

        if volumes[bar_idx] < avg_volume[bar_idx] * 1.2:
            return None

        if high_diff[bar_idx] <= 0:
            return None

        # 새로운 조건: 거래량 가속도와 최근 3봉의 평균 트루 레인지 비율 확인
        if volume_accel[bar_idx] < 0.05:
            return None

        if recent_tr_range[bar_idx] < 0.004:
            return None

        return {
            "reason": f"rsi_neutral={rsi[bar_idx]:.2f}, atr={atr[bar_idx]:.4f}, hong={hong_reason}",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
            "confidence": 1.0 * self.hong_confidence_boost(),
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        return None

    def check_entry(self, code, current_bar, historical):
        return None

    def check_exit(self, position, current_bar, historical):
        return None