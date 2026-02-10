"""Opening Range Breakout Strategy - Trades breakouts from morning range."""

from datetime import time
from typing import Optional

import pandas as pd
import numpy as np

from src.strategies.intraday.base import IntradayStrategy


class OpeningRangeBreakoutStrategy(IntradayStrategy):
    """
    Opening Range Breakout (ORB) Strategy.

    1. Define the opening range (first 30 minutes of trading)
    2. Wait for a breakout above/below the range
    3. Enter with volume confirmation
    """

    def __init__(
        self,
        opening_range_minutes: int = 30,
        min_range_pct: float = 0.005,  # Minimum 0.5% range
        max_range_pct: float = 0.03,  # Maximum 3% range
        breakout_buffer: float = 0.001,  # 0.1% above/below range
        volume_surge: float = 1.5,  # Volume surge required
        stop_loss: float = 0.02,  # 2%
        take_profit: float = 0.03,  # 3%
    ):
        super().__init__("Opening Range Breakout")
        self.opening_range_minutes = opening_range_minutes
        self.min_range_pct = min_range_pct
        self.max_range_pct = max_range_pct
        self.breakout_buffer = breakout_buffer
        self.volume_surge = volume_surge
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def _get_opening_range(
        self, historical: pd.DataFrame
    ) -> Optional[tuple[float, float]]:
        """Get the opening range high and low."""
        # Get today's data
        if len(historical) < 6:  # Need at least 30 min of 5-min bars
            return None

        today = historical.index[-1].date()
        today_data = historical[historical.index.date == today]

        if len(today_data) < 6:
            return None

        # First 30 minutes (6 bars of 5-min data)
        opening_bars = today_data.iloc[:6]
        opening_high = opening_bars["high"].max()
        opening_low = opening_bars["low"].min()

        return opening_high, opening_low

    def check_entry(
        self,
        code: str,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[dict]:
        """Check for ORB entry."""
        opening_range = self._get_opening_range(historical)
        if opening_range is None:
            return None

        opening_high, opening_low = opening_range
        current_price = float(current_bar["close"])

        # Calculate range percentage
        range_pct = (opening_high - opening_low) / opening_low

        # Skip if range too narrow or too wide
        if range_pct < self.min_range_pct or range_pct > self.max_range_pct:
            return None

        # Check if we're past the opening range period
        current_time = current_bar.name.time() if hasattr(current_bar.name, 'time') else None
        if current_time and current_time < time(9, 30):
            return None  # Still in opening range period

        # Volume confirmation
        avg_volume = historical["volume"].rolling(20).mean().iloc[-1]
        current_volume = float(current_bar["volume"])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        if volume_ratio < self.volume_surge:
            return None

        # Check for breakout above opening range high
        breakout_level = opening_high * (1 + self.breakout_buffer)
        if current_price > breakout_level:
            # Confirm with strong close
            if current_price > float(current_bar["open"]):
                return {
                    "reason": f"ORB 상방 돌파: {current_price:,.0f} > {opening_high:,.0f}",
                    "stop_loss": self.stop_loss,
                    "take_profit": self.take_profit,
                }

        return None

    def check_exit(
        self,
        position,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[str]:
        """Check for exit signal."""
        current_price = float(current_bar["close"])

        # Get opening range
        opening_range = self._get_opening_range(historical)
        if opening_range is None:
            return None

        opening_high, opening_low = opening_range
        midpoint = (opening_high + opening_low) / 2

        # Exit if price falls back into the range
        if current_price < opening_high:
            return "레인지 내 복귀"

        # Exit if strong reversal candle
        if float(current_bar["close"]) < float(current_bar["open"]):
            candle_range = float(current_bar["open"]) - float(current_bar["close"])
            bar_range = float(current_bar["high"]) - float(current_bar["low"])
            if bar_range > 0 and candle_range / bar_range > 0.7:
                return "강한 하락 캔들"

        return None
