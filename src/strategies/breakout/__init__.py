"""Breakout and trend-following strategies."""

from src.strategies.breakout.ma_golden_cross import MAGoldenCrossStrategy
from src.strategies.breakout.institutional_flow import InstitutionalFlowStrategy
from src.strategies.breakout.sector_rotation import SectorRotationStrategy

__all__ = [
    "MAGoldenCrossStrategy",
    "InstitutionalFlowStrategy",
    "SectorRotationStrategy",
]
