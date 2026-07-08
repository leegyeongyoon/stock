"""SQLAlchemy database models."""

from datetime import date, datetime, time
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
    Time,
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
    """Live position tracking (서버 재시작 시 전략 이름 보존용)."""

    __tablename__ = "live_positions"
    __table_args__ = (
        UniqueConstraint("stock_code", name="uq_live_pos_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    stock_name: Mapped[Optional[str]] = mapped_column(String(50))
    strategy_name: Mapped[Optional[str]] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    stop_loss_pct: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    take_profit_pct: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    stop_loss_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    take_profit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    partial_sold: Mapped[bool] = mapped_column(Boolean, default=False)
    original_quantity: Mapped[Optional[int]] = mapped_column(Integer)

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


# ── 단타 재설계: 데이터 기반 모델 ──────────────────────────────────
# 모두 insert/upsert 전용(불변 스냅샷). 같은 (date,...) 재수집은 멱등 갱신.


class OHLCVIntraday(Base):
    """분봉 데이터. 기존 raw 테이블(scripts/fetch_top_stocks_data.py)을 ORM에 매핑.

    컬럼/제약은 기존 테이블과 정확히 일치시켜 create_all 충돌을 피한다.
    1분봉은 interval='1m', 기존 5분봉은 '5m'로 공존한다.
    """

    __tablename__ = "ohlcv_intraday"
    __table_args__ = (
        UniqueConstraint("code", "datetime", "interval", name="uq_ohlcv_intraday_code_dt_iv"),
        Index("idx_intraday_code", "code"),
        Index("idx_intraday_datetime", "datetime"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    close: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    interval: Mapped[str] = mapped_column(String(10), nullable=False, default="5m")

    def __repr__(self) -> str:
        return f"<OHLCVIntraday(code={self.code}, dt={self.datetime}, iv={self.interval})>"


class DailyMovers(Base):
    """생존편향 없는 '그날의 유니버스' 스냅샷.

    그날 어떤 스캐너 규칙(급등/거래대금/거래량급증/상한가)으로든 포착된 모든 종목을
    하루 1행으로 기록한다. 백테스트가 "그날 아침 스캐너가 띄웠을 종목"을 재구성할 수 있게 한다.
    """

    __tablename__ = "daily_movers"
    __table_args__ = (
        UniqueConstraint("date", "code", name="uq_daily_movers_date_code"),
        Index("idx_daily_movers_date", "date"),
        Index("idx_daily_movers_change", "date", "change_rate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[Optional[str]] = mapped_column(String(10))  # KOSPI/KOSDAQ

    open: Mapped[Optional[int]] = mapped_column(Integer)
    high: Mapped[Optional[int]] = mapped_column(Integer)
    low: Mapped[Optional[int]] = mapped_column(Integer)
    close: Mapped[Optional[int]] = mapped_column(Integer)
    change_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))  # 당일 등락률(%)
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    value: Mapped[Optional[int]] = mapped_column(BigInteger)  # 거래대금
    market_cap: Mapped[Optional[int]] = mapped_column(BigInteger)  # 시가총액
    volume_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))  # 당일/20일평균 거래량

    is_limit_up: Mapped[bool] = mapped_column(Boolean, default=False)
    is_limit_down: Mapped[bool] = mapped_column(Boolean, default=False)

    rank_change: Mapped[Optional[int]] = mapped_column(Integer)  # 등락률 순위
    rank_value: Mapped[Optional[int]] = mapped_column(Integer)  # 거래대금 순위
    rank_volume_ratio: Mapped[Optional[int]] = mapped_column(Integer)  # 거래량급증 순위

    flags: Mapped[Optional[list]] = mapped_column(JSONB)  # ["top_gainer","value_top","vol_surge","limit_up"]
    theme_tags: Mapped[Optional[list]] = mapped_column(JSONB)  # 후속 join으로 채움(nullable)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:
        return f"<DailyMovers(date={self.date}, code={self.code}, chg={self.change_rate})>"


class LimitEvent(Base):
    """상한가/하한가 이벤트 + 최초 도달 시각(상따 현실성/체결불가 모델의 핵심)."""

    __tablename__ = "limit_events"
    __table_args__ = (
        UniqueConstraint("date", "code", "event_type", name="uq_limit_events_date_code_type"),
        Index("idx_limit_events_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(10), nullable=False)  # limit_up/limit_down
    limit_price: Mapped[Optional[int]] = mapped_column(Integer)
    first_hit_time: Mapped[Optional[time]] = mapped_column(Time)  # 분봉 확인 시에만
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    closed_at_limit: Mapped[bool] = mapped_column(Boolean, default=False)  # 종가=상한가(굳히기)
    source: Mapped[str] = mapped_column(String(20), default="daily_inferred")  # daily_inferred/minute_confirmed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:
        return f"<LimitEvent(date={self.date}, code={self.code}, type={self.event_type})>"


class StockTheme(Base):
    """일자별 테마 소속(네이버 크롤 기반, 전진 수집 전용)."""

    __tablename__ = "stock_themes"
    __table_args__ = (
        UniqueConstraint("date", "code", "theme_code", name="uq_stock_themes_date_code_theme"),
        Index("idx_stock_themes_date", "date"),
        Index("idx_stock_themes_theme", "date", "theme_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    theme_code: Mapped[str] = mapped_column(String(30), nullable=False)
    theme_name: Mapped[Optional[str]] = mapped_column(String(100))
    is_leader: Mapped[bool] = mapped_column(Boolean, default=False)  # 대장주
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:
        return f"<StockTheme(date={self.date}, code={self.code}, theme={self.theme_name})>"


class DailyHotTheme(Base):
    """일자별 핫테마 리더보드 스냅샷."""

    __tablename__ = "daily_hot_themes"
    __table_args__ = (
        UniqueConstraint("date", "theme_code", name="uq_daily_hot_themes_date_theme"),
        Index("idx_daily_hot_themes_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    theme_code: Mapped[str] = mapped_column(String(30), nullable=False)
    theme_name: Mapped[Optional[str]] = mapped_column(String(100))
    rank: Mapped[Optional[int]] = mapped_column(Integer)
    change_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))  # 테마 평균 등락률
    up_count: Mapped[Optional[int]] = mapped_column(Integer)
    down_count: Mapped[Optional[int]] = mapped_column(Integer)
    stock_count: Mapped[Optional[int]] = mapped_column(Integer)
    leader_code: Mapped[Optional[str]] = mapped_column(String(20))
    leader_name: Mapped[Optional[str]] = mapped_column(String(100))
    total_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    news_hot_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    sentiment: Mapped[Optional[str]] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:
        return f"<DailyHotTheme(date={self.date}, theme={self.theme_name}, rank={self.rank})>"


class MockForwardFill(Base):
    """모의 포워드 검증용: 신호의 의도 체결 vs 실제(모의) 체결 로그.

    백테스트 가정과 모의 실측의 슬리피지/체결률/승률을 비교(실거래 진입 게이트)하기 위함.
    라이브 스키마(live_trades)를 건드리지 않도록 별도 테이블로 둔다.
    """

    __tablename__ = "mock_forward_fills"
    __table_args__ = (
        Index("idx_mock_fills_date", "traded_at"),
        Index("idx_mock_fills_tier", "tier"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    traded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)  # BALANCED/AGGRESSIVE
    side: Mapped[str] = mapped_column(String(4), nullable=False)   # buy/sell
    strategy_name: Mapped[Optional[str]] = mapped_column(String(50))
    theme: Mapped[Optional[str]] = mapped_column(String(100))

    intended_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    intended_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    actual_qty: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[Optional[str]] = mapped_column(String(20))  # filled/partial/blocked/failed
    is_win: Mapped[Optional[bool]] = mapped_column(Boolean)     # 청산 결과(있으면)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:
        return f"<MockForwardFill(code={self.code}, tier={self.tier}, side={self.side})>"


class OrderFlowSnapshot(Base):
    """호가/체결강도 스냅샷 — OHLC 봉에 없는 '오를 놈' 신호(전진 수집).

    그리드 전수 검색 결과 OHLC만으론 엣지가 없었음. 체결강도/호가잔량비가
    상승 지속을 예측하는지 검증하기 위해 장중 폴링으로 모은다.
    """

    __tablename__ = "orderflow_snapshots"
    __table_args__ = (
        Index("idx_orderflow_code_dt", "code", "captured_at"),
        Index("idx_orderflow_dt", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_price: Mapped[Optional[int]] = mapped_column(Integer)
    exec_strength: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))   # 체결강도
    total_bid_qty: Mapped[Optional[int]] = mapped_column(BigInteger)          # 총매수호가잔량
    total_ask_qty: Mapped[Optional[int]] = mapped_column(BigInteger)          # 총매도호가잔량
    bid_ask_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))  # 매수/매도 잔량비
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    book: Mapped[Optional[dict]] = mapped_column(JSONB)  # 10단계 호가(옵션)

    def __repr__(self) -> str:
        return f"<OrderFlowSnapshot(code={self.code}, at={self.captured_at}, str={self.exec_strength})>"


class CollectionJobLog(Base):
    """배치 수집 작업 재개·멱등성 체크포인트."""

    __tablename__ = "collection_job_logs"
    __table_args__ = (
        UniqueConstraint("job_name", "target_date", name="uq_collection_job_name_date"),
        Index("idx_collection_job_date", "target_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(50), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/completed/failed/partial
    codes_total: Mapped[int] = mapped_column(Integer, default=0)
    codes_done: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return f"<CollectionJobLog(job={self.job_name}, date={self.target_date}, status={self.status})>"
