"""Trading strategies module."""

from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal

# Momentum strategies
from src.strategies.momentum.volume_breakout import VolumeBreakoutStrategy
from src.strategies.momentum.gap_up import GapUpStrategy
from src.strategies.momentum.top_volume_momentum import TopVolumeMomentumStrategy
from src.strategies.momentum.high_52week import High52WeekBreakoutStrategy

# Mean reversion strategies
from src.strategies.mean_reversion.vwap_reversion import VWAPReversionStrategy
from src.strategies.mean_reversion.rsi_oversold import RSIOversoldStrategy
from src.strategies.mean_reversion.bb_squeeze import BBSqueezeStrategy

# Breakout strategies
from src.strategies.breakout.ma_golden_cross import MAGoldenCrossStrategy
from src.strategies.breakout.institutional_flow import InstitutionalFlowStrategy
from src.strategies.breakout.sector_rotation import SectorRotationStrategy


def get_all_strategies() -> list[BaseStrategy]:
    """Get instances of all available strategies with default parameters."""
    return [
        VolumeBreakoutStrategy(),
        GapUpStrategy(),
        VWAPReversionStrategy(),
        RSIOversoldStrategy(),
        MAGoldenCrossStrategy(),
        BBSqueezeStrategy(),
        TopVolumeMomentumStrategy(),
        High52WeekBreakoutStrategy(),
        InstitutionalFlowStrategy(),
        SectorRotationStrategy(),
    ]


__all__ = [
    "BaseStrategy",
    "StrategyConfig",
    "TradeSignal",
    "get_all_strategies",
    # Momentum
    "VolumeBreakoutStrategy",
    "GapUpStrategy",
    "TopVolumeMomentumStrategy",
    "High52WeekBreakoutStrategy",
    # Mean reversion
    "VWAPReversionStrategy",
    "RSIOversoldStrategy",
    "BBSqueezeStrategy",
    # Breakout
    "MAGoldenCrossStrategy",
    "InstitutionalFlowStrategy",
    "SectorRotationStrategy",
]
