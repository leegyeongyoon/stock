"""Application constants."""

from enum import Enum
from datetime import time


class Market(str, Enum):
    """Stock market types."""

    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class SignalType(str, Enum):
    """Trading signal types."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderType(str, Enum):
    """Order types."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class PositionStatus(str, Enum):
    """Position status."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


# Trading hours (KST)
TRADING_START_TIME = time(9, 0)
TRADING_END_TIME = time(15, 30)
PRE_MARKET_START = time(8, 30)
POST_MARKET_END = time(18, 0)

# Technical indicator defaults
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_OVERSOLD = 30
DEFAULT_RSI_OVERBOUGHT = 70

DEFAULT_BB_PERIOD = 20
DEFAULT_BB_STD = 2.0

DEFAULT_MA_SHORT = 5
DEFAULT_MA_LONG = 20

DEFAULT_VOLUME_MA_PERIOD = 20
DEFAULT_VOLUME_SURGE_RATIO = 3.0

# Risk management
DEFAULT_STOP_LOSS = 0.02  # 2%
DEFAULT_TAKE_PROFIT = 0.03  # 3%
MAX_SLIPPAGE = 0.005  # 0.5%

# Fee and tax
COMMISSION_RATE = 0.00015  # 0.015%
TAX_RATE = 0.0023  # 0.23% (매도 시)
