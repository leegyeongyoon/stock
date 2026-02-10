import numpy as np
from src.strategies.intraday.base import IntradayStrategy

class AfternoonRSINeutralATRVolumeStrategy(IntradayStrategy):
    """오후 1시에서 2시 30분 사이 RSI가 40-55 중립 영역에 있고 ATR, VWAP, 거래량 급증 조건을 만족하는 경우 진입 전략."""
    
    def __init__(self):
        super().__init__(name="afternoon_rsi_neutral_atr_volume")
        self.min_bars = 15
        self.atr_threshold_low = 0.0040 
        self.atr_threshold_high = 0.0060
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.05

    def precompute_day(self, day_df):
        """하루치 지표를 numpy 배열로 사전계산."""
        ind = super().precompute_day(day_df)

        closes = ind["close"]
        highs = ind["high"]
        lows = ind["low"]
        opens = ind["open"]
        volumes = ind["volume"]
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
        cum_volume = np.cumsum(volumes)
        cum_vwap = np.cumsum(volumes * closes)
        vwap = np.divide(cum_vwap, cum_volume, out=np.zeros_like(cum_vwap), where=cum_volume != 0)
        ind["vwap"] = vwap

        # 이전 5개의 평균 거래량 계산
        avg_volume_last_5 = np.full(n, np.nan)
        for i in range(len(volumes)):
            avg_volume_last_5[i] = np.mean(volumes[max(0, i-5):i+1]) if i >= 5 else np.nan
        ind["avg_volume_last_5"] = avg_volume_last_5

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
        volumes = indicators["volume"]
        avg_volume_last_5 = indicators["avg_volume_last_5"]

        # 시간 필터: 13시~14:30시
        hour = hours[bar_idx]
        if hour < 13 or (hour == 14 and bar_idx % 12 > 5):
            return None

        # NaN 체크
        if np.isnan(atr[bar_idx]) or np.isnan(rsi[bar_idx]) or np.isnan(avg_volume_last_5[bar_idx]):
            return None

        # 조건 1: ATR 범위 체크
        if not (self.atr_threshold_low <= atr[bar_idx] <= self.atr_threshold_high):
            return None

        # 조건 2: RSI 40-55 중립 영역
        if not (40 <= rsi[bar_idx] <= 55):
            return None

        # 조건 3: 직전 두 개 bar 양봉 확인
        if not bullish_candle[bar_idx - 1]:
            return None

        # 조건 4: 현재가가 VWAP 위에 있을 때
        if closes[bar_idx] < vwap[bar_idx]:
            return None

        # 조건 5: 거래량 급증 (1.3배 초과)
        if volumes[bar_idx] <= 1.3 * avg_volume_last_5[bar_idx]:
            return None

        return {
            "reason": f"rsi_neutral={rsi[bar_idx]:.2f}, atr={atr[bar_idx]:.4f}, vol_spike={volumes[bar_idx] / avg_volume_last_5[bar_idx]:.2f}",
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