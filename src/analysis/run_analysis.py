"""Script to run AI analysis on all strategies."""

import json
import os
from datetime import date
from pathlib import Path

from src.analysis.openai_analyzer import OpenAIAnalyzer, TradeAnalysisData
from src.analysis.trade_collector import TradeCollector
from src.config.settings import settings
from src.database.connection import get_session
from src.database.repositories import BacktestRepository, TradeRepository
from src.utils.logger import get_logger

logger = get_logger(__name__)

STRATEGIES = [
    "VolumeBreakout",
    "RSIOversold",
    "BBSqueeze",
    "GapUp",
    "TopVolumeMomentum",
    "High52WeekBreakout",
    "InstitutionalFlow",
    "SectorRotation",
    "MAGoldenCross",
    "VWAPReversion",
]


def collect_strategy_data() -> list[TradeAnalysisData]:
    """Collect trade data for all strategies from database."""
    collector = TradeCollector()
    strategies_data = []

    with get_session() as session:
        backtest_repo = BacktestRepository(session)
        trade_repo = TradeRepository(session)

        for strategy_name in STRATEGIES:
            logger.info(f"Collecting data for {strategy_name}...")

            latest = backtest_repo.get_latest(strategy_name)
            if not latest:
                logger.warning(f"No backtest found for {strategy_name}")
                continue

            trades = trade_repo.get_by_backtest(latest.id)
            if not trades:
                logger.warning(f"No trades found for {strategy_name}")
                continue

            trade_dicts = []
            for trade in trades:
                holding_days = (trade.exit_date - trade.entry_date).days
                trade_dicts.append({
                    "code": trade.code,
                    "entry_date": trade.entry_date,
                    "exit_date": trade.exit_date,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "quantity": trade.quantity,
                    "pnl": trade.pnl,
                    "pnl_rate": trade.pnl_rate,
                    "holding_days": holding_days,
                    "entry_reason": trade.entry_reason,
                    "exit_reason": trade.exit_reason,
                })

            data = collector.collect_from_trades(
                strategy_name=strategy_name,
                trades=trade_dicts,
                strategy_params=latest.config.get("params", {}) if latest.config else {},
                total_return=latest.total_return,
            )
            strategies_data.append(data)

            logger.info(
                f"  {strategy_name}: {data.total_trades} trades, "
                f"{data.win_rate:.1f}% win rate"
            )

    return strategies_data


def run_ai_analysis(
    strategies_data: list[TradeAnalysisData],
    api_key: str,
) -> dict:
    """Run AI analysis on all strategies."""
    analyzer = OpenAIAnalyzer(api_key=api_key)
    analyses = analyzer.analyze_all_strategies(strategies_data)

    results = {
        "analysis_date": str(date.today()),
        "strategies": {},
    }

    for analysis in analyses:
        results["strategies"][analysis.strategy_name] = analysis.to_dict()
        logger.info(f"Analyzed {analysis.strategy_name}: confidence {analysis.confidence_score:.2f}")

    summary = analyzer.get_optimization_summary(analyses)
    results["summary"] = summary

    return results


def save_results(results: dict, output_path: str) -> None:
    """Save analysis results to JSON file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"Results saved to {output_path}")


def main() -> None:
    """Main function to run analysis."""
    api_key = os.environ.get("OPENAI_API_KEY") or settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    logger.info("Starting AI analysis...")

    strategies_data = collect_strategy_data()
    if not strategies_data:
        logger.error("No strategy data collected")
        return

    results = run_ai_analysis(strategies_data, api_key)

    output_path = f"reports/ai_analysis_report_{date.today().strftime('%Y%m%d')}.json"
    save_results(results, output_path)

    print("\n" + "=" * 60)
    print("AI Analysis Summary")
    print("=" * 60)

    for strategy_name, data in results["strategies"].items():
        print(f"\n{strategy_name}:")
        print(f"  Confidence: {data['confidence_score']:.2f}")
        print(f"  Top Issues: {', '.join(data['loss_reasons'][:2])}")
        if data['parameter_recommendations']:
            print(f"  Key Parameters to Adjust: {list(data['parameter_recommendations'].keys())[:3]}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
