"""Base class for intraday trading strategies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class IntradaySignal:
    """Intraday trading signal."""
    action: str  # "buy" or "sell"
    reason: str
    stop_loss: float = 0.02  # 2% default
    take_profit: float = 0.03  # 3% default
    confidence: float = 1.0


class IntradayStrategy(ABC):
    """Base class for intraday trading strategies."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def check_entry(
        self,
        code: str,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[dict]:
        """
        Check for entry signal.

        Args:
            code: Stock code
            current_bar: Current OHLCV bar
            historical: Historical bars up to current

        Returns:
            Signal dict with 'reason', 'stop_loss', 'take_profit' if entry, else None
        """
        pass

    @abstractmethod
    def check_exit(
        self,
        position,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[str]:
        """
        Check for exit signal.

        Args:
            position: Current position
            current_bar: Current OHLCV bar
            historical: Historical bars up to current

        Returns:
            Exit reason string if exit, else None
        """
        pass

    def calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Calculate VWAP (Volume Weighted Average Price)."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
        return vwap

    def calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI."""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """Calculate EMA."""
        return series.ewm(span=period, adjust=False).mean()

    def calculate_bollinger_bands(
        self, series: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands."""
        middle = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ATR (Average True Range)."""
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)

        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr
