"""VWAP Scalper Strategy - Trades price deviations from VWAP."""

from typing import Optional

import pandas as pd
import numpy as np

from src.strategies.intraday.base import IntradayStrategy


class VWAPScalperStrategy(IntradayStrategy):
    """
    VWAP Scalper Strategy.

    Enters when price deviates significantly from VWAP and shows signs of reverting.
    - Buy when price is below VWAP and showing upward momentum
    - Sell when price is above VWAP and showing downward momentum
    """

    def __init__(
        self,
        deviation_threshold: float = 0.015,  # 1.5% deviation from VWAP
        min_volume_ratio: float = 1.2,  # Current volume vs average
        rsi_oversold: int = 35,
        rsi_overbought: int = 65,
        stop_loss: float = 0.015,  # 1.5%
        take_profit: float = 0.02,  # 2%
    ):
        super().__init__("VWAP Scalper")
        self.deviation_threshold = deviation_threshold
        self.min_volume_ratio = min_volume_ratio
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def check_entry(
        self,
        code: str,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[dict]:
        """Check for VWAP scalping entry."""
        if len(historical) < 20:
            return None

        # Calculate VWAP
        vwap = self.calculate_vwap(historical)
        current_vwap = vwap.iloc[-1]
        current_price = float(current_bar["close"])

        # Calculate deviation from VWAP
        deviation = (current_price - current_vwap) / current_vwap

        # Calculate volume ratio
        avg_volume = historical["volume"].rolling(20).mean().iloc[-1]
        current_volume = float(current_bar["volume"])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        # Calculate RSI
        rsi = self.calculate_rsi(historical["close"], period=14)
        current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

        # Check for oversold + below VWAP (long entry)
        if (
            deviation < -self.deviation_threshold
            and current_rsi < self.rsi_oversold
            and volume_ratio > self.min_volume_ratio
        ):
            # Check for reversal candle (close > open)
            if current_price > float(current_bar["open"]):
                return {
                    "reason": f"VWAP 이탈 매수: {deviation*100:.2f}% 하방, RSI {current_rsi:.1f}",
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
        if len(historical) < 5:
            return None

        # Calculate VWAP
        vwap = self.calculate_vwap(historical)
        current_vwap = vwap.iloc[-1]
        current_price = float(current_bar["close"])

        # Exit if price crosses above VWAP
        if current_price > current_vwap:
            return "VWAP 상향 돌파"

        # Calculate RSI for overbought exit
        rsi = self.calculate_rsi(historical["close"], period=14)
        if not pd.isna(rsi.iloc[-1]) and rsi.iloc[-1] > self.rsi_overbought:
            return f"RSI 과매수 ({rsi.iloc[-1]:.1f})"

        return None
