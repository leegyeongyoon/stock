"""Intraday backtest engine for day trading strategies."""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional, Literal

import pandas as pd
import numpy as np
from tqdm import tqdm

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 한국 주식시장 거래 시간
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)

# 수수료 및 세금
COMMISSION_RATE = 0.00015  # 0.015%
TAX_RATE = 0.0023  # 0.23% (매도 시)


@dataclass
class IntradayPosition:
    """Represents an intraday position."""
    code: str
    entry_price: float
    entry_time: datetime
    quantity: int
    strategy_name: str
    stop_loss: float
    take_profit: float
    entry_reason: str = ""
    entry_bar_idx: int = 0


@dataclass
class IntradayTrade:
    """Completed intraday trade."""
    code: str
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    quantity: int
    strategy_name: str
    pnl: float
    pnl_pct: float
    exit_reason: str


@dataclass
class IntradayBacktestConfig:
    """Intraday backtest configuration."""
    initial_capital: int = 5_000_000  # 500만원
    max_positions: int = 3  # 동시 최대 포지션
    position_size: float = 0.3  # 30% per position
    commission_rate: float = COMMISSION_RATE
    tax_rate: float = TAX_RATE
    force_close_time: time = time(15, 20)  # 장 마감 10분 전 강제 청산


@dataclass
class IntradayMetrics:
    """Intraday backtest metrics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    avg_holding_time_minutes: float = 0.0
    trades_per_day: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    daily_returns: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 2),
            "total_pnl": round(self.total_pnl, 0),
            "total_return_pct": round(self.total_return_pct, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "avg_holding_time_minutes": round(self.avg_holding_time_minutes, 1),
            "trades_per_day": round(self.trades_per_day, 2),
            "best_trade": round(self.best_trade, 2),
            "worst_trade": round(self.worst_trade, 2),
        }


class IntradayBacktestEngine:
    """Engine for backtesting intraday trading strategies."""

    def __init__(self, config: Optional[IntradayBacktestConfig] = None):
        self.config = config or IntradayBacktestConfig()

    def run(
        self,
        strategy,
        data: dict[str, pd.DataFrame],
        show_progress: bool = True,
    ) -> tuple[IntradayMetrics, list[IntradayTrade]]:
        """
        Run intraday backtest.

        Args:
            strategy: Intraday trading strategy
            data: Dictionary of stock code -> DataFrame with OHLCV data
            show_progress: Show progress bar

        Returns:
            Tuple of (metrics, trades)
        """
        logger.info(f"Starting intraday backtest for {strategy.name}")
        logger.info(f"Initial capital: {self.config.initial_capital:,}원")
        logger.info(f"Stocks: {len(data)}")

        capital = self.config.initial_capital
        positions: dict[str, IntradayPosition] = {}
        all_trades: list[IntradayTrade] = []
        equity_curve = [capital]
        daily_pnl = {}

        # Get all unique dates
        all_dates = set()
        for df in data.values():
            dates = df.index.date
            all_dates.update(dates)
        all_dates = sorted(all_dates)

        logger.info(f"Trading days: {len(all_dates)}")

        for current_date in tqdm(all_dates, desc="Backtesting", disable=not show_progress):
            day_pnl = 0.0

            # Get data for current day
            day_data = {}
            for code, df in data.items():
                day_df = df[df.index.date == current_date]
                if not day_df.empty:
                    day_data[code] = day_df

            if not day_data:
                continue

            # Get all timestamps for the day, sorted
            all_timestamps = set()
            for df in day_data.values():
                all_timestamps.update(df.index.tolist())
            all_timestamps = sorted(all_timestamps)

            for ts in all_timestamps:
                current_time = ts.time() if hasattr(ts, 'time') else ts

                # Skip if outside trading hours
                if hasattr(current_time, 'hour'):
                    if current_time < MARKET_OPEN or current_time > MARKET_CLOSE:
                        continue

                # Force close before market close
                if hasattr(current_time, 'hour') and current_time >= self.config.force_close_time:
                    for code in list(positions.keys()):
                        if code in day_data and ts in day_data[code].index:
                            row = day_data[code].loc[ts]
                            trade = self._close_position(
                                positions[code], float(row["close"]), ts, "Market close"
                            )
                            all_trades.append(trade)
                            capital += trade.pnl
                            day_pnl += trade.pnl
                            del positions[code]
                    continue

                # Check existing positions for exit
                for code in list(positions.keys()):
                    if code not in day_data or ts not in day_data[code].index:
                        continue

                    row = day_data[code].loc[ts]
                    pos = positions[code]

                    # Check stop loss
                    if float(row["low"]) <= pos.stop_loss:
                        trade = self._close_position(pos, pos.stop_loss, ts, "Stop loss")
                        all_trades.append(trade)
                        capital += trade.pnl
                        day_pnl += trade.pnl
                        del positions[code]
                        continue

                    # Check take profit
                    if float(row["high"]) >= pos.take_profit:
                        trade = self._close_position(pos, pos.take_profit, ts, "Take profit")
                        all_trades.append(trade)
                        capital += trade.pnl
                        day_pnl += trade.pnl
                        del positions[code]
                        continue

                    # Check strategy exit signal
                    exit_signal = strategy.check_exit(pos, row, day_data[code].loc[:ts])
                    if exit_signal:
                        trade = self._close_position(
                            pos, float(row["close"]), ts, exit_signal
                        )
                        all_trades.append(trade)
                        capital += trade.pnl
                        day_pnl += trade.pnl
                        del positions[code]

                # Check for new entries (if we have room)
                if len(positions) < self.config.max_positions:
                    available_capital = capital * self.config.position_size

                    for code, df in day_data.items():
                        if code in positions:
                            continue
                        if ts not in df.index:
                            continue

                        row = df.loc[ts]
                        historical = df.loc[:ts]

                        signal = strategy.check_entry(code, row, historical)
                        if signal:
                            price = float(row["close"])
                            quantity = int(available_capital / price)

                            if quantity > 0:
                                stop_loss = price * (1 - signal.get("stop_loss", 0.02))
                                take_profit = price * (1 + signal.get("take_profit", 0.03))

                                positions[code] = IntradayPosition(
                                    code=code,
                                    entry_price=price,
                                    entry_time=ts,
                                    quantity=quantity,
                                    strategy_name=strategy.name,
                                    stop_loss=stop_loss,
                                    take_profit=take_profit,
                                    entry_reason=signal.get("reason", ""),
                                )

                                # Deduct commission
                                commission = price * quantity * self.config.commission_rate
                                capital -= commission

                                if len(positions) >= self.config.max_positions:
                                    break

            # Close any remaining positions at end of day
            for code in list(positions.keys()):
                if code in day_data:
                    last_row = day_data[code].iloc[-1]
                    last_time = day_data[code].index[-1]
                    trade = self._close_position(
                        positions[code], float(last_row["close"]), last_time, "End of day"
                    )
                    all_trades.append(trade)
                    capital += trade.pnl
                    day_pnl += trade.pnl
                    del positions[code]

            # Record daily performance
            daily_pnl[current_date] = day_pnl
            equity_curve.append(capital)

        # Calculate metrics
        metrics = self._calculate_metrics(
            all_trades, equity_curve, daily_pnl, len(all_dates)
        )

        logger.info(f"Backtest completed: {metrics.total_trades} trades")
        logger.info(f"Win rate: {metrics.win_rate:.1f}%")
        logger.info(f"Total return: {metrics.total_return_pct:.2f}%")
        logger.info(f"Total P&L: {metrics.total_pnl:,.0f}원")

        return metrics, all_trades

    def _close_position(
        self,
        pos: IntradayPosition,
        exit_price: float,
        exit_time: datetime,
        reason: str,
    ) -> IntradayTrade:
        """Close a position and create a trade record."""
        # Calculate P&L
        gross_pnl = (exit_price - pos.entry_price) * pos.quantity

        # Deduct commission and tax
        commission = exit_price * pos.quantity * self.config.commission_rate
        tax = exit_price * pos.quantity * self.config.tax_rate if gross_pnl > 0 else 0

        net_pnl = gross_pnl - commission - tax
        pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

        return IntradayTrade(
            code=pos.code,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            quantity=pos.quantity,
            strategy_name=pos.strategy_name,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
        )

    def _calculate_metrics(
        self,
        trades: list[IntradayTrade],
        equity_curve: list[float],
        daily_pnl: dict,
        num_days: int,
    ) -> IntradayMetrics:
        """Calculate backtest metrics."""
        metrics = IntradayMetrics()

        if not trades:
            return metrics

        metrics.total_trades = len(trades)
        metrics.winning_trades = sum(1 for t in trades if t.pnl > 0)
        metrics.losing_trades = sum(1 for t in trades if t.pnl < 0)
        metrics.win_rate = (metrics.winning_trades / metrics.total_trades) * 100

        # P&L metrics
        metrics.total_pnl = sum(t.pnl for t in trades)
        initial_capital = equity_curve[0]
        metrics.total_return_pct = (metrics.total_pnl / initial_capital) * 100

        # Average win/loss
        wins = [t.pnl_pct for t in trades if t.pnl > 0]
        losses = [t.pnl_pct for t in trades if t.pnl < 0]

        metrics.avg_win = np.mean(wins) if wins else 0
        metrics.avg_loss = np.mean(losses) if losses else 0

        # Profit factor
        total_wins = sum(t.pnl for t in trades if t.pnl > 0)
        total_losses = abs(sum(t.pnl for t in trades if t.pnl < 0))
        metrics.profit_factor = total_wins / total_losses if total_losses > 0 else 0

        # Max drawdown
        peak = equity_curve[0]
        max_dd = 0
        for value in equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak * 100
            if dd > max_dd:
                max_dd = dd
        metrics.max_drawdown = max_dd

        # Average holding time
        holding_times = []
        for t in trades:
            if hasattr(t.entry_time, 'timestamp') and hasattr(t.exit_time, 'timestamp'):
                delta = (t.exit_time - t.entry_time).total_seconds() / 60
                holding_times.append(delta)
        metrics.avg_holding_time_minutes = np.mean(holding_times) if holding_times else 0

        # Trades per day
        metrics.trades_per_day = len(trades) / num_days if num_days > 0 else 0

        # Best/worst trade
        pnl_pcts = [t.pnl_pct for t in trades]
        metrics.best_trade = max(pnl_pcts) if pnl_pcts else 0
        metrics.worst_trade = min(pnl_pcts) if pnl_pcts else 0

        # Daily returns
        metrics.daily_returns = list(daily_pnl.values())

        return metrics
