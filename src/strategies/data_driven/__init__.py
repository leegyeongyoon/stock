"""Data-driven intraday strategies designed by OpenAI."""

from src.strategies.data_driven.intraday_strategy_1 import MorningRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_3 import ModifiedRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_gap import OpeningGapReversalStrategy


def get_data_driven_strategies() -> list:
    """Get instances of all data-driven strategies (prev_day_data 불필요한 것만).

    2026-02-27 최적화 결과:
    - 전략1(morning_rsi WR41.7%), 전략3(modified_rsi WR53.4%) → 실전 WR 25%로 제거
    - 갭반전(opening_gap_reversal WR 62.1%) → DDStrategyRunner에서 단독 실행
    """
    return []


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
