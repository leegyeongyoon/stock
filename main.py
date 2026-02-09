"""Main entry point for the stock trading system."""

import argparse
from datetime import date, datetime, timedelta

from src.api.data_fetcher import DataFetcher
from src.backtest.engine import BacktestEngine, BacktestConfig
from src.backtest.reporter import BacktestReporter
from src.config.settings import settings
from src.database.connection import init_db, get_session
from src.database.repositories import StockRepository
from src.strategies import get_all_strategies
from src.utils.logger import setup_logger, get_logger


def init_database():
    """Initialize database tables."""
    print("Initializing database...")
    init_db()
    print("Database initialized successfully.")


def fetch_data(start_date: str, end_date: str, market: str = None):
    """Fetch stock data from KRX."""
    setup_logger()
    logger = get_logger(__name__)

    fetcher = DataFetcher(delay=0.3)

    # Parse dates
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    logger.info(f"Fetching data from {start} to {end}")

    # Fetch stocks first
    fetcher.fetch_and_save_stocks()

    # Then fetch OHLCV data
    fetcher.fetch_and_save_ohlcv(
        start_date=start,
        end_date=end,
        market=market,
    )

    logger.info("Data fetching completed.")


def run_backtest(
    strategy_name: str = None,
    start_date: str = None,
    end_date: str = None,
    market: str = None,
    save_to_db: bool = False,
):
    """Run backtest for strategies."""
    setup_logger()
    logger = get_logger(__name__)

    # Parse dates
    end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else end - timedelta(days=365)

    # Get stock codes
    with get_session() as session:
        stock_repo = StockRepository(session)
        codes = stock_repo.get_codes(market=market)

    if not codes:
        logger.error("No stocks found in database. Run 'fetch' first.")
        return

    logger.info(f"Running backtest on {len(codes)} stocks from {start} to {end}")

    # Get strategies
    all_strategies = get_all_strategies()

    if strategy_name:
        strategies = [s for s in all_strategies if s.name.lower() == strategy_name.lower()]
        if not strategies:
            available = ", ".join(s.name for s in all_strategies)
            logger.error(f"Strategy '{strategy_name}' not found. Available: {available}")
            return
    else:
        strategies = all_strategies

    # Run backtest
    config = BacktestConfig(
        initial_capital=settings.initial_capital,
        max_positions=settings.max_positions,
        position_size=settings.max_position_size,
    )
    engine = BacktestEngine(config)
    results = engine.run_all_strategies(strategies, codes, start, end, save_to_db)

    # Generate report
    reporter = BacktestReporter()

    print("\n" + "=" * 60)
    print("백테스트 결과 요약")
    print("=" * 60)

    for name, metrics in results.items():
        print(reporter.generate_summary(metrics))

    # Print comparison table
    print("\n전략 비교:")
    comparison = reporter.generate_comparison_table(results)
    print(comparison.to_string(index=False))

    # Generate HTML report
    reporter.generate_full_report(results)
    print(f"\nHTML 리포트가 reports/ 폴더에 생성되었습니다.")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Korean Stock Auto-Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize database")

    # fetch command
    fetch_parser = subparsers.add_parser("fetch", help="Fetch stock data")
    fetch_parser.add_argument(
        "--start", "-s",
        default=(date.today() - timedelta(days=365*3)).strftime("%Y-%m-%d"),
        help="Start date (YYYY-MM-DD)",
    )
    fetch_parser.add_argument(
        "--end", "-e",
        default=date.today().strftime("%Y-%m-%d"),
        help="End date (YYYY-MM-DD)",
    )
    fetch_parser.add_argument(
        "--market", "-m",
        choices=["KOSPI", "KOSDAQ"],
        help="Market to fetch (default: both)",
    )

    # backtest command
    backtest_parser = subparsers.add_parser("backtest", help="Run backtest")
    backtest_parser.add_argument(
        "--strategy", "-t",
        help="Strategy name (default: all)",
    )
    backtest_parser.add_argument(
        "--start", "-s",
        help="Start date (YYYY-MM-DD)",
    )
    backtest_parser.add_argument(
        "--end", "-e",
        help="End date (YYYY-MM-DD)",
    )
    backtest_parser.add_argument(
        "--market", "-m",
        choices=["KOSPI", "KOSDAQ"],
        help="Market to test (default: both)",
    )
    backtest_parser.add_argument(
        "--save", "-S",
        action="store_true",
        help="Save results to database",
    )

    # list command
    list_parser = subparsers.add_parser("list", help="List available strategies")

    args = parser.parse_args()

    if args.command == "init":
        init_database()
    elif args.command == "fetch":
        fetch_data(args.start, args.end, args.market)
    elif args.command == "backtest":
        run_backtest(
            strategy_name=args.strategy,
            start_date=args.start,
            end_date=args.end,
            market=args.market,
            save_to_db=args.save,
        )
    elif args.command == "list":
        print("\n사용 가능한 전략:")
        for i, strategy in enumerate(get_all_strategies(), 1):
            info = strategy.get_strategy_info()
            print(f"  {i}. {info['name']}")
            print(f"     - 손절: {info['stop_loss']:.1%}, 익절: {info['take_profit']:.1%}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
