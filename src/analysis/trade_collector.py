"""Trade data collector for AI analysis."""

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from src.database.connection import get_session
from src.database.repositories import TradeRepository, OHLCVRepository, BacktestRepository
from src.strategies.base_strategy import BaseStrategy
from src.backtest.engine import BacktestEngine, BacktestConfig
from src.analysis.openai_analyzer import TradeAnalysisData
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TradeDetail:
    """Detailed information about a single trade."""

    code: str
    entry_date: datetime
    exit_date: datetime
    entry_price: int
    exit_price: int
    quantity: int
    pnl: int
    pnl_rate: float
    holding_days: int
    entry_reason: str
    exit_reason: str
    is_win: bool
    indicators: dict = field(default_factory=dict)


class TradeCollector:
    """Collector for trade data and market context."""

    def __init__(self):
        """Initialize trade collector."""
        pass

    def collect_from_backtest(
        self,
        strategy: BaseStrategy,
        codes: list[str],
        start_date: date,
        end_date: date,
    ) -> TradeAnalysisData:
        """
        Run backtest and collect trade data for analysis.

        Args:
            strategy: Strategy to backtest.
            codes: List of stock codes.
            start_date: Start date.
            end_date: End date.

        Returns:
            TradeAnalysisData for AI analysis.
        """
        engine = BacktestEngine(BacktestConfig())
        metrics = engine.run(strategy, codes, start_date, end_date, save_to_db=True)

        return self._collect_from_db(strategy.name)

    def collect_from_db(self, strategy_name: str) -> TradeAnalysisData:
        """
        Collect trade data from database.

        Args:
            strategy_name: Name of the strategy.

        Returns:
            TradeAnalysisData for AI analysis.
        """
        return self._collect_from_db(strategy_name)

    def _collect_from_db(self, strategy_name: str) -> TradeAnalysisData:
        """Internal method to collect trade data from database."""
        with get_session() as session:
            trade_repo = TradeRepository(session)
            backtest_repo = BacktestRepository(session)

            latest_backtest = backtest_repo.get_latest_by_strategy(strategy_name)
            if not latest_backtest:
                logger.warning(f"No backtest found for {strategy_name}")
                return self._empty_analysis_data(strategy_name)

            trades = trade_repo.get_by_backtest(latest_backtest.id)
            if not trades:
                logger.warning(f"No trades found for {strategy_name}")
                return self._empty_analysis_data(strategy_name)

            return self._process_trades(
                strategy_name=strategy_name,
                trades=trades,
                backtest_config=latest_backtest.config or {},
                total_return=latest_backtest.total_return,
                win_rate=latest_backtest.win_rate,
            )

    def collect_from_trades(
        self,
        strategy_name: str,
        trades: list[dict],
        strategy_params: dict,
        total_return: float,
    ) -> TradeAnalysisData:
        """
        Collect trade data from a list of trades.

        Args:
            strategy_name: Strategy name.
            trades: List of trade dictionaries.
            strategy_params: Strategy parameters.
            total_return: Total return of the strategy.

        Returns:
            TradeAnalysisData for AI analysis.
        """
        if not trades:
            return self._empty_analysis_data(strategy_name)

        winning_trades = [t for t in trades if t.get("pnl", 0) > 0]
        losing_trades = [t for t in trades if t.get("pnl", 0) <= 0]

        win_rate = len(winning_trades) / len(trades) * 100 if trades else 0

        return self._process_trade_list(
            strategy_name=strategy_name,
            trades=trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            strategy_params=strategy_params,
            total_return=total_return,
            win_rate=win_rate,
        )

    def _process_trades(
        self,
        strategy_name: str,
        trades: list,
        backtest_config: dict,
        total_return: float,
        win_rate: float,
    ) -> TradeAnalysisData:
        """Process trades from database models."""
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

        winning_trades = [t for t in trade_dicts if t.get("pnl", 0) > 0]
        losing_trades = [t for t in trade_dicts if t.get("pnl", 0) <= 0]

        return self._process_trade_list(
            strategy_name=strategy_name,
            trades=trade_dicts,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            strategy_params=backtest_config.get("params", {}),
            total_return=total_return,
            win_rate=win_rate,
        )

    def _process_trade_list(
        self,
        strategy_name: str,
        trades: list[dict],
        winning_trades: list[dict],
        losing_trades: list[dict],
        strategy_params: dict,
        total_return: float,
        win_rate: float,
    ) -> TradeAnalysisData:
        """Process a list of trades into analysis data."""
        avg_win = 0.0
        if winning_trades:
            avg_win = sum(t.get("pnl_rate", 0) for t in winning_trades) / len(winning_trades)

        avg_loss = 0.0
        if losing_trades:
            avg_loss = sum(t.get("pnl_rate", 0) for t in losing_trades) / len(losing_trades)

        losing_summary = self._summarize_trades(losing_trades)
        winning_summary = self._summarize_trades(winning_trades)

        market_conditions = self._analyze_market_conditions(trades)

        return TradeAnalysisData(
            strategy_name=strategy_name,
            current_params=strategy_params,
            win_rate=win_rate,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_win=avg_win,
            avg_loss=avg_loss,
            total_return=total_return,
            losing_trades_summary=losing_summary,
            winning_trades_summary=winning_summary,
            market_conditions=market_conditions,
        )

    def _summarize_trades(self, trades: list[dict]) -> list[dict]:
        """Summarize trades for AI analysis."""
        summaries = []
        sorted_trades = sorted(
            trades,
            key=lambda t: abs(t.get("pnl_rate", 0)),
            reverse=True,
        )

        for trade in sorted_trades[:30]:
            summary = {
                "code": trade.get("code", "N/A"),
                "entry_price": trade.get("entry_price", 0),
                "exit_price": trade.get("exit_price", 0),
                "pnl_rate": trade.get("pnl_rate", 0),
                "holding_days": trade.get("holding_days", 0),
                "entry_reason": trade.get("entry_reason", ""),
                "exit_reason": trade.get("exit_reason", ""),
            }

            if "indicators" in trade:
                summary["indicators"] = trade["indicators"]

            summaries.append(summary)

        return summaries

    def _analyze_market_conditions(self, trades: list[dict]) -> dict:
        """Analyze market conditions during trades."""
        if not trades:
            return {}

        conditions = {
            "total_trades": len(trades),
            "exit_reasons": {},
            "holding_period_distribution": {
                "same_day": 0,
                "1_3_days": 0,
                "4_7_days": 0,
                "over_7_days": 0,
            },
            "loss_by_exit_reason": {},
        }

        for trade in trades:
            exit_reason = trade.get("exit_reason", "Unknown")
            base_reason = self._extract_base_reason(exit_reason)

            conditions["exit_reasons"][base_reason] = (
                conditions["exit_reasons"].get(base_reason, 0) + 1
            )

            holding_days = trade.get("holding_days", 0)
            if holding_days == 0:
                conditions["holding_period_distribution"]["same_day"] += 1
            elif holding_days <= 3:
                conditions["holding_period_distribution"]["1_3_days"] += 1
            elif holding_days <= 7:
                conditions["holding_period_distribution"]["4_7_days"] += 1
            else:
                conditions["holding_period_distribution"]["over_7_days"] += 1

            if trade.get("pnl", 0) < 0:
                if base_reason not in conditions["loss_by_exit_reason"]:
                    conditions["loss_by_exit_reason"][base_reason] = {
                        "count": 0,
                        "total_loss_rate": 0,
                    }
                conditions["loss_by_exit_reason"][base_reason]["count"] += 1
                conditions["loss_by_exit_reason"][base_reason]["total_loss_rate"] += abs(
                    trade.get("pnl_rate", 0)
                )

        for reason, data in conditions["loss_by_exit_reason"].items():
            if data["count"] > 0:
                data["avg_loss_rate"] = data["total_loss_rate"] / data["count"]

        return conditions

    def _extract_base_reason(self, exit_reason: str) -> str:
        """Extract base reason from exit reason string."""
        if not exit_reason:
            return "Unknown"

        reason_lower = exit_reason.lower()

        if "stop loss" in reason_lower or "손절" in reason_lower:
            return "Stop Loss"
        elif "take profit" in reason_lower or "익절" in reason_lower:
            return "Take Profit"
        elif "max holding" in reason_lower or "보유일" in reason_lower:
            return "Max Holding Days"
        elif "death cross" in reason_lower:
            return "Death Cross"
        elif "rsi" in reason_lower:
            return "RSI Signal"
        elif "vwap" in reason_lower:
            return "VWAP Reached"
        elif "bb middle" in reason_lower or "bollinger" in reason_lower:
            return "BB Signal"
        elif "bearish" in reason_lower or "음봉" in reason_lower:
            return "Bearish Candles"
        elif "momentum" in reason_lower:
            return "Momentum Breakdown"
        elif "end of backtest" in reason_lower:
            return "End of Backtest"
        else:
            return "Other"

    def _empty_analysis_data(self, strategy_name: str) -> TradeAnalysisData:
        """Return empty analysis data."""
        return TradeAnalysisData(
            strategy_name=strategy_name,
            current_params={},
            win_rate=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            avg_win=0.0,
            avg_loss=0.0,
            total_return=0.0,
        )

    def collect_with_indicators(
        self,
        strategy_name: str,
        trades: list[dict],
        ohlcv_data: dict[str, pd.DataFrame],
        strategy_params: dict,
        total_return: float,
    ) -> TradeAnalysisData:
        """
        Collect trade data with technical indicators at entry.

        Args:
            strategy_name: Strategy name.
            trades: List of trade dictionaries.
            ohlcv_data: Dictionary of OHLCV DataFrames by code.
            strategy_params: Strategy parameters.
            total_return: Total return.

        Returns:
            TradeAnalysisData with indicator information.
        """
        enriched_trades = []

        for trade in trades:
            code = trade.get("code")
            entry_date = trade.get("entry_date")

            enriched = dict(trade)

            if code in ohlcv_data and entry_date:
                df = ohlcv_data[code]
                entry_dt = entry_date.date() if isinstance(entry_date, datetime) else entry_date

                if entry_dt in df.index:
                    row = df.loc[entry_dt]
                    enriched["indicators"] = {
                        "rsi": row.get("rsi"),
                        "volume_ratio": row.get("volume_ratio"),
                        "bb_width": row.get("bb_width"),
                        "macd_hist": row.get("macd_hist"),
                        "change_5d": row.get("change_5d"),
                    }

            enriched_trades.append(enriched)

        return self.collect_from_trades(
            strategy_name=strategy_name,
            trades=enriched_trades,
            strategy_params=strategy_params,
            total_return=total_return,
        )
