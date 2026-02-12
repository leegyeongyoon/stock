"""SQLAlchemy database models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Stock(Base):
    """Stock information model."""

    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False)  # KOSPI/KOSDAQ
    sector: Mapped[Optional[str]] = mapped_column(String(50))
    market_cap: Mapped[Optional[int]] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    # Relationships
    ohlcv_daily: Mapped[list["OHLCVDaily"]] = relationship(back_populates="stock")
    investor_trading: Mapped[list["InvestorTrading"]] = relationship(back_populates="stock")
    trades: Mapped[list["Trade"]] = relationship(back_populates="stock")

    def __repr__(self) -> str:
        return f"<Stock(code={self.code}, name={self.name}, market={self.market})>"


class OHLCVDaily(Base):
    """Daily OHLCV data model."""

    __tablename__ = "ohlcv_daily"
    __table_args__ = (
        UniqueConstraint("code", "date", name="uq_ohlcv_daily_code_date"),
        Index("idx_ohlcv_daily_date", "date"),
        Index("idx_ohlcv_daily_code", "code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[int] = mapped_column(Integer, nullable=False)
    high: Mapped[int] = mapped_column(Integer, nullable=False)
    low: Mapped[int] = mapped_column(Integer, nullable=False)
    close: Mapped[int] = mapped_column(Integer, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value: Mapped[Optional[int]] = mapped_column(BigInteger)  # 거래대금
    change_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))

    # Relationship
    stock: Mapped["Stock"] = relationship(back_populates="ohlcv_daily")

    def __repr__(self) -> str:
        return f"<OHLCVDaily(code={self.code}, date={self.date}, close={self.close})>"


class InvestorTrading(Base):
    """Investor trading data (institutional, foreign, individual)."""

    __tablename__ = "investor_trading"
    __table_args__ = (
        UniqueConstraint("code", "date", name="uq_investor_trading_code_date"),
        Index("idx_investor_trading_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)

    # 기관
    institution_buy: Mapped[Optional[int]] = mapped_column(BigInteger)
    institution_sell: Mapped[Optional[int]] = mapped_column(BigInteger)

    # 외국인
    foreign_buy: Mapped[Optional[int]] = mapped_column(BigInteger)
    foreign_sell: Mapped[Optional[int]] = mapped_column(BigInteger)

    # 개인
    individual_buy: Mapped[Optional[int]] = mapped_column(BigInteger)
    individual_sell: Mapped[Optional[int]] = mapped_column(BigInteger)

    # Relationship
    stock: Mapped["Stock"] = relationship(back_populates="investor_trading")

    @property
    def institution_net(self) -> int:
        """기관 순매수."""
        buy = self.institution_buy or 0
        sell = self.institution_sell or 0
        return buy - sell

    @property
    def foreign_net(self) -> int:
        """외인 순매수."""
        buy = self.foreign_buy or 0
        sell = self.foreign_sell or 0
        return buy - sell

    def __repr__(self) -> str:
        return f"<InvestorTrading(code={self.code}, date={self.date})>"


class BacktestResult(Base):
    """Backtest result summary."""

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    run_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Performance metrics
    initial_capital: Mapped[int] = mapped_column(BigInteger, default=100_000_000)
    final_capital: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    cagr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    sharpe_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    max_drawdown: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    win_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    profit_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    total_trades: Mapped[Optional[int]] = mapped_column(Integer)

    # Strategy configuration
    config: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Relationships
    trades: Mapped[list["Trade"]] = relationship(back_populates="backtest_result")

    def __repr__(self) -> str:
        return f"<BacktestResult(id={self.id}, strategy={self.strategy_name}, return={self.total_return})>"


class Trade(Base):
    """Individual trade record."""

    __tablename__ = "trades"
    __table_args__ = (Index("idx_trades_strategy", "strategy_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("backtest_results.id")
    )
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)

    # Entry
    entry_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    entry_price: Mapped[int] = mapped_column(Integer, nullable=False)

    # Exit
    exit_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    exit_price: Mapped[Optional[int]] = mapped_column(Integer)

    # Position
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    position_value: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # P&L
    pnl: Mapped[Optional[int]] = mapped_column(Integer)  # 손익금액
    pnl_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))  # 손익률
    commission: Mapped[Optional[int]] = mapped_column(Integer)  # 수수료
    tax: Mapped[Optional[int]] = mapped_column(Integer)  # 세금

    # Metadata
    entry_reason: Mapped[Optional[str]] = mapped_column(Text)
    exit_reason: Mapped[Optional[str]] = mapped_column(Text)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)  # 실전/백테스트 구분

    # Relationships
    backtest_result: Mapped[Optional["BacktestResult"]] = relationship(back_populates="trades")
    stock: Mapped["Stock"] = relationship(back_populates="trades")

    @property
    def is_winner(self) -> bool:
        """Check if trade was profitable."""
        return (self.pnl or 0) > 0

    @property
    def holding_days(self) -> Optional[int]:
        """Calculate holding period in days."""
        if self.exit_date:
            return (self.exit_date - self.entry_date).days
        return None

    def __repr__(self) -> str:
        return f"<Trade(id={self.id}, code={self.code}, pnl_rate={self.pnl_rate})>"


class Signal(Base):
    """Trading signal log."""

    __tablename__ = "signals"
    __table_args__ = (Index("idx_signals_date", "signal_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY/SELL
    signal_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"<Signal(strategy={self.strategy_name}, code={self.code}, type={self.signal_type})>"


# ── Live Trading Models ────────────────────────────────────────


class LiveOrder(Base):
    """Live order history."""

    __tablename__ = "live_orders"
    __table_args__ = (
        Index("idx_live_orders_status", "status"),
        Index("idx_live_orders_stock", "stock_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(50))
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    filled_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, onupdate=datetime.now
    )

    # Relationships
    live_trades: Mapped[list["LiveTrade"]] = relationship(back_populates="order")

    def __repr__(self) -> str:
        return f"<LiveOrder(order_id={self.order_id}, stock={self.stock_code}, status={self.status})>"


class LivePosition(Base):
    """Live position tracking."""

    __tablename__ = "live_positions"
    __table_args__ = (
        UniqueConstraint("stock_code", "strategy_name", name="uq_live_pos_code_strategy"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    stop_loss_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    take_profit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<LivePosition(stock={self.stock_code}, qty={self.quantity}, strategy={self.strategy_name})>"


class LiveTrade(Base):
    """Completed live trade record."""

    __tablename__ = "live_trades"
    __table_args__ = (
        Index("idx_live_trades_stock", "stock_code"),
        Index("idx_live_trades_date", "traded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("live_orders.order_id")
    )
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    stock_name: Mapped[Optional[str]] = mapped_column(String(50))
    strategy_name: Mapped[Optional[str]] = mapped_column(String(50))
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    pnl_pct: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    exit_reason: Mapped[Optional[str]] = mapped_column(String(20))
    entry_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    order: Mapped[Optional["LiveOrder"]] = relationship(back_populates="live_trades")

    def __repr__(self) -> str:
        return f"<LiveTrade(stock={self.stock_code}, side={self.side}, pnl={self.pnl})>"


class PortfolioSnapshot(Base):
    """Daily portfolio snapshot."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    total_equity: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    daily_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    daily_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
    total_trades: Mapped[Optional[int]] = mapped_column(Integer)
    win_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    def __repr__(self) -> str:
        return f"<PortfolioSnapshot(date={self.date}, equity={self.total_equity})>"


class SystemEvent(Base):
    """System event log with JSONB metadata."""

    __tablename__ = "system_events"
    __table_args__ = (
        Index("idx_system_events_type", "event_type"),
        Index("idx_system_events_date", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)

    def __repr__(self) -> str:
        return f"<SystemEvent(type={self.event_type}, severity={self.severity})>"


class StrategyPerformance(Base):
    """Daily strategy performance summary."""

    __tablename__ = "strategy_performance"
    __table_args__ = (
        UniqueConstraint("date", "strategy_name", name="uq_strategy_perf_date_name"),
        Index("idx_strategy_perf_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), default=0)

    def __repr__(self) -> str:
        return f"<StrategyPerformance(date={self.date}, strategy={self.strategy_name}, pnl={self.pnl})>"
