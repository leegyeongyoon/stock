#!/usr/bin/env python3
"""Run iterative optimization with 5 iterations."""

import json
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.analysis.iterative_optimizer import IterativeOptimizer
from src.utils.logger import get_logger

logger = get_logger(__name__)


def main():
    """Run 5 iterations of optimization for all strategies."""
    # Load current optimization report
    reports_path = project_root / "reports"
    report_file = reports_path / "final_optimization_report.json"

    if not report_file.exists():
        logger.error(f"Report not found: {report_file}")
        return

    with open(report_file, "r", encoding="utf-8") as f:
        initial_report = json.load(f)

    logger.info("=" * 70)
    logger.info("Starting Iterative Optimization (5 iterations)")
    logger.info("=" * 70)

    # Print initial state
    logger.info("\n📊 Initial State:")
    total_initial_return = 0
    for name, data in initial_report.items():
        win_rate = data.get("optimized_win_rate", data.get("original_win_rate", 0))
        ret = data.get("optimized_return", data.get("original_return", 0))
        total_initial_return += ret
        logger.info(f"  {name}: 승률 {win_rate:.1f}%, 수익률 {ret:.2f}%")
    logger.info(f"\n  Total Initial Return: {total_initial_return:.2f}%")

    # Initialize optimizer (using 50 stocks for faster testing)
    optimizer = IterativeOptimizer(sample_size=50)

    # Run optimization for each strategy
    all_progress = {}

    for strategy_name, results in initial_report.items():
        initial_results = {
            "win_rate": results.get("optimized_win_rate", results.get("original_win_rate", 0)),
            "total_return": results.get("optimized_return", results.get("original_return", 0)),
            "total_trades": results.get("total_trades", 0),
        }

        logger.info(f"\n{'#' * 70}")
        logger.info(f"# Optimizing: {strategy_name}")
        logger.info(f"# Initial: win_rate={initial_results['win_rate']:.1f}%, "
                   f"return={initial_results['total_return']:.2f}%")
        logger.info(f"{'#' * 70}")

        try:
            progress = optimizer.optimize_strategy(
                strategy_name, initial_results, num_iterations=5
            )
            all_progress[strategy_name] = progress

            # Save intermediate progress
            optimizer._save_progress(all_progress)

            logger.info(f"\n✅ {strategy_name} completed:")
            logger.info(f"   Initial: {progress.initial_return:.2f}% → Final: {progress.current_return:.2f}%")
            logger.info(f"   Improvement: {progress.current_return - progress.initial_return:+.2f}%")

        except Exception as e:
            logger.error(f"Error optimizing {strategy_name}: {e}")
            continue

    # Generate final report
    logger.info("\n" + "=" * 70)
    logger.info("Generating Final Report")
    logger.info("=" * 70)

    final_report = optimizer.generate_final_report(all_progress)

    # Print summary
    logger.info("\n📊 Final Summary:")
    logger.info("-" * 50)

    total_final_return = 0
    for name, progress in all_progress.items():
        improvement = progress.current_return - progress.initial_return
        total_final_return += progress.current_return
        status = "↑" if improvement > 0 else ("↓" if improvement < 0 else "=")
        logger.info(
            f"  {name}: {progress.initial_return:.2f}% → {progress.current_return:.2f}% "
            f"({improvement:+.2f}% {status})"
        )

    logger.info("-" * 50)
    total_improvement = total_final_return - total_initial_return
    logger.info(f"  Total: {total_initial_return:.2f}% → {total_final_return:.2f}%")
    logger.info(f"  Total Improvement: {total_improvement:+.2f}%")
    logger.info(f"  Strategies Improved: {final_report['summary']['strategies_improved']}/{len(all_progress)}")

    logger.info("\n✅ Iterative optimization completed!")
    logger.info(f"   Reports saved to: {reports_path}")

    return final_report


if __name__ == "__main__":
    main()
