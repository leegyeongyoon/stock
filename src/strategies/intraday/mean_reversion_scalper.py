"""Mean Reversion Scalper Strategy - Trades Bollinger Band extremes."""

from typing import Optional

import pandas as pd
import numpy as np

from src.strategies.intraday.base import IntradayStrategy


class MeanReversionScalperStrategy(IntradayStrategy):
    """
    Mean Reversion Scalper Strategy.

    Uses Bollinger Bands to identify oversold conditions:
    - Enter when price touches or breaks lower band
    - Exit when price reverts to middle band or upper
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        min_squeeze: float = 0.02,  # Minimum band width
        rsi_oversold: int = 30,
        volume_min_ratio: float = 0.8,  # Minimum volume for entry
        stop_loss: float = 0.02,  # 2%
        take_profit: float = 0.025,  # 2.5%
    ):
        super().__init__("Mean Reversion Scalper")
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.min_squeeze = min_squeeze
        self.rsi_oversold = rsi_oversold
        self.volume_min_ratio = volume_min_ratio
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def check_entry(
        self,
        code: str,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[dict]:
        """Check for mean reversion entry."""
        if len(historical) < self.bb_period + 5:
            return None

        # Calculate Bollinger Bands
        upper, middle, lower = self.calculate_bollinger_bands(
            historical["close"], self.bb_period, self.bb_std
        )

        current_upper = upper.iloc[-1]
        current_middle = middle.iloc[-1]
        current_lower = lower.iloc[-1]
        current_price = float(current_bar["close"])

        # Check band width (avoid too tight bands)
        band_width = (current_upper - current_lower) / current_middle
        if band_width < self.min_squeeze:
            return None

        # Check if price is at or below lower band
        if current_price > current_lower:
            return None

        # RSI confirmation
        rsi = self.calculate_rsi(historical["close"], period=14)
        current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

        if current_rsi > self.rsi_oversold:
            return None

        # Volume check
        avg_volume = historical["volume"].rolling(20).mean().iloc[-1]
        current_volume = float(current_bar["volume"])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        if volume_ratio < self.volume_min_ratio:
            return None

        # Look for reversal candle (hammer or doji)
        open_price = float(current_bar["open"])
        high_price = float(current_bar["high"])
        low_price = float(current_bar["low"])

        body = abs(current_price - open_price)
        lower_wick = min(current_price, open_price) - low_price
        upper_wick = high_price - max(current_price, open_price)

        # Hammer pattern: lower wick > 2x body
        is_hammer = lower_wick > body * 2 and upper_wick < body

        # Bullish close
        is_bullish = current_price > open_price

        if not (is_hammer or is_bullish):
            return None

        return {
            "reason": f"BB 하단 터치: RSI {current_rsi:.1f}, 밴드폭 {band_width*100:.1f}%",
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
        if len(historical) < self.bb_period:
            return None

        # Calculate Bollinger Bands
        upper, middle, lower = self.calculate_bollinger_bands(
            historical["close"], self.bb_period, self.bb_std
        )

        current_middle = middle.iloc[-1]
        current_price = float(current_bar["close"])

        # Exit at middle band (take partial or full profit)
        if current_price >= current_middle:
            return "BB 중간선 도달"

        # Check RSI overbought
        rsi = self.calculate_rsi(historical["close"], period=14)
        if not pd.isna(rsi.iloc[-1]) and rsi.iloc[-1] > 70:
            return f"RSI 과매수 ({rsi.iloc[-1]:.1f})"

        # Check for bearish reversal pattern
        last_3_bars = historical.iloc[-3:]
        if len(last_3_bars) >= 3:
            all_bearish = all(
                bar["close"] < bar["open"]
                for _, bar in last_3_bars.iterrows()
            )
            if all_bearish:
                return "연속 3음봉"

        return None
