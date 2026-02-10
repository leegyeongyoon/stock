"""Data-driven intraday strategies designed by OpenAI."""

from src.strategies.data_driven.intraday_strategy_1 import MorningRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_2 import LunchRSINeutralATRVolumeStrategy
from src.strategies.data_driven.intraday_strategy_3 import ModifiedRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_4 import AfternoonRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_6 import AfternoonRSINeutralATRVolumeStrategy
from src.strategies.data_driven.intraday_strategy_8 import MorningWideRSINeutralATRStrategy


def get_data_driven_strategies() -> list:
    """Get instances of all data-driven strategies."""
    return [
        MorningRSINeutralATRStrategy(),
        LunchRSINeutralATRVolumeStrategy(),
        ModifiedRSINeutralATRStrategy(),
        AfternoonRSINeutralATRStrategy(),
        AfternoonRSINeutralATRVolumeStrategy(),
        MorningWideRSINeutralATRStrategy(),
    ]


__all__ = [
    "MorningRSINeutralATRStrategy",
    "LunchRSINeutralATRVolumeStrategy",
    "ModifiedRSINeutralATRStrategy",
    "AfternoonRSINeutralATRStrategy",
    "AfternoonRSINeutralATRVolumeStrategy",
    "MorningWideRSINeutralATRStrategy",
    "get_data_driven_strategies",
]
