"""Base class for intraday trading strategies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class IntradaySignal:
    """Intraday trading signal."""
    action: str  # "buy" or "sell"
    reason: str
    stop_loss: float = 0.02  # 2% default
    take_profit: float = 0.03  # 3% default
    confidence: float = 1.0


# --- Numpy indicator helpers (for fast pre-computation) ---

def rolling_mean_np(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling mean using cumsum. O(n) complexity."""
    n = len(arr)
    result = np.full(n, np.nan)
    if n < window:
        return result
    cs = np.cumsum(arr)
    result[window - 1] = cs[window - 1] / window
    if n > window:
        result[window:] = (cs[window:] - cs[:-window]) / window
    return result


def rsi_np(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI using numpy. Matches pandas rolling mean implementation."""
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi

    deltas = np.diff(closes)
    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)

    for i in range(period - 1, len(deltas)):
        avg_gain = np.mean(gains[i - period + 1:i + 1])
        avg_loss = np.mean(losses[i - period + 1:i + 1])

        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def vwap_np(
    highs: np.ndarray, lows: np.ndarray,
    closes: np.ndarray, volumes: np.ndarray,
) -> np.ndarray:
    """VWAP using numpy. Cumulative from start."""
    typical_price = (highs + lows + closes) / 3.0
    cum_vol = np.cumsum(volumes)
    cum_tp_vol = np.cumsum(typical_price * volumes)
    return np.divide(
        cum_tp_vol, cum_vol,
        out=np.zeros_like(cum_vol),
        where=cum_vol != 0,
    )


def bollinger_bands_np(
    closes: np.ndarray, period: int = 20, std_dev: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands using numpy. Returns (upper, middle, lower)."""
    n = len(closes)
    upper = np.full(n, np.nan)
    middle = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = np.mean(window)
        s = np.std(window, ddof=1)
        middle[i] = m
        upper[i] = m + std_dev * s
        lower[i] = m - std_dev * s

    return upper, middle, lower


class IntradayStrategy(ABC):
    """Base class for intraday trading strategies."""

    def __init__(self, name: str):
        self.name = name

    # --- Original slow-path methods (backward compatible) ---

    @abstractmethod
    def check_entry(
        self,
        code: str,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[dict]:
        pass

    @abstractmethod
    def check_exit(
        self,
        position,
        current_bar: pd.Series,
        historical: pd.DataFrame,
    ) -> Optional[str]:
        pass

    def calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        return (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()

    def calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def calculate_bollinger_bands(
        self, series: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        middle = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    # --- Fast-path methods (for V2 engine) ---

    def precompute_day(self, day_df: pd.DataFrame) -> dict:
        """Pre-compute indicators for a full day. Override to add more."""
        closes = day_df["close"].values.astype(np.float64)
        opens = day_df["open"].values.astype(np.float64)
        highs = day_df["high"].values.astype(np.float64)
        lows = day_df["low"].values.astype(np.float64)
        volumes = day_df["volume"].values.astype(np.float64)

        return {
            "close": closes,
            "open": opens,
            "high": highs,
            "low": lows,
            "volume": volumes,
            "timestamps": day_df.index.tolist(),
            "n_bars": len(day_df),
            "rsi_14": rsi_np(closes, 14),
            "vwap": vwap_np(highs, lows, closes, volumes),
            "vol_avg_20": rolling_mean_np(volumes, 20),
        }

    def check_entry_fast(
        self, code: str, bar_idx: int, indicators: dict,
    ) -> Optional[dict]:
        """Fast entry check using pre-computed indicators. Override in subclass."""
        return None

    def check_exit_fast(
        self, position, bar_idx: int, indicators: dict,
    ) -> Optional[str]:
        """Fast exit check using pre-computed indicators. Override in subclass."""
        return None
