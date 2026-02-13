"""Data-driven intraday strategies designed by OpenAI."""

from src.strategies.data_driven.intraday_strategy_1 import MorningRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_3 import ModifiedRSINeutralATRStrategy


def get_data_driven_strategies() -> list:
    """Get instances of all data-driven strategies."""
    return [
        MorningRSINeutralATRStrategy(),
        ModifiedRSINeutralATRStrategy(),
    ]


__all__ = [
    "MorningRSINeutralATRStrategy",
    "ModifiedRSINeutralATRStrategy",
    "get_data_driven_strategies",
]
