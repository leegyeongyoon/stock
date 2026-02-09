"""Repository layer for database operations."""

from datetime import date
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
