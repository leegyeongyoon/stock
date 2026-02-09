"""Backtest engine for strategy evaluation."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

import pandas as pd
from tqdm import tqdm

from src.config.constants import COMMISSION_RATE, TAX_RATE, SignalType
from src.config.settings import settings
from src.database.connection import get_session
from src.database.repositories import OHLCVRepository, StockRepository, BacktestRepository, TradeRepository
from src.database.models import BacktestResult, Trade
from src.strategies.base_strategy import BaseStrategy, TradeSignal
from src.backtest.metrics import BacktestMetrics, calculate_metrics
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Position:
    """Represents an open position."""

    code: str
    entry_price: int
    entry_date: datetime
    quantity: int
    strategy_name: str
    entry_reason: str


@dataclass
class BacktestConfig:
    """Backtest configuration."""

    initial_capital: int = 100_000_000  # 1억원
    max_positions: int = 10
    position_size: float = 0.1  # 10% per position
    commission_rate: float = COMMISSION_RATE
    tax_rate: float = TAX_RATE
    allow_same_day_exit: bool = True
    use_parallel: bool = True
    num_workers: Optional[int] = None


class BacktestEngine:
    """Engine for running backtests on trading strategies."""

    def __init__(self, config: Optional[BacktestConfig] = None):
        """
        Initialize backtest engine.

        Args:
            config: Backtest configuration. Uses defaults if not provided.
        """
        self.config = config or BacktestConfig()

    def run(
        self,
        strategy: BaseStrategy,
        codes: list[str],
        start_date: date,
        end_date: date,
        save_to_db: bool = False,
    ) -> BacktestMetrics:
        """
        Run backtest for a strategy on multiple stocks.

        Args:
            strategy: Trading strategy to test.
            codes: List of stock codes to test.
            start_date: Backtest start date.
            end_date: Backtest end date.
            save_to_db: Whether to save results to database.

        Returns:
            BacktestMetrics with performance results.
        """
        logger.info(f"Starting backtest for {strategy.name} on {len(codes)} stocks")
        logger.info(f"Period: {start_date} to {end_date}")

        # Initialize
        capital = self.config.initial_capital
        positions: dict[str, Position] = {}
        trades: list[dict] = []
        equity_curve = []
        equity_dates = []

        # Fetch all OHLCV data
        logger.info("Fetching OHLCV data...")
        all_data = self._fetch_all_data(codes, start_date, end_date)

        if not all_data:
            logger.warning("No data available for backtest")
            return self._empty_metrics(strategy.name, start_date, end_date)

        # Get all trading days
        all_dates = set()
        for df in all_data.values():
            all_dates.update(df.index.tolist())
        trading_days = sorted(all_dates)

        logger.info(f"Processing {len(trading_days)} trading days...")

        # Generate signals for all stocks
        logger.info("Generating signals...")
        all_signals: dict[str, list[TradeSignal]] = {}

        if self.config.use_parallel and len(codes) > 10:
            all_signals = self._generate_signals_parallel(strategy, all_data, codes)
        else:
            for code in tqdm(codes, desc="Generating signals"):
                if code in all_data:
                    signals = strategy.generate_signals(all_data[code], code)
                    if signals:
                        all_signals[code] = signals

        logger.info(f"Generated signals for {len(all_signals)} stocks")

        # Simulate trading day by day
        for current_date in tqdm(trading_days, desc="Simulating"):
            current_dt = datetime.combine(current_date, datetime.min.time())

            # Check exits for existing positions
            for code in list(positions.keys()):
                if code not in all_data:
                    continue

                df = all_data[code]
                if current_date not in df.index:
                    continue

                position = positions[code]
                current_price = int(df.loc[current_date, "close"])

                # Check exit conditions
                df_to_date = df.loc[:current_date]
                should_exit, exit_reason = strategy.should_exit(
                    entry_price=position.entry_price,
                    current_price=current_price,
                    entry_date=position.entry_date,
                    current_date=current_dt,
                    df=df_to_date,
                )

                if should_exit:
                    # Calculate P&L
                    pnl, pnl_rate = self._calculate_pnl(
                        position.entry_price,
                        current_price,
                        position.quantity,
                    )

                    trades.append({
                        "code": code,
                        "strategy_name": strategy.name,
                        "entry_date": position.entry_date,
                        "entry_price": position.entry_price,
                        "exit_date": current_dt,
                        "exit_price": current_price,
                        "quantity": position.quantity,
                        "pnl": pnl,
                        "pnl_rate": pnl_rate,
                        "entry_reason": position.entry_reason,
                        "exit_reason": exit_reason,
                    })

                    # Return original investment + net pnl
                    capital += position.entry_price * position.quantity + pnl
                    del positions[code]

            # Check entries for new positions
            # capital now represents cash (not in positions)
            available_capital = capital
            max_new_positions = self.config.max_positions - len(positions)

            if max_new_positions > 0 and available_capital > 0:
                # Collect all buy signals for today
                today_signals = []
                for code, signals in all_signals.items():
                    if code in positions:
                        continue
                    for signal in signals:
                        signal_date = signal.date.date() if isinstance(signal.date, datetime) else signal.date
                        if signal_date == current_date and signal.signal_type == SignalType.BUY:
                            today_signals.append(signal)

                # Sort by strength and take top signals
                today_signals.sort(key=lambda s: s.strength, reverse=True)
                today_signals = today_signals[:max_new_positions]

                for signal in today_signals:
                    code = signal.code
                    if code in positions or code not in all_data:
                        continue

                    df = all_data[code]
                    if current_date not in df.index:
                        continue

                    entry_price = int(df.loc[current_date, "close"])

                    # Calculate position size (limit to initial capital fraction)
                    max_position_value = self.config.initial_capital * self.config.position_size
                    position_value = min(
                        available_capital * self.config.position_size,
                        available_capital / max(1, max_new_positions),
                        max_position_value,  # Cap at initial capital fraction
                    )

                    quantity = int(position_value / entry_price)
                    if quantity <= 0:
                        continue

                    # Open position
                    positions[code] = Position(
                        code=code,
                        entry_price=entry_price,
                        entry_date=current_dt,
                        quantity=quantity,
                        strategy_name=strategy.name,
                        entry_reason=signal.reason,
                    )

                    # Reduce capital when entering position
                    capital -= entry_price * quantity
                    available_capital -= entry_price * quantity
                    max_new_positions -= 1

                    if max_new_positions <= 0:
                        break

            # Calculate daily equity (cash + current value of positions)
            portfolio_value = capital
            for code, position in positions.items():
                if code in all_data and current_date in all_data[code].index:
                    current_price = int(all_data[code].loc[current_date, "close"])
                    portfolio_value += current_price * position.quantity
                else:
                    # Use entry price if no data available
                    portfolio_value += position.entry_price * position.quantity

            equity_curve.append(portfolio_value)
            equity_dates.append(current_date)

        # Close any remaining positions at end
        for code, position in positions.items():
            if code in all_data and len(all_data[code]) > 0:
                last_price = int(all_data[code]["close"].iloc[-1])
                pnl, pnl_rate = self._calculate_pnl(
                    position.entry_price,
                    last_price,
                    position.quantity,
                )
                trades.append({
                    "code": code,
                    "strategy_name": strategy.name,
                    "entry_date": position.entry_date,
                    "entry_price": position.entry_price,
                    "exit_date": datetime.combine(end_date, datetime.min.time()),
                    "exit_price": last_price,
                    "quantity": position.quantity,
                    "pnl": pnl,
                    "pnl_rate": pnl_rate,
                    "entry_reason": position.entry_reason,
                    "exit_reason": "End of backtest",
                })

        # Create equity series
        equity_series = pd.Series(equity_curve, index=pd.DatetimeIndex(equity_dates))

        # Calculate metrics
        metrics = calculate_metrics(
            trades=trades,
            equity_curve=equity_series,
            strategy_name=strategy.name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.config.initial_capital,
        )

        logger.info(f"Backtest completed: {metrics.total_trades} trades, {metrics.total_return:.2%} return")

        # Save to database if requested
        if save_to_db:
            self._save_results(strategy, metrics, trades, start_date, end_date)

        return metrics

    def _fetch_all_data(
        self,
        codes: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV data for all stocks."""
        data = {}
        with get_session() as session:
            repo = OHLCVRepository(session)
            for code in codes:
                df = repo.get_by_code(code, start_date, end_date)
                if not df.empty:
                    data[code] = df
        return data

    def _generate_signals_parallel(
        self,
        strategy: BaseStrategy,
        all_data: dict[str, pd.DataFrame],
        codes: list[str],
    ) -> dict[str, list[TradeSignal]]:
        """Generate signals in parallel."""
        all_signals = {}
        num_workers = self.config.num_workers or max(1, multiprocessing.cpu_count() - 1)

        # Note: For actual parallel processing, strategy would need to be picklable
        # This is a simplified sequential version
        for code in tqdm(codes, desc="Generating signals"):
            if code in all_data:
                try:
                    signals = strategy.generate_signals(all_data[code], code)
                    if signals:
                        all_signals[code] = signals
                except Exception as e:
                    logger.warning(f"Error generating signals for {code}: {e}")

        return all_signals

    def _calculate_pnl(
        self,
        entry_price: int,
        exit_price: int,
        quantity: int,
    ) -> tuple[int, float]:
        """Calculate P&L including commission and tax."""
        gross_pnl = (exit_price - entry_price) * quantity

        # Commission (both ways)
        commission = int(
            entry_price * quantity * self.config.commission_rate +
            exit_price * quantity * self.config.commission_rate
        )

        # Tax (only on sell)
        tax = int(exit_price * quantity * self.config.tax_rate) if exit_price > entry_price else 0

        net_pnl = gross_pnl - commission - tax
        pnl_rate = net_pnl / (entry_price * quantity)

        return net_pnl, pnl_rate

    def _save_results(
        self,
        strategy: BaseStrategy,
        metrics: BacktestMetrics,
        trades: list[dict],
        start_date: date,
        end_date: date,
    ) -> None:
        """Save backtest results to database."""
        with get_session() as session:
            # Save backtest result
            backtest_repo = BacktestRepository(session)
            backtest_result = BacktestResult(
                strategy_name=strategy.name,
                start_date=start_date,
                end_date=end_date,
                initial_capital=self.config.initial_capital,
                final_capital=metrics.final_capital,
                total_return=metrics.total_return,
                cagr=metrics.cagr,
                sharpe_ratio=metrics.sharpe_ratio,
                max_drawdown=metrics.max_drawdown,
                win_rate=metrics.win_rate,
                profit_factor=metrics.profit_factor,
                total_trades=metrics.total_trades,
                config=strategy.get_strategy_info(),
            )
            backtest_result = backtest_repo.create(backtest_result)

            # Save trades
            trade_repo = TradeRepository(session)
            trade_models = []
            for t in trades:
                trade = Trade(
                    backtest_id=backtest_result.id,
                    code=t["code"],
                    strategy_name=t["strategy_name"],
                    entry_date=t["entry_date"],
                    entry_price=t["entry_price"],
                    exit_date=t["exit_date"],
                    exit_price=t["exit_price"],
                    quantity=t["quantity"],
                    position_value=t["entry_price"] * t["quantity"],
                    pnl=t["pnl"],
                    pnl_rate=t["pnl_rate"],
                    entry_reason=t.get("entry_reason"),
                    exit_reason=t.get("exit_reason"),
                    is_live=False,
                )
                trade_models.append(trade)

            if trade_models:
                trade_repo.create_many(trade_models)

            logger.info(f"Saved backtest result ID: {backtest_result.id}")

    def _empty_metrics(
        self,
        strategy_name: str,
        start_date: date,
        end_date: date,
    ) -> BacktestMetrics:
        """Return empty metrics when no data available."""
        return BacktestMetrics(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.config.initial_capital,
            final_capital=self.config.initial_capital,
            total_return=0.0,
            cagr=0.0,
        )

    def run_all_strategies(
        self,
        strategies: list[BaseStrategy],
        codes: list[str],
        start_date: date,
        end_date: date,
        save_to_db: bool = False,
    ) -> dict[str, BacktestMetrics]:
        """Run backtest for multiple strategies."""
        results = {}
        for strategy in strategies:
            logger.info(f"\n{'='*50}")
            logger.info(f"Running backtest for: {strategy.name}")
            logger.info(f"{'='*50}")
            metrics = self.run(strategy, codes, start_date, end_date, save_to_db)
            results[strategy.name] = metrics
        return results
