"""Volume Surge Strategy - Trades sudden volume spikes."""

from typing import Optional

import pandas as pd
import numpy as np

from src.strategies.intraday.base import IntradayStrategy


class VolumeSurgeStrategy(IntradayStrategy):
    """
    Volume Surge Strategy.

    Detects unusual volume spikes that often precede price moves:
    - Volume spike > 3x average
    - Price moving in direction of the surge
    - Confirmatory candle patterns
    """

    def __init__(
        self,
        volume_surge_ratio: float = 3.0,  # 3x average volume
        min_price_move: float = 0.005,  # 0.5% minimum price move
        lookback_period: int = 20,
        rsi_neutral_min: int = 35,
        rsi_neutral_max: int = 65,
        stop_loss: float = 0.018,  # 1.8%
        take_profit: float = 0.028,  # 2.8%
    ):
        super().__init__("Volume Surge")
        self.volume_surge_ratio = volume_surge_ratio
        self.min_price_move = min_price_move
        self.lookback_period = lookback_period
        self.rsi_neutral_min = rsi_neutral_min
        self.rsi_neutral_max = rsi_neutral_max
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def check_entry(
        self,
        code: str,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[dict]:
        """Check for volume surge entry."""
        if len(historical) < self.lookback_period + 5:
            return None

        # Calculate average volume
        avg_volume = historical["volume"].iloc[:-1].rolling(self.lookback_period).mean().iloc[-1]
        current_volume = float(current_bar["volume"])

        # Check for volume surge
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        if volume_ratio < self.volume_surge_ratio:
            return None

        # Check price direction
        open_price = float(current_bar["open"])
        close_price = float(current_bar["close"])
        price_change = (close_price - open_price) / open_price

        # Only long entries for now
        if price_change < self.min_price_move:
            return None

        # Check for strong bullish candle
        high_price = float(current_bar["high"])
        low_price = float(current_bar["low"])
        bar_range = high_price - low_price

        if bar_range > 0:
            body = close_price - open_price
            body_ratio = body / bar_range
            # Strong bullish: body > 60% of range
            if body_ratio < 0.6:
                return None

        # RSI check - not at extremes
        rsi = self.calculate_rsi(historical["close"], period=14)
        current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

        if current_rsi < self.rsi_neutral_min or current_rsi > self.rsi_neutral_max:
            return None

        # Check previous bar wasn't also a surge (avoid chasing)
        if len(historical) >= 2:
            prev_volume = float(historical.iloc[-2]["volume"])
            prev_ratio = prev_volume / avg_volume if avg_volume > 0 else 0
            if prev_ratio > self.volume_surge_ratio * 0.8:
                return None

        return {
            "reason": f"거래량 급증: {volume_ratio:.1f}x, 가격 {price_change*100:.2f}% 상승",
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
        }

    def check_exit(
        self,
        position,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[str]:
        """Check for exit signal."""
        if len(historical) < 5:
            return None

        # Volume dry up check
        avg_volume = historical["volume"].rolling(20).mean().iloc[-1]
        current_volume = float(current_bar["volume"])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        # Exit if volume drops significantly
        if volume_ratio < 0.5:
            return "거래량 급감"

        # Bearish reversal
        open_price = float(current_bar["open"])
        close_price = float(current_bar["close"])
        high_price = float(current_bar["high"])

        # Strong bearish candle with high volume
        if close_price < open_price and volume_ratio > 1.5:
            body = open_price - close_price
            upper_wick = high_price - open_price
            if body > upper_wick * 2:
                return "하락 반전 캔들"

        # RSI overbought
        rsi = self.calculate_rsi(historical["close"], period=14)
        if not pd.isna(rsi.iloc[-1]) and rsi.iloc[-1] > 75:
            return f"RSI 과매수 ({rsi.iloc[-1]:.1f})"

        # Check for 2 consecutive bearish bars
        last_2 = historical.iloc[-2:]
        bearish = sum(1 for _, bar in last_2.iterrows() if bar["close"] < bar["open"])
        if bearish >= 2:
            return "연속 음봉"

        return None
