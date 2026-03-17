import numpy as np
from src.strategies.intraday.base import IntradayStrategy
from src.strategies.data_driven.hong_filter_mixin import HongFilterMixin

class ModifiedRSINeutralATRStrategy(HongFilterMixin, IntradayStrategy):
    """9시에서 14시 사이 RSI 중립, VWAP 위, ATR 높음, 2연속 양봉인 경우 진입하는 전략."""

    # 종일: 좋은 일봉자리만
    HONG_PREFERRED_POSITIONS = {"신고가", "전고점돌파"}
    HONG_MIN_CAP_BIL = 5000
    HONG_MIN_INST_BIL = 50

    def __init__(self):
        super().__init__(name="modified_rsi_neutral_atr")
        self.min_bars = 15
        self.atr_threshold = 0.005
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.05

    def precompute_day(self, day_df):
        ind = super().precompute_day(day_df)
        closes = ind["close"]
        opens = ind["open"]
        n = ind["n_bars"]
        
        atr = np.full(n, np.nan)
        for i in range(1, n):
            if i >= 10:
                tr_sum = 0.0
                for j in range(i-9, i+1):
                    tr_sum += max(ind["high"][j] - ind["low"][j],
                                  abs(ind["high"][j] - closes[j-1]),
                                  abs(ind["low"][j] - closes[j-1]))
                atr[i] = (tr_sum / 10.0) / closes[i] if closes[i] > 0 else 0.0
        ind["atr_10_pct"] = atr

        hours = np.array([ts.hour if hasattr(ts, 'hour') else 0 for ts in ind["timestamps"]])
        minutes = np.array([ts.minute if hasattr(ts, 'minute') else 0 for ts in ind["timestamps"]])
        ind["hours"] = hours
        ind["minutes"] = minutes

        bullish_candle = closes > opens
        ind["bullish_candle"] = bullish_candle

        # 거래대금 (홍인기 필터용)
        ind["bar_trading_value"] = closes * ind["volume"]
        ind["cum_trading_value"] = np.cumsum(ind["bar_trading_value"])

        return ind

    def check_entry_fast(self, code, bar_idx, indicators):
        if bar_idx < self.min_bars:
            return None
        n = indicators["n_bars"]
        if bar_idx >= n:
            return None

        # === 홍인기 필터 ===
        passes, hong_reason = self.passes_hong_filter()
        if not passes:
            return None

        # === 당일 누적 거래대금 필터 ===
        if not self.passes_intraday_value_filter(bar_idx, indicators):
            return None

        atr = indicators["atr_10_pct"]
        rsi = indicators["rsi_14"]
        vwap = indicators["vwap"]
        closes = indicators["close"]
        hours = indicators["hours"]
        bullish_candle = indicators["bullish_candle"]

        hour = hours[bar_idx]
        minute = indicators["minutes"][bar_idx]

        # 시간대 필터: 09시 전체, 10:45~10:59, 11시 전체만 허용
        # 10:00~10:44 차단 (WR 29.4%, -324k 손실구간)
        # 12:00 이후 전면 차단 (14시 WR 16.7%, -355k 손실구간)
        if not ((hour == 9) or (hour == 10 and minute >= 45) or (hour == 11)):
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

        # 적응형 SL/TP (오전 전용: SL 2.5%, TP 4.5%, ATR 보정)
        atr_val = atr[bar_idx]
        adaptive_sl = max(0.025, 1.5 * atr_val) if not np.isnan(atr_val) else 0.025
        adaptive_tp = max(0.045, 2.5 * atr_val) if not np.isnan(atr_val) else 0.045
        # 상한 제한
        adaptive_sl = min(adaptive_sl, 0.04)
        adaptive_tp = min(adaptive_tp, 0.06)

        return {
            "reason": f"rsi_neutral={rsi[bar_idx]:.2f}, atr={atr[bar_idx]:.4f}, hong={hong_reason}",
            "stop_loss": adaptive_sl,
            "take_profit": adaptive_tp,
            "confidence": 1.0 * self.hong_confidence_boost(),
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        return None
    def check_entry(self, code, current_bar, historical):
        return None
    def check_exit(self, position, current_bar, historical):
        return None