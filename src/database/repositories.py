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
    OHLCVIntraday,
    DailyMovers,
    LimitEvent,
    StockTheme,
    DailyHotTheme,
    CollectionJobLog,
    MockForwardFill,
    OrderFlowSnapshot,
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
        """Upsert a live position by stock_code (unique)."""
        stmt = insert(LivePosition).values(data)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_live_pos_code",
            set_={
                "stock_name": stmt.excluded.stock_name,
                "strategy_name": stmt.excluded.strategy_name,
                "quantity": stmt.excluded.quantity,
                "avg_price": stmt.excluded.avg_price,
                "current_price": stmt.excluded.current_price,
                "unrealized_pnl": stmt.excluded.unrealized_pnl,
                "stop_loss_pct": stmt.excluded.stop_loss_pct,
                "take_profit_pct": stmt.excluded.take_profit_pct,
                "stop_loss_price": stmt.excluded.stop_loss_price,
                "take_profit_price": stmt.excluded.take_profit_price,
                "partial_sold": stmt.excluded.partial_sold,
                "original_quantity": stmt.excluded.original_quantity,
            },
        )
        self.session.execute(stmt)

    def get_by_code(self, stock_code: str) -> Optional[LivePosition]:
        """Get a single position by stock code."""
        return self.session.execute(
            select(LivePosition).where(LivePosition.stock_code == stock_code)
        ).scalar_one_or_none()

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


# ── 단타 재설계: 데이터 기반 리포지토리 ─────────────────────────────


class OHLCVIntradayRepository:
    """분봉 데이터 멱등 upsert/조회.

    기존 raw 테이블과 공존하므로 conflict 대상은 (constraint 이름이 아니라)
    컬럼 집합으로 지정한다.
    """

    def __init__(self, session: Session):
        self.session = session

    def upsert_many(self, records: list[dict]) -> int:
        """분봉 레코드 멱등 upsert. records: code/datetime/open/high/low/close/volume/interval."""
        if not records:
            return 0
        stmt = insert(OHLCVIntraday).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code", "datetime", "interval"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        self.session.execute(stmt)
        return len(records)

    def get_codes_for_date(self, target_date: date, interval: str = "1m") -> set[str]:
        """해당 일자에 이미 분봉이 적재된 종목코드 집합(재개용 skip 판단)."""
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time())
        query = (
            select(OHLCVIntraday.code)
            .where(
                OHLCVIntraday.interval == interval,
                OHLCVIntraday.datetime >= start,
                OHLCVIntraday.datetime <= end,
            )
            .distinct()
        )
        return set(self.session.execute(query).scalars().all())

    def get_by_code(
        self, code: str, interval: str = "1m",
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """단일 종목 분봉을 datetime 인덱스 DataFrame으로."""
        query = select(OHLCVIntraday).where(
            OHLCVIntraday.code == code, OHLCVIntraday.interval == interval
        )
        if start:
            query = query.where(OHLCVIntraday.datetime >= start)
        if end:
            query = query.where(OHLCVIntraday.datetime <= end)
        query = query.order_by(OHLCVIntraday.datetime)
        rows = self.session.execute(query).scalars().all()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            [
                {
                    "datetime": r.datetime,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows
            ]
        )
        df.set_index("datetime", inplace=True)
        return df


class DailyMoversRepository:
    """생존편향 없는 그날 유니버스 멱등 upsert/조회."""

    _UPDATABLE = (
        "market", "open", "high", "low", "close", "change_rate", "volume", "value",
        "market_cap", "volume_ratio", "is_limit_up", "is_limit_down",
        "rank_change", "rank_value", "rank_volume_ratio", "flags", "theme_tags",
    )

    def __init__(self, session: Session):
        self.session = session

    def upsert_many(self, records: list[dict]) -> int:
        if not records:
            return 0
        stmt = insert(DailyMovers).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_daily_movers_date_code",
            set_={c: getattr(stmt.excluded, c) for c in self._UPDATABLE},
        )
        self.session.execute(stmt)
        return len(records)

    def get_universe(self, target_date: date) -> list[str]:
        """해당 일자에 포착된 모든 종목코드(거래대금 순)."""
        query = (
            select(DailyMovers.code)
            .where(DailyMovers.date == target_date)
            .order_by(DailyMovers.value.desc().nullslast())
        )
        return list(self.session.execute(query).scalars().all())

    def get_for_date(self, target_date: date) -> list[DailyMovers]:
        query = (
            select(DailyMovers)
            .where(DailyMovers.date == target_date)
            .order_by(DailyMovers.change_rate.desc().nullslast())
        )
        return list(self.session.execute(query).scalars().all())

    def get_dates(self, start: date, end: date) -> list[date]:
        query = (
            select(DailyMovers.date)
            .where(DailyMovers.date >= start, DailyMovers.date <= end)
            .distinct()
            .order_by(DailyMovers.date)
        )
        return list(self.session.execute(query).scalars().all())

    def update_theme_tags(self, target_date: date, code: str, theme_tags: list[str]) -> None:
        """테마 수집 후 theme_tags 역정규화 갱신."""
        row = self.session.execute(
            select(DailyMovers).where(
                DailyMovers.date == target_date, DailyMovers.code == code
            )
        ).scalar_one_or_none()
        if row:
            row.theme_tags = theme_tags


class LimitEventRepository:
    """상한가/하한가 이벤트 멱등 upsert/조회."""

    _UPDATABLE = (
        "limit_price", "first_hit_time", "hit_count", "closed_at_limit", "source",
    )

    def __init__(self, session: Session):
        self.session = session

    def upsert_many(self, records: list[dict]) -> int:
        if not records:
            return 0
        stmt = insert(LimitEvent).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_limit_events_date_code_type",
            set_={c: getattr(stmt.excluded, c) for c in self._UPDATABLE},
        )
        self.session.execute(stmt)
        return len(records)

    def get_for_date(self, target_date: date) -> list[LimitEvent]:
        query = select(LimitEvent).where(LimitEvent.date == target_date)
        return list(self.session.execute(query).scalars().all())


class StockThemeRepository:
    """일자별 테마 소속 멱등 upsert/조회."""

    def __init__(self, session: Session):
        self.session = session

    def upsert_many(self, records: list[dict]) -> int:
        if not records:
            return 0
        stmt = insert(StockTheme).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_stock_themes_date_code_theme",
            set_={
                "theme_name": stmt.excluded.theme_name,
                "is_leader": stmt.excluded.is_leader,
            },
        )
        self.session.execute(stmt)
        return len(records)

    def get_for_date(self, target_date: date) -> dict[str, list[str]]:
        """{code: [theme_name, ...]} 형태로 그날 테마 소속 반환."""
        rows = self.session.execute(
            select(StockTheme).where(StockTheme.date == target_date)
        ).scalars().all()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r.code, []).append(r.theme_name or r.theme_code)
        return out


class DailyHotThemeRepository:
    """일자별 핫테마 리더보드 멱등 upsert/조회."""

    _UPDATABLE = (
        "theme_name", "rank", "change_rate", "up_count", "down_count", "stock_count",
        "leader_code", "leader_name", "total_score", "news_hot_score", "sentiment",
    )

    def __init__(self, session: Session):
        self.session = session

    def upsert_many(self, records: list[dict]) -> int:
        if not records:
            return 0
        stmt = insert(DailyHotTheme).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_daily_hot_themes_date_theme",
            set_={c: getattr(stmt.excluded, c) for c in self._UPDATABLE},
        )
        self.session.execute(stmt)
        return len(records)

    def get_for_date(self, target_date: date) -> list[DailyHotTheme]:
        query = (
            select(DailyHotTheme)
            .where(DailyHotTheme.date == target_date)
            .order_by(DailyHotTheme.rank.asc().nullslast())
        )
        return list(self.session.execute(query).scalars().all())


class CollectionJobLogRepository:
    """배치 수집 작업 재개·멱등성 체크포인트."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, job_name: str, target_date: date) -> Optional[CollectionJobLog]:
        return self.session.execute(
            select(CollectionJobLog).where(
                CollectionJobLog.job_name == job_name,
                CollectionJobLog.target_date == target_date,
            )
        ).scalar_one_or_none()

    def is_completed(self, job_name: str, target_date: date) -> bool:
        row = self.get(job_name, target_date)
        return bool(row and row.status == "completed")

    def start(self, job_name: str, target_date: date, codes_total: int = 0) -> None:
        """작업 시작 기록(멱등: 기존 행이 있으면 running으로 리셋)."""
        stmt = insert(CollectionJobLog).values(
            job_name=job_name, target_date=target_date,
            status="running", codes_total=codes_total,
            codes_done=0, records_written=0, error=None,
            started_at=datetime.now(), finished_at=None,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_collection_job_name_date",
            set_={
                "status": "running",
                "codes_total": stmt.excluded.codes_total,
                "started_at": stmt.excluded.started_at,
                "error": None,
                "finished_at": None,
            },
        )
        self.session.execute(stmt)

    def finish(
        self, job_name: str, target_date: date, status: str,
        codes_done: int = 0, records_written: int = 0, error: Optional[str] = None,
    ) -> None:
        row = self.get(job_name, target_date)
        if row:
            row.status = status
            row.codes_done = codes_done
            row.records_written = records_written
            row.error = error
            row.finished_at = datetime.now()


class MockForwardFillRepository:
    """모의 포워드 체결 로그 기록/조회."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, data: dict) -> None:
        self.session.add(MockForwardFill(**data))
        self.session.flush()

    def get_for_date(self, target_date: date) -> list[MockForwardFill]:
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time())
        query = (
            select(MockForwardFill)
            .where(MockForwardFill.traded_at >= start, MockForwardFill.traded_at <= end)
            .order_by(MockForwardFill.traded_at)
        )
        return list(self.session.execute(query).scalars().all())


class OrderFlowSnapshotRepository:
    """호가/체결강도 스냅샷 기록/조회."""

    def __init__(self, session: Session):
        self.session = session

    def insert_many(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.session.execute(insert(OrderFlowSnapshot), records)
        return len(records)

    def get_by_code(
        self, code: str, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> pd.DataFrame:
        query = select(OrderFlowSnapshot).where(OrderFlowSnapshot.code == code)
        if start:
            query = query.where(OrderFlowSnapshot.captured_at >= start)
        if end:
            query = query.where(OrderFlowSnapshot.captured_at <= end)
        query = query.order_by(OrderFlowSnapshot.captured_at)
        rows = self.session.execute(query).scalars().all()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "captured_at": r.captured_at, "current_price": r.current_price,
                "exec_strength": float(r.exec_strength) if r.exec_strength is not None else None,
                "total_bid_qty": r.total_bid_qty, "total_ask_qty": r.total_ask_qty,
                "bid_ask_ratio": float(r.bid_ask_ratio) if r.bid_ask_ratio is not None else None,
                "volume": r.volume,
            }
            for r in rows
        ]).set_index("captured_at")
