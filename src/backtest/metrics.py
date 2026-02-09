"""Performance metrics calculation."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    """Backtest performance metrics."""

    # Basic info
    strategy_name: str
    start_date: date
    end_date: date
    initial_capital: int
    final_capital: int

    # Returns
    total_return: float  # 총 수익률
    cagr: float  # 연평균 수익률
    daily_returns: list[float] = field(default_factory=list)

    # Risk metrics
    sharpe_ratio: float = 0.0  # 샤프 비율
    sortino_ratio: float = 0.0  # 소르티노 비율
    max_drawdown: float = 0.0  # 최대 낙폭
    max_drawdown_duration: int = 0  # MDD 지속 기간 (일)
    volatility: float = 0.0  # 변동성

    # Trade statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0  # 승률
    profit_factor: float = 0.0  # 손익비
    avg_win: float = 0.0  # 평균 수익
    avg_loss: float = 0.0  # 평균 손실
    avg_trade_return: float = 0.0  # 평균 거래 수익률
    avg_holding_days: float = 0.0  # 평균 보유 기간

    # Monthly/Weekly returns
    monthly_returns: dict[str, float] = field(default_factory=dict)
    weekly_returns: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "strategy_name": self.strategy_name,
            "start_date": str(self.start_date),
            "end_date": str(self.end_date),
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "total_return": round(self.total_return, 4),
            "cagr": round(self.cagr, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "max_drawdown_duration": self.max_drawdown_duration,
            "volatility": round(self.volatility, 4),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "avg_win": round(self.avg_win, 4),
            "avg_loss": round(self.avg_loss, 4),
            "avg_trade_return": round(self.avg_trade_return, 4),
            "avg_holding_days": round(self.avg_holding_days, 2),
            "monthly_returns": self.monthly_returns,
            "weekly_returns": self.weekly_returns,
        }


def calculate_metrics(
    trades: list[dict],
    equity_curve: pd.Series,
    strategy_name: str,
    start_date: date,
    end_date: date,
    initial_capital: int,
    risk_free_rate: float = 0.03,
) -> BacktestMetrics:
    """
    Calculate comprehensive backtest metrics.

    Args:
        trades: List of trade dictionaries with pnl, pnl_rate, entry_date, exit_date.
        equity_curve: Series of portfolio value over time.
        strategy_name: Name of the strategy.
        start_date: Backtest start date.
        end_date: Backtest end date.
        initial_capital: Initial capital.
        risk_free_rate: Annual risk-free rate for Sharpe calculation.

    Returns:
        BacktestMetrics object.
    """
    final_capital = int(equity_curve.iloc[-1]) if len(equity_curve) > 0 else initial_capital

    # Total return
    total_return = (final_capital - initial_capital) / initial_capital

    # CAGR
    days = (end_date - start_date).days
    years = days / 365.25
    if years > 0 and final_capital > 0:
        cagr = (final_capital / initial_capital) ** (1 / years) - 1
    else:
        cagr = 0.0

    # Daily returns
    daily_returns = equity_curve.pct_change().dropna().tolist()

    # Volatility (annualized)
    if len(daily_returns) > 1:
        volatility = np.std(daily_returns) * np.sqrt(252)
    else:
        volatility = 0.0

    # Sharpe Ratio
    if volatility > 0:
        daily_rf = risk_free_rate / 252
        excess_returns = [r - daily_rf for r in daily_returns]
        sharpe_ratio = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
    else:
        sharpe_ratio = 0.0

    # Sortino Ratio (uses downside deviation)
    negative_returns = [r for r in daily_returns if r < 0]
    if len(negative_returns) > 1:
        downside_std = np.std(negative_returns) * np.sqrt(252)
        if downside_std > 0:
            sortino_ratio = (np.mean(daily_returns) * 252 - risk_free_rate) / downside_std
        else:
            sortino_ratio = 0.0
    else:
        sortino_ratio = 0.0

    # Maximum Drawdown
    rolling_max = equity_curve.expanding().max()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_drawdown = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

    # MDD Duration
    max_drawdown_duration = 0
    if len(drawdown) > 0:
        in_drawdown = False
        current_duration = 0
        for dd in drawdown:
            if dd < 0:
                in_drawdown = True
                current_duration += 1
                max_drawdown_duration = max(max_drawdown_duration, current_duration)
            else:
                in_drawdown = False
                current_duration = 0

    # Trade statistics
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.get("pnl", 0) > 0)
    losing_trades = sum(1 for t in trades if t.get("pnl", 0) < 0)

    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    # Profit factor
    gross_profit = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # Average win/loss
    wins = [t.get("pnl_rate", 0) for t in trades if t.get("pnl", 0) > 0]
    losses = [t.get("pnl_rate", 0) for t in trades if t.get("pnl", 0) < 0]
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0

    # Average trade return
    all_returns = [t.get("pnl_rate", 0) for t in trades]
    avg_trade_return = np.mean(all_returns) if all_returns else 0.0

    # Average holding days
    holding_days = []
    for t in trades:
        if t.get("entry_date") and t.get("exit_date"):
            days_held = (t["exit_date"] - t["entry_date"]).days
            holding_days.append(days_held)
    avg_holding_days = np.mean(holding_days) if holding_days else 0.0

    # Monthly returns
    monthly_returns = {}
    if len(equity_curve) > 0:
        equity_df = equity_curve.to_frame(name="value")
        equity_df.index = pd.to_datetime(equity_df.index)
        monthly = equity_df.resample("M").last()
        monthly_pct = monthly.pct_change().dropna()
        for idx, row in monthly_pct.iterrows():
            month_key = idx.strftime("%Y-%m")
            monthly_returns[month_key] = round(row["value"], 4)

    # Weekly returns
    weekly_returns = {}
    if len(equity_curve) > 0:
        equity_df = equity_curve.to_frame(name="value")
        equity_df.index = pd.to_datetime(equity_df.index)
        weekly = equity_df.resample("W").last()
        weekly_pct = weekly.pct_change().dropna()
        for idx, row in weekly_pct.iterrows():
            week_key = idx.strftime("%Y-W%W")
            weekly_returns[week_key] = round(row["value"], 4)

    def to_python_float(val) -> float:
        """Convert numpy types to Python float."""
        if isinstance(val, (np.floating, np.integer)):
            return float(val)
        if pd.isna(val):
            return 0.0
        return float(val) if val is not None else 0.0

    return BacktestMetrics(
        strategy_name=strategy_name,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        final_capital=final_capital,
        total_return=to_python_float(total_return),
        cagr=to_python_float(cagr),
        daily_returns=[to_python_float(r) for r in daily_returns],
        sharpe_ratio=to_python_float(sharpe_ratio),
        sortino_ratio=to_python_float(sortino_ratio),
        max_drawdown=to_python_float(max_drawdown),
        max_drawdown_duration=int(max_drawdown_duration),
        volatility=to_python_float(volatility),
        total_trades=int(total_trades),
        winning_trades=int(winning_trades),
        losing_trades=int(losing_trades),
        win_rate=to_python_float(win_rate),
        profit_factor=to_python_float(profit_factor),
        avg_win=to_python_float(avg_win),
        avg_loss=to_python_float(avg_loss),
        avg_trade_return=to_python_float(avg_trade_return),
        avg_holding_days=to_python_float(avg_holding_days),
        monthly_returns=monthly_returns,
        weekly_returns=weekly_returns,
    )
