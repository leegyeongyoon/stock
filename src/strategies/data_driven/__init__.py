"""Data-driven intraday strategies designed by OpenAI."""

from src.strategies.data_driven.intraday_strategy_1 import MorningRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_3 import ModifiedRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_gap import OpeningGapReversalStrategy


def get_data_driven_strategies() -> list:
    """Get instances of all data-driven strategies (prev_day_data 불필요한 것만)."""
    return [
        MorningRSINeutralATRStrategy(),
        ModifiedRSINeutralATRStrategy(),
    ]


def get_gap_strategy() -> OpeningGapReversalStrategy:
    """갭 전략 인스턴스 (prev_day_data 주입 필요)."""
    return OpeningGapReversalStrategy()


__all__ = [
    "MorningRSINeutralATRStrategy",
    "ModifiedRSINeutralATRStrategy",
    "OpeningGapReversalStrategy",
    "get_data_driven_strategies",
    "get_gap_strategy",
]
