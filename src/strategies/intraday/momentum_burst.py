"""Momentum Burst Strategy - Catches sudden momentum surges."""

from typing import Optional

import pandas as pd
import numpy as np

from src.strategies.intraday.base import IntradayStrategy


class MomentumBurstStrategy(IntradayStrategy):
    """
    Momentum Burst Strategy.

    Detects sudden price momentum with volume confirmation:
    - Price moves up significantly in short time
    - Volume spikes above average
    - RSI shows strong momentum but not extreme
    """

    def __init__(
        self,
        price_surge_pct: float = 0.015,  # 1.5% price surge
        lookback_bars: int = 3,  # Look at last 3 bars
        volume_surge: float = 2.0,  # 2x average volume
        rsi_min: int = 40,  # Not too oversold
        rsi_max: int = 70,  # Not too overbought
        stop_loss: float = 0.015,  # 1.5%
        take_profit: float = 0.025,  # 2.5%
    ):
        super().__init__("Momentum Burst")
        self.price_surge_pct = price_surge_pct
        self.lookback_bars = lookback_bars
        self.volume_surge = volume_surge
        self.rsi_min = rsi_min
        self.rsi_max = rsi_max
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def check_entry(
        self,
        code: str,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[dict]:
        """Check for momentum burst entry."""
        if len(historical) < 20:
            return None

        # Get recent bars
        recent_bars = historical.iloc[-self.lookback_bars:]

        # Calculate price change over lookback period
        start_price = recent_bars.iloc[0]["open"]
        current_price = float(current_bar["close"])
        price_change = (current_price - start_price) / start_price

        # Check for price surge
        if price_change < self.price_surge_pct:
            return None

        # Volume surge check
        avg_volume = historical["volume"].iloc[:-self.lookback_bars].rolling(20).mean().iloc[-1]
        recent_volume = recent_bars["volume"].sum()
        expected_volume = avg_volume * self.lookback_bars
        volume_ratio = recent_volume / expected_volume if expected_volume > 0 else 0

        if volume_ratio < self.volume_surge:
            return None

        # RSI check
        rsi = self.calculate_rsi(historical["close"], period=14)
        current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

        if current_rsi < self.rsi_min or current_rsi > self.rsi_max:
            return None

        # Check all recent bars are bullish
        bullish_count = sum(
            1 for _, bar in recent_bars.iterrows()
            if bar["close"] > bar["open"]
        )
        if bullish_count < self.lookback_bars - 1:
            return None

        return {
            "reason": f"모멘텀 버스트: {price_change*100:.2f}% 상승, 거래량 {volume_ratio:.1f}x",
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

        current_price = float(current_bar["close"])

        # Check for momentum loss (2 consecutive bearish bars)
        last_2_bars = historical.iloc[-2:]
        bearish_count = sum(
            1 for _, bar in last_2_bars.iterrows()
            if bar["close"] < bar["open"]
        )

        if bearish_count >= 2:
            return "모멘텀 약화 (연속 음봉)"

        # RSI overbought exit
        rsi = self.calculate_rsi(historical["close"], period=14)
        if not pd.isna(rsi.iloc[-1]) and rsi.iloc[-1] > 75:
            return f"RSI 과매수 ({rsi.iloc[-1]:.1f})"

        # Volume dry up
        avg_volume = historical["volume"].rolling(20).mean().iloc[-1]
        current_volume = float(current_bar["volume"])
        if avg_volume > 0 and current_volume / avg_volume < 0.5:
            return "거래량 감소"

        return None
