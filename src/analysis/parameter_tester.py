"""Parameter testing system for strategy optimization."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from src.backtest.engine import BacktestEngine, BacktestConfig
from src.config.settings import settings
from src.database.connection import get_session
from src.database.repositories import StockRepository
from src.strategies import get_all_strategies
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ParameterTestResult:
    """Result of a single parameter test."""

    strategy_name: str
    param_name: str
    original_value: Any
    new_value: Any
    original_win_rate: float
    new_win_rate: float
    original_return: float
    new_return: float
    original_trades: int
    new_trades: int
    improved: bool
    improvement_details: str

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "param_name": self.param_name,
            "original_value": self.original_value,
            "new_value": self.new_value,
            "original_win_rate": round(self.original_win_rate, 2),
            "new_win_rate": round(self.new_win_rate, 2),
            "win_rate_change": round(self.new_win_rate - self.original_win_rate, 2),
            "original_return": round(self.original_return, 2),
            "new_return": round(self.new_return, 2),
            "return_change": round(self.new_return - self.original_return, 2),
            "improved": self.improved,
            "improvement_details": self.improvement_details,
        }


class ParameterTester:
    """Test individual parameter changes and verify improvements."""

    def __init__(self, sample_size: Optional[int] = None):
        """
        Initialize tester.

        Args:
            sample_size: Number of stocks to use for quick testing. None = all stocks.
        """
        self.sample_size = sample_size
        self._codes = None
        self._engine = None

    def _get_codes(self) -> list[str]:
        """Get stock codes for testing."""
        if self._codes is None:
            with get_session() as session:
                stock_repo = StockRepository(session)
                self._codes = stock_repo.get_codes()
                if self.sample_size:
                    self._codes = self._codes[: self.sample_size]
        return self._codes

    def _get_engine(self) -> BacktestEngine:
        """Get backtest engine."""
        if self._engine is None:
            config = BacktestConfig(
                initial_capital=settings.initial_capital,
                max_positions=settings.max_positions,
                position_size=settings.max_position_size,
            )
            self._engine = BacktestEngine(config)
        return self._engine

    def _get_dates(self) -> tuple[date, date]:
        """Get backtest dates."""
        start = datetime.strptime(settings.backtest_start_date, "%Y-%m-%d").date()
        end = datetime.strptime(settings.backtest_end_date, "%Y-%m-%d").date()
        return start, end

    def run_single_strategy_backtest(self, strategy) -> dict:
        """Run backtest for a single strategy and return metrics."""
        engine = self._get_engine()
        codes = self._get_codes()
        start_date, end_date = self._get_dates()

        metrics = engine.run(strategy, codes, start_date, end_date)

        return {
            "win_rate": metrics.win_rate * 100,
            "total_return": metrics.total_return * 100,
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "avg_win": metrics.avg_win * 100,
            "avg_loss": metrics.avg_loss * 100,
            "profit_factor": metrics.profit_factor,
            "max_drawdown": metrics.max_drawdown * 100,
            "sharpe_ratio": metrics.sharpe_ratio,
        }

    def test_parameter_change(
        self,
        strategy_class,
        param_name: str,
        original_value: Any,
        new_value: Any,
        other_params: dict = None,
    ) -> ParameterTestResult:
        """
        Test a single parameter change.

        Args:
            strategy_class: The strategy class to test
            param_name: Name of the parameter to change
            original_value: Current value
            new_value: New value to test
            other_params: Other parameters to keep constant
        """
        other_params = other_params or {}

        # Test with original value
        logger.info(f"Testing {strategy_class.__name__} with {param_name}={original_value}")
        original_params = {**other_params, param_name: original_value}
        original_strategy = strategy_class(**original_params)
        original_results = self.run_single_strategy_backtest(original_strategy)

        # Test with new value
        logger.info(f"Testing {strategy_class.__name__} with {param_name}={new_value}")
        new_params = {**other_params, param_name: new_value}
        new_strategy = strategy_class(**new_params)
        new_results = self.run_single_strategy_backtest(new_strategy)

        # Determine if improved
        # Improvement criteria: better win rate AND better or equal return
        # OR significantly better return (>2%) with similar win rate
        win_rate_improved = new_results["win_rate"] > original_results["win_rate"]
        return_improved = new_results["total_return"] > original_results["total_return"]
        significant_return_gain = (
            new_results["total_return"] - original_results["total_return"] > 2.0
        )
        win_rate_similar = abs(
            new_results["win_rate"] - original_results["win_rate"]
        ) < 3.0

        improved = (win_rate_improved and return_improved) or (
            significant_return_gain and win_rate_similar
        )

        # Build improvement details
        details = []
        if win_rate_improved:
            details.append(
                f"승률 +{new_results['win_rate'] - original_results['win_rate']:.1f}%"
            )
        elif new_results["win_rate"] < original_results["win_rate"]:
            details.append(
                f"승률 {new_results['win_rate'] - original_results['win_rate']:.1f}%"
            )

        if return_improved:
            details.append(
                f"수익률 +{new_results['total_return'] - original_results['total_return']:.2f}%"
            )
        elif new_results["total_return"] < original_results["total_return"]:
            details.append(
                f"수익률 {new_results['total_return'] - original_results['total_return']:.2f}%"
            )

        return ParameterTestResult(
            strategy_name=strategy_class.__name__.replace("Strategy", ""),
            param_name=param_name,
            original_value=original_value,
            new_value=new_value,
            original_win_rate=original_results["win_rate"],
            new_win_rate=new_results["win_rate"],
            original_return=original_results["total_return"],
            new_return=new_results["total_return"],
            original_trades=original_results["total_trades"],
            new_trades=new_results["total_trades"],
            improved=improved,
            improvement_details=", ".join(details) if details else "변화 없음",
        )

    def test_multiple_parameters(
        self,
        strategy_class,
        parameter_changes: dict[str, dict],
        base_params: dict = None,
    ) -> list[ParameterTestResult]:
        """
        Test multiple parameter changes one by one.

        Args:
            strategy_class: Strategy class to test
            parameter_changes: Dict of {param_name: {"current": x, "recommended": y}}
            base_params: Base parameters to use
        """
        base_params = base_params or {}
        results = []

        for param_name, change in parameter_changes.items():
            current = change.get("current")
            recommended = change.get("recommended")

            if current is None or recommended is None:
                continue

            # Convert string numbers to proper types
            if isinstance(current, str):
                try:
                    current = float(current)
                except ValueError:
                    pass
            if isinstance(recommended, str):
                try:
                    recommended = float(recommended)
                except ValueError:
                    pass

            result = self.test_parameter_change(
                strategy_class,
                param_name,
                current,
                recommended,
                base_params,
            )
            results.append(result)

            logger.info(
                f"{param_name}: {current} -> {recommended} | "
                f"{'✅ 개선' if result.improved else '❌ 악화'} | "
                f"{result.improvement_details}"
            )

        return results


def get_strategy_class(strategy_name: str):
    """Get strategy class by name."""
    from src.strategies.momentum.volume_breakout import VolumeBreakoutStrategy
    from src.strategies.momentum.gap_up import GapUpStrategy
    from src.strategies.momentum.top_volume_momentum import TopVolumeMomentumStrategy
    from src.strategies.momentum.high_52week import High52WeekBreakoutStrategy
    from src.strategies.mean_reversion.vwap_reversion import VWAPReversionStrategy
    from src.strategies.mean_reversion.rsi_oversold import RSIOversoldStrategy
    from src.strategies.mean_reversion.bb_squeeze import BBSqueezeStrategy
    from src.strategies.breakout.ma_golden_cross import MAGoldenCrossStrategy
    from src.strategies.breakout.institutional_flow import InstitutionalFlowStrategy
    from src.strategies.breakout.sector_rotation import SectorRotationStrategy

    mapping = {
        "VolumeBreakout": VolumeBreakoutStrategy,
        "GapUp": GapUpStrategy,
        "TopVolumeMomentum": TopVolumeMomentumStrategy,
        "High52WeekBreakout": High52WeekBreakoutStrategy,
        "VWAPReversion": VWAPReversionStrategy,
        "RSIOversold": RSIOversoldStrategy,
        "BBSqueeze": BBSqueezeStrategy,
        "MAGoldenCross": MAGoldenCrossStrategy,
        "InstitutionalFlow": InstitutionalFlowStrategy,
        "SectorRotation": SectorRotationStrategy,
    }

    return mapping.get(strategy_name)
