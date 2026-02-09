"""Script to verify strategy optimization results."""

import json
from datetime import date
from pathlib import Path
from typing import Optional

from src.backtest.engine import BacktestEngine, BacktestConfig
from src.strategies.momentum.volume_breakout import VolumeBreakoutStrategy
from src.strategies.momentum.gap_up import GapUpStrategy
from src.strategies.momentum.top_volume_momentum import TopVolumeMomentumStrategy
from src.strategies.momentum.high_52week import High52WeekBreakoutStrategy
from src.strategies.mean_reversion.rsi_oversold import RSIOversoldStrategy
from src.strategies.mean_reversion.bb_squeeze import BBSqueezeStrategy
from src.strategies.mean_reversion.vwap_reversion import VWAPReversionStrategy
from src.strategies.breakout.ma_golden_cross import MAGoldenCrossStrategy
from src.strategies.breakout.institutional_flow import InstitutionalFlowStrategy
from src.strategies.breakout.sector_rotation import SectorRotationStrategy
from src.database.connection import get_session
from src.database.repositories import StockRepository
from src.utils.logger import get_logger

logger = get_logger(__name__)


BEFORE_OPTIMIZATION = {
    "VolumeBreakout": {"win_rate": 35.8, "total_return": -0.15},
    "RSIOversold": {"win_rate": 43.2, "total_return": -0.08},
    "BBSqueeze": {"win_rate": 35.0, "total_return": -0.12},
    "GapUp": {"win_rate": 37.4, "total_return": -0.10},
    "TopVolumeMomentum": {"win_rate": 30.0, "total_return": -0.18},
    "High52WeekBreakout": {"win_rate": 29.5, "total_return": -0.20},
    "InstitutionalFlow": {"win_rate": 30.1, "total_return": -0.16},
    "SectorRotation": {"win_rate": 30.7, "total_return": -0.14},
    "MAGoldenCross": {"win_rate": 26.0, "total_return": -0.22},
    "VWAPReversion": {"win_rate": 39.5, "total_return": -0.06},
}


def get_optimized_strategies() -> list:
    """Get all optimized strategy instances."""
    return [
        VolumeBreakoutStrategy(),
        RSIOversoldStrategy(),
        BBSqueezeStrategy(),
        GapUpStrategy(),
        TopVolumeMomentumStrategy(),
        High52WeekBreakoutStrategy(),
        InstitutionalFlowStrategy(),
        SectorRotationStrategy(),
        MAGoldenCrossStrategy(),
        VWAPReversionStrategy(),
    ]


def run_verification_backtest(
    codes: Optional[list[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """Run backtest on all optimized strategies."""
    if codes is None:
        with get_session() as session:
            repo = StockRepository(session)
            codes = repo.get_codes()[:50]

    if start_date is None:
        start_date = date(2022, 1, 1)
    if end_date is None:
        end_date = date(2025, 1, 31)

    engine = BacktestEngine(BacktestConfig())
    strategies = get_optimized_strategies()

    results = {}

    for strategy in strategies:
        logger.info(f"Running backtest for {strategy.name}...")
        try:
            metrics = engine.run(strategy, codes, start_date, end_date, save_to_db=True)

            results[strategy.name] = {
                "win_rate": metrics.win_rate,
                "total_return": metrics.total_return,
                "total_trades": metrics.total_trades,
                "sharpe_ratio": metrics.sharpe_ratio,
                "max_drawdown": metrics.max_drawdown,
                "profit_factor": metrics.profit_factor,
            }

            logger.info(
                f"  {strategy.name}: {metrics.win_rate:.1f}% win rate, "
                f"{metrics.total_return:.2%} return"
            )
        except Exception as e:
            logger.error(f"Error running backtest for {strategy.name}: {e}")
            results[strategy.name] = {"error": str(e)}

    return results


def compare_results(after_results: dict) -> dict:
    """Compare before and after optimization results."""
    comparison = {}

    for strategy_name, before in BEFORE_OPTIMIZATION.items():
        after = after_results.get(strategy_name, {})

        if "error" in after:
            comparison[strategy_name] = {
                "error": after["error"],
            }
            continue

        win_rate_before = before["win_rate"]
        win_rate_after = after.get("win_rate", 0)
        win_rate_change = win_rate_after - win_rate_before

        return_before = before["total_return"]
        return_after = after.get("total_return", 0)
        return_change = return_after - return_before

        comparison[strategy_name] = {
            "win_rate": {
                "before": win_rate_before,
                "after": win_rate_after,
                "change": win_rate_change,
                "improved": win_rate_change > 0,
            },
            "total_return": {
                "before": return_before,
                "after": return_after,
                "change": return_change,
                "improved": return_change > 0,
            },
            "total_trades": after.get("total_trades", 0),
            "sharpe_ratio": after.get("sharpe_ratio", 0),
            "max_drawdown": after.get("max_drawdown", 0),
        }

    return comparison


def generate_report(comparison: dict[str, dict]) -> str:
    """Generate a summary report."""
    lines = [
        "=" * 70,
        "Strategy Optimization Verification Report",
        "=" * 70,
        "",
    ]

    improved_win_rate = 0
    improved_return = 0
    total_valid = 0

    for strategy_name, data in comparison.items():
        if "error" in data:
            lines.append(f"{strategy_name}: ERROR - {data['error']}")
            continue

        total_valid += 1
        wr = data["win_rate"]
        tr = data["total_return"]

        if wr["improved"]:
            improved_win_rate += 1
        if tr["improved"]:
            improved_return += 1

        wr_symbol = "+" if wr["change"] > 0 else ""
        tr_symbol = "+" if tr["change"] > 0 else ""

        lines.extend([
            f"\n{strategy_name}:",
            f"  Win Rate:    {wr['before']:.1f}% → {wr['after']:.1f}% ({wr_symbol}{wr['change']:.1f}%)",
            f"  Total Return: {tr['before']:.2%} → {tr['after']:.2%} ({tr_symbol}{tr['change']:.2%})",
            f"  Trades: {data['total_trades']}, Sharpe: {data['sharpe_ratio']:.2f}, MaxDD: {data['max_drawdown']:.2%}",
        ])

    lines.extend([
        "",
        "=" * 70,
        "Summary",
        "=" * 70,
        f"Win Rate Improved: {improved_win_rate}/{total_valid} strategies",
        f"Return Improved: {improved_return}/{total_valid} strategies",
    ])

    return "\n".join(lines)


def main() -> None:
    """Main verification function."""
    logger.info("Starting optimization verification...")

    results = run_verification_backtest()

    comparison = compare_results(results)

    output_path = Path("reports/optimization_comparison.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "date": str(date.today()),
                "before": BEFORE_OPTIMIZATION,
                "after": results,
                "comparison": comparison,
            },
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    report = generate_report(comparison)
    print(report)

    report_path = Path("reports/optimization_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"Results saved to {output_path}")
    logger.info(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
