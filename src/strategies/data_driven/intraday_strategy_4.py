import numpy as np
from src.strategies.intraday.base import IntradayStrategy, rolling_mean_np, rsi_np, vwap_np

class AfternoonRSINeutralATRStrategy(IntradayStrategy):
    """오후 13시에서 15시 사이 RSI가 중립 영역(40-60)에 있고 ATR, VWAP, 2연속 양봉 조건 진입 전략. (전략1 시간대 변형)"""

    def __init__(self):
        super().__init__(name="afternoon_from_morning")
        self.min_bars = 15
        self.atr_threshold = 0.0050  # ATR 임계값을 약간 하향 조정
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.05

    def precompute_day(self, day_df):
        """하루치 지표를 numpy 배열로 사전계산."""
        ind = super().precompute_day(day_df)

        closes = ind["close"]
        highs = ind["high"]
        lows = ind["low"]
        opens = ind["open"]
        n = ind["n_bars"]

        # ATR (10-bar) 계산
        atr = np.full(n, np.nan)
        for i in range(1, n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
            if i >= 10:
                tr_sum = 0.0
                for j in range(i-9, i+1):
                    tr_sum += max(highs[j] - lows[j],
                                  abs(highs[j] - closes[j-1]),
                                  abs(lows[j] - closes[j-1]))
                atr[i] = (tr_sum / 10.0) / closes[i] if closes[i] > 0 else 0.0
        ind["atr_10_pct"] = atr

        # 시간 (hour) 배열 - timestamps에서 추출
        hours = np.array([ts.hour if hasattr(ts, 'hour') else 0 for ts in ind["timestamps"]])
        ind["hours"] = hours

        # 양봉 여부 계산
        bullish_candle = closes > opens
        ind["bullish_candle"] = bullish_candle

        # VWAP 계산
        cum_volume = np.cumsum(ind["volume"])
        cum_vwap = np.cumsum(ind["volume"] * closes)
        vwap = np.divide(cum_vwap, cum_volume, out=np.zeros_like(cum_vwap), where=cum_volume != 0)
        ind["vwap"] = vwap

        return ind

    def check_entry_fast(self, code, bar_idx, indicators):
        """진입 조건 확인 (numpy 기반)."""
        if bar_idx < self.min_bars:
            return None

        n = indicators["n_bars"]
        if bar_idx >= n:
            return None

        atr = indicators["atr_10_pct"]
        rsi = indicators["rsi_14"]
        hours = indicators["hours"]
        bullish_candle = indicators["bullish_candle"]
        vwap = indicators["vwap"]
        closes = indicators["close"]

        # 시간 필터: 13시~15시
        hour = hours[bar_idx]
        if hour < 13 or hour >= 15:
            return None

        # NaN 체크
        if np.isnan(atr[bar_idx]):
            return None
        if np.isnan(rsi[bar_idx]):
            return None

        # 조건 1: ATR 상위 25%
        if atr[bar_idx] < self.atr_threshold:
            return None

        # 조건 2: RSI 중립 영역
        if rsi[bar_idx] < 40 or rsi[bar_idx] > 60:
            return None

        # 조건 3: 직전 bar 양봉 확인
        if not bullish_candle[bar_idx - 1]:
            return None

        # 추가 조건: 직전 2bar 양봉 확인 (손실 줄이기)
        if bar_idx > 1 and not bullish_candle[bar_idx - 2]:
            return None

        # 조건 4: 현재가가 VWAP 위에 있을 때
        if closes[bar_idx] < vwap[bar_idx]:
            return None

        return {
            "reason": f"rsi_neutral={rsi[bar_idx]:.2f}, atr={atr[bar_idx]:.4f}",
            "stop_loss": self.stop_loss_pct,
            "take_profit": self.take_profit_pct,
        }

    def check_exit_fast(self, position, bar_idx, indicators):
        """청산 조건 확인."""
        return None

    def check_entry(self, code, current_bar, historical):
        return None

    def check_exit(self, position, current_bar, historical):
        return None