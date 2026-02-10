"""Trading strategies module."""

from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal
from src.strategies.intraday.base import IntradayStrategy
from src.strategies.data_driven import get_data_driven_strategies


def get_all_strategies() -> list:
    """Get instances of all available strategies."""
    return get_data_driven_strategies()


__all__ = [
    "BaseStrategy",
    "StrategyConfig",
    "TradeSignal",
    "IntradayStrategy",
    "get_all_strategies",
    "get_data_driven_strategies",
]
