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
    """갭 전략 인스턴스 (prev_day_data 주입 필요). 하위 호환용."""
    return OpeningGapReversalStrategy()


def get_gap_strategy_a() -> OpeningGapReversalStrategy:
    """Gap-A: 거래량급증 1.5x 필터 (전일 양봉 대상).

    59일 시뮬: 74건, WR 58.1%, SL 2.5%, TP 5%.
    """
    return OpeningGapReversalStrategy(
        name="gap_vol_surge",
        stop_loss_pct=0.025,
        take_profit_pct=0.05,
        require_vol_surge=True,
        vol_surge_threshold=1.5,
        require_prev_bearish=False,
    )


def get_gap_strategy_b() -> OpeningGapReversalStrategy:
    """Gap-B: 거래량급증 1.5x + 전일 음봉 (고승률).

    59일 시뮬: 16건, WR 87.5%, SL 3.0%, TP 10%.
    전일 음봉 후 갭다운 = 강한 반등 패턴.
    """
    return OpeningGapReversalStrategy(
        name="gap_bearish_surge",
        stop_loss_pct=0.03,
        take_profit_pct=0.10,
        require_vol_surge=True,
        vol_surge_threshold=1.5,
        require_prev_bearish=True,
    )


__all__ = [
    "MorningRSINeutralATRStrategy",
    "ModifiedRSINeutralATRStrategy",
    "OpeningGapReversalStrategy",
    "get_data_driven_strategies",
    "get_gap_strategy",
    "get_gap_strategy_a",
    "get_gap_strategy_b",
]
