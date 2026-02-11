"""Repository layer for database operations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import pandas as pd
from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from src.database.models import (
    Stock,
    OHLCVDaily,
    InvestorTrading,
    BacktestResult,
    Trade,
    Signal,
    LiveOrder,
    LivePosition,
    LiveTrade,
    PortfolioSnapshot,
    SystemEvent,
    StrategyPerformance,
)


class StockRepository:
    """Repository for stock operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_all(self, market: Optional[str] = None, active_only: bool = True) -> list[Stock]:
        """Get all stocks, optionally filtered by market."""
        query = select(Stock)
        if market:
            query = query.where(Stock.market == market)
        if active_only:
            query = query.where(Stock.is_active == True)
        return list(self.session.execute(query).scalars().all())

    def get_by_code(self, code: str) -> Optional[Stock]:
        """Get stock by code."""
        return self.session.get(Stock, code)

    def get_codes(self, market: Optional[str] = None) -> list[str]:
        """Get all stock codes."""
        query = select(Stock.code).where(Stock.is_active == True)
        if market:
            query = query.where(Stock.market == market)
        return list(self.session.execute(query).scalars().all())

    def upsert_many(self, stocks: list[dict]) -> int:
        """Upsert multiple stocks."""
        if not stocks:
            return 0

        stmt = insert(Stock).values(stocks)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "name": stmt.excluded.name,
                "market": stmt.excluded.market,
                "sector": stmt.excluded.sector,
                "market_cap": stmt.excluded.market_cap,
                "is_active": stmt.excluded.is_active,
            },
        )
        self.session.execute(stmt)
        return len(stocks)


class OHLCVRepository:
    """Repository for OHLCV data operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_code(
        self,
        code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """Get OHLCV data for a stock as DataFrame."""
        query = select(OHLCVDaily).where(OHLCVDaily.code == code)

        if start_date:
            query = query.where(OHLCVDaily.date >= start_date)
        if end_date:
            query = query.where(OHLCVDaily.date <= end_date)

        query = query.order_by(OHLCVDaily.date)
        results = self.session.execute(query).scalars().all()

        if not results:
            return pd.DataFrame()

        data = [
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "value": r.value,
                "change_rate": float(r.change_rate) if r.change_rate else None,
            }
            for r in results
        ]
        df = pd.DataFrame(data)
        df.set_index("date", inplace=True)
        return df

    def get_latest_date(self, code: str) -> Optional[date]:
        """Get the latest date for a stock."""
        query = (
            select(func.max(OHLCVDaily.date))
            .where(OHLCVDaily.code == code)
        )
        return self.session.execute(query).scalar()

    def upsert_many(self, records: list[dict]) -> int:
        """Upsert multiple OHLCV records."""
        if not records:
            return 0

        stmt = insert(OHLCVDaily).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ohlcv_daily_code_date",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "value": stmt.excluded.value,
                "change_rate": stmt.excluded.change_rate,
            },
        )
        self.session.execute(stmt)
        return len(records)

    def get_all_for_date_range(
        self,
        codes: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, pd.DataFrame]:
        """Get OHLCV data for multiple stocks."""
        result = {}
        for code in codes:
            df = self.get_by_code(code, start_date, end_date)
            if not df.empty:
                result[code] = df
        return result


class InvestorTradingRepository:
    """Repository for investor trading data."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_code(
        self,
        code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """Get investor trading data as DataFrame."""
        query = select(InvestorTrading).where(InvestorTrading.code == code)

        if start_date:
            query = query.where(InvestorTrading.date >= start_date)
        if end_date:
            query = query.where(InvestorTrading.date <= end_date)

        query = query.order_by(InvestorTrading.date)
        results = self.session.execute(query).scalars().all()

        if not results:
            return pd.DataFrame()

        data = [
            {
                "date": r.date,
                "institution_buy": r.institution_buy,
                "institution_sell": r.institution_sell,
                "foreign_buy": r.foreign_buy,
                "foreign_sell": r.foreign_sell,
                "individual_buy": r.individual_buy,
                "individual_sell": r.individual_sell,
                "institution_net": r.institution_net,
                "foreign_net": r.foreign_net,
            }
            for r in results
        ]
        df = pd.DataFrame(data)
        df.set_index("date", inplace=True)
        return df

    def upsert_many(self, records: list[dict]) -> int:
        """Upsert multiple investor trading records."""
        if not records:
            return 0

        stmt = insert(InvestorTrading).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_investor_trading_code_date",
            set_={
                "institution_buy": stmt.excluded.institution_buy,
                "institution_sell": stmt.excluded.institution_sell,
                "foreign_buy": stmt.excluded.foreign_buy,
                "foreign_sell": stmt.excluded.foreign_sell,
                "individual_buy": stmt.excluded.individual_buy,
                "individual_sell": stmt.excluded.individual_sell,
            },
        )
        self.session.execute(stmt)
        return len(records)


class BacktestRepository:
    """Repository for backtest results."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, result: BacktestResult) -> BacktestResult:
        """Create a new backtest result."""
        self.session.add(result)
        self.session.flush()
        return result

    def get_by_id(self, backtest_id: int) -> Optional[BacktestResult]:
        """Get backtest result by ID."""
        return self.session.get(BacktestResult, backtest_id)

    def get_by_strategy(self, strategy_name: str) -> list[BacktestResult]:
        """Get all backtest results for a strategy."""
        query = (
            select(BacktestResult)
            .where(BacktestResult.strategy_name == strategy_name)
            .order_by(BacktestResult.run_date.desc())
        )
        return list(self.session.execute(query).scalars().all())

    def get_latest(self, strategy_name: str) -> Optional[BacktestResult]:
        """Get the latest backtest result for a strategy."""
        query = (
            select(BacktestResult)
            .where(BacktestResult.strategy_name == strategy_name)
            .order_by(BacktestResult.run_date.desc())
            .limit(1)
        )
        return self.session.execute(query).scalar()

    def get_latest_by_strategy(self, strategy_name: str) -> Optional[BacktestResult]:
        """Get the latest backtest result for a strategy (alias for get_latest)."""
        return self.get_latest(strategy_name)


class TradeRepository:
    """Repository for trade records."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, trade: Trade) -> Trade:
        """Create a new trade record."""
        self.session.add(trade)
        self.session.flush()
        return trade

    def create_many(self, trades: list[Trade]) -> list[Trade]:
        """Create multiple trade records."""
        self.session.add_all(trades)
        self.session.flush()
        return trades

    def get_by_backtest(self, backtest_id: int) -> list[Trade]:
        """Get all trades for a backtest."""
        query = (
            select(Trade)
            .where(Trade.backtest_id == backtest_id)
            .order_by(Trade.entry_date)
        )
        return list(self.session.execute(query).scalars().all())

    def get_by_strategy(
        self,
        strategy_name: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[Trade]:
        """Get trades by strategy name."""
        query = select(Trade).where(Trade.strategy_name == strategy_name)

        if start_date:
            query = query.where(Trade.entry_date >= start_date)
        if end_date:
            query = query.where(Trade.entry_date <= end_date)

        query = query.order_by(Trade.entry_date)
        return list(self.session.execute(query).scalars().all())


class SignalRepository:
    """Repository for trading signals."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, signal: Signal) -> Signal:
        """Create a new signal."""
        self.session.add(signal)
        self.session.flush()
        return signal

    def get_unexecuted(self, strategy_name: Optional[str] = None) -> list[Signal]:
        """Get unexecuted signals."""
        query = select(Signal).where(Signal.executed == False)

        if strategy_name:
            query = query.where(Signal.strategy_name == strategy_name)

        query = query.order_by(Signal.signal_date)
        return list(self.session.execute(query).scalars().all())

    def mark_executed(self, signal_id: int) -> None:
        """Mark a signal as executed."""
        signal = self.session.get(Signal, signal_id)
        if signal:
            signal.executed = True


# ── Live Trading Repositories ──────────────────────────────────


class LiveOrderRepository:
    """Repository for live order operations."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(self, data: dict) -> None:
        """Upsert a live order by order_id."""
        stmt = insert(LiveOrder).values(data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["order_id"],
            set_={
                "status": stmt.excluded.status,
                "filled_quantity": stmt.excluded.filled_quantity,
                "filled_price": stmt.excluded.filled_price,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        self.session.execute(stmt)

    def update_status(
        self,
        order_id: str,
        status: str,
        filled_quantity: int = 0,
        filled_price: float = 0.0,
    ) -> None:
        """Update order status and fill info."""
        order = self.session.execute(
            select(LiveOrder).where(LiveOrder.order_id == order_id)
        ).scalar_one_or_none()
        if order:
            order.status = status
            order.filled_quantity = filled_quantity
            order.filled_price = Decimal(str(filled_price))
            order.updated_at = datetime.now()

    def get_open_orders(self) -> list[LiveOrder]:
        """Get all open (non-terminal) orders."""
        query = select(LiveOrder).where(
            LiveOrder.status.in_(["PENDING", "SUBMITTED", "PARTIAL_FILL"])
        )
        return list(self.session.execute(query).scalars().all())

    def get_by_order_id(self, order_id: str) -> Optional[LiveOrder]:
        """Get order by order_id."""
        return self.session.execute(
            select(LiveOrder).where(LiveOrder.order_id == order_id)
        ).scalar_one_or_none()


class LivePositionRepository:
    """Repository for live position operations."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(self, data: dict) -> None:
        """Upsert a live position by (stock_code, strategy_name)."""
        stmt = insert(LivePosition).values(data)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_live_pos_code_strategy",
            set_={
                "quantity": stmt.excluded.quantity,
                "avg_price": stmt.excluded.avg_price,
                "current_price": stmt.excluded.current_price,
                "unrealized_pnl": stmt.excluded.unrealized_pnl,
                "stop_loss_price": stmt.excluded.stop_loss_price,
                "take_profit_price": stmt.excluded.take_profit_price,
            },
        )
        self.session.execute(stmt)

    def delete_by_code(self, stock_code: str) -> None:
        """Delete position by stock code."""
        pos = self.session.execute(
            select(LivePosition).where(LivePosition.stock_code == stock_code)
        ).scalar_one_or_none()
        if pos:
            self.session.delete(pos)

    def get_all(self) -> list[LivePosition]:
        """Get all live positions."""
        return list(
            self.session.execute(select(LivePosition)).scalars().all()
        )

    def update_prices(self, updates: list[dict]) -> None:
        """Batch update current prices for positions."""
        for upd in updates:
            pos = self.session.execute(
                select(LivePosition).where(
                    LivePosition.stock_code == upd["stock_code"]
                )
            ).scalar_one_or_none()
            if pos:
                pos.current_price = Decimal(str(upd["current_price"]))
                pos.unrealized_pnl = Decimal(str(upd.get("unrealized_pnl", 0)))


class LiveTradeRepository:
    """Repository for live trade operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, data: dict) -> None:
        """Create a new trade record."""
        trade = LiveTrade(**data)
        self.session.add(trade)
        self.session.flush()

    def get_today(self) -> list[LiveTrade]:
        """Get today's trades."""
        today = date.today()
        query = select(LiveTrade).where(
            func.date(LiveTrade.traded_at) == today
        ).order_by(LiveTrade.traded_at)
        return list(self.session.execute(query).scalars().all())


class PortfolioSnapshotRepository:
    """Repository for portfolio snapshots."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(self, data: dict) -> None:
        """Upsert daily portfolio snapshot."""
        stmt = insert(PortfolioSnapshot).values(data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={
                "total_equity": stmt.excluded.total_equity,
                "daily_pnl": stmt.excluded.daily_pnl,
                "daily_return": stmt.excluded.daily_return,
                "total_trades": stmt.excluded.total_trades,
                "win_rate": stmt.excluded.win_rate,
            },
        )
        self.session.execute(stmt)

    def get_recent(self, days: int = 30) -> list[PortfolioSnapshot]:
        """Get recent snapshots."""
        query = (
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.date.desc())
            .limit(days)
        )
        return list(self.session.execute(query).scalars().all())


class SystemEventRepository:
    """Repository for system events."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, data: dict) -> None:
        """Log a system event."""
        event = SystemEvent(**data)
        self.session.add(event)
        self.session.flush()

    def get_recent(self, limit: int = 100) -> list[SystemEvent]:
        """Get recent events."""
        query = (
            select(SystemEvent)
            .order_by(SystemEvent.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(query).scalars().all())


class StrategyPerformanceRepository:
    """Repository for strategy performance."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(self, data: dict) -> None:
        """Upsert daily strategy performance."""
        stmt = insert(StrategyPerformance).values(data)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_strategy_perf_date_name",
            set_={
                "trades": stmt.excluded.trades,
                "wins": stmt.excluded.wins,
                "pnl": stmt.excluded.pnl,
            },
        )
        self.session.execute(stmt)
