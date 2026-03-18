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

    def _get_rsi_range(self) -> tuple[float, float]:
        """KOSPI 상태에 따른 동적 RSI 범위.

        상승장: RSI 50-70 (시장을 따라가는 종목만)
        보합장: RSI 40-60 (기존)
        하락장: RSI 35-55 (하락에 덜 빠지는 종목)
        """
        k = self._market_change_pct
        if k >= 1.0:      # 강한 상승장
            return 50.0, 70.0
        elif k >= 0.0:     # 약상승/보합
            return 45.0, 65.0
        elif k >= -1.0:    # 약하락
            return 40.0, 60.0
        else:              # 급락
            return 35.0, 55.0

    def _get_adaptive_sl_tp(self, atr_val: float) -> tuple[float, float]:
        """KOSPI 상태에 따른 적응형 SL/TP.

        상승장: SL 넓게(덜 잘림), TP 낮게(빨리 익절)
        하락장: SL 좁게(빨리 손절), TP 유지
        """
        k = self._market_change_pct
        if k >= 1.0:
            # 상승장: SL 넓게(일시 눌림 견딤), TP 현실적(3.5%)
            base_sl, base_tp = 0.035, 0.035
        elif k >= 0.0:
            base_sl, base_tp = 0.03, 0.045
        else:
            base_sl, base_tp = 0.025, 0.05

        if not np.isnan(atr_val):
            sl = max(base_sl, 1.5 * atr_val)
            tp = max(base_tp, 2.5 * atr_val)
        else:
            sl, tp = base_sl, base_tp

        # 상한 제한
        sl = min(sl, 0.045)
        tp = min(tp, 0.06)
        return sl, tp

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

        volume_acceleration = (ind["volume"] - np.roll(ind["volume"], 1)) / np.roll(ind["volume"], 1)
        ind["volume_acceleration"] = np.where(np.roll(ind["volume"], 1) == 0, 0, volume_acceleration)

        recent_tr_range = rolling_mean_np(atr, window=3)
        ind["recent_tr_range"] = recent_tr_range

        # 시가 대비 등락률 (종목의 당일 모멘텀)
        day_open = opens[0] if n > 0 and opens[0] > 0 else 1.0
        ind["intraday_return"] = (closes / day_open - 1.0) * 100  # %

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

        # ── 핵심 변경: 동적 RSI 범위 ──
        rsi_lo, rsi_hi = self._get_rsi_range()
        if rsi[bar_idx] < rsi_lo or rsi[bar_idx] > rsi_hi:
            return None

        if not bullish_candle[bar_idx - 1] or not bullish_candle[bar_idx - 2]:
            return None

        if closes[bar_idx] < vwap[bar_idx]:
            return None

        if volumes[bar_idx] < avg_volume[bar_idx] * 1.2:
            return None

        if high_diff[bar_idx] <= 0:
            return None

        if volume_accel[bar_idx] < 0.05:
            return None

        if recent_tr_range[bar_idx] < 0.004:
            return None

        # ── 상승장 추가 조건: 종목도 시장을 따라가야 함 ──
        if self._market_change_pct >= 1.0:
            intraday_ret = indicators["intraday_return"][bar_idx]
            # 상승장인데 종목이 마이너스면 진입하지 않음
            if intraday_ret < 0.5:
                return None

        # ── 동적 SL/TP ──
        sl, tp = self._get_adaptive_sl_tp(atr[bar_idx])

        return {
            "reason": (f"rsi={rsi[bar_idx]:.1f}({rsi_lo:.0f}-{rsi_hi:.0f}), "
                       f"atr={atr[bar_idx]:.4f}, kospi={self._market_change_pct:+.1f}%, "
                       f"hong={hong_reason}"),
            "stop_loss": sl,
            "take_profit": tp,
            "confidence": 1.0 * self.hong_confidence_boost(),
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        return None

    def check_entry(self, code, current_bar, historical):
        return None

    def check_exit(self, position, current_bar, historical):
        return None
