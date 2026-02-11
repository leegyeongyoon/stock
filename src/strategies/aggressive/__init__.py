"""Aggressive short-term trading strategies."""

from src.strategies.aggressive.momentum_surge import MomentumSurgeStrategy
from src.strategies.aggressive.volume_spike_breakout import VolumeSpikeBreakoutStrategy
from src.strategies.aggressive.consecutive_surge import ConsecutiveSurgeStrategy

__all__ = [
    "MomentumSurgeStrategy",
    "VolumeSpikeBreakoutStrategy",
    "ConsecutiveSurgeStrategy",
]
