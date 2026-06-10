"""공격/균형 인트라데이 전략 (단타 재설계 2-티어).

균형 티어: VolumeSpikeBreakoutStrategy (거래량 급증 돌파 스캘프, 2~3%)
공격 티어: LimitUpContinuationStrategy (상따), MomentumSurgeStrategy, ConsecutiveSurgeStrategy
"""

from src.strategies.aggressive.base import AggressiveIntradayBase
from src.strategies.aggressive.consecutive_surge import ConsecutiveSurgeStrategy
from src.strategies.aggressive.limitup_continuation import LimitUpContinuationStrategy
from src.strategies.aggressive.momentum_surge import MomentumSurgeStrategy
from src.strategies.aggressive.oscillation_scalp import OscillationScalpStrategy
from src.strategies.aggressive.pullback_vwap import PullbackVWAPStrategy
from src.strategies.aggressive.volume_spike_breakout import VolumeSpikeBreakoutStrategy


def get_balanced_scalp(**kwargs) -> VolumeSpikeBreakoutStrategy:
    """균형 티어 — 거래량 급증 돌파 스캘프."""
    return VolumeSpikeBreakoutStrategy(**kwargs)


def get_pro_pullback(**kwargs) -> PullbackVWAPStrategy:
    """고수 눌림목 + VWAP 기법 — 초반 급등 후 VWAP 위 눌림 반등."""
    return PullbackVWAPStrategy(**kwargs)


def get_oscillation_scalp(**kwargs) -> OscillationScalpStrategy:
    """오실레이션 평균회귀 스캘프 — VWAP 아래 눌림 매수, VWAP 복귀 매도, 반복."""
    return OscillationScalpStrategy(**kwargs)


def get_aggressive_limitup(**kwargs) -> LimitUpContinuationStrategy:
    """공격 티어 — 상한가 접근 연속성(상따)."""
    return LimitUpContinuationStrategy(**kwargs)


def get_aggressive_momentum(**kwargs) -> MomentumSurgeStrategy:
    """공격 티어 — 모멘텀 급등 연속성."""
    return MomentumSurgeStrategy(**kwargs)


__all__ = [
    "AggressiveIntradayBase",
    "VolumeSpikeBreakoutStrategy",
    "LimitUpContinuationStrategy",
    "MomentumSurgeStrategy",
    "ConsecutiveSurgeStrategy",
    "PullbackVWAPStrategy",
    "get_balanced_scalp",
    "get_pro_pullback",
    "get_aggressive_limitup",
    "get_aggressive_momentum",
]
