"""FastAPI dependency injection - shared engine, scheduler and DB access."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine.scheduler import TradingScheduler

from src.engine.trading_engine import TradingEngine

_engine: TradingEngine | None = None
_scheduler: "TradingScheduler | None" = None


def get_engine() -> TradingEngine:
    """Get the global TradingEngine instance."""
    global _engine
    if _engine is None:
        _engine = TradingEngine()
    return _engine


def set_engine(engine: TradingEngine) -> None:
    """Set the global TradingEngine instance (used in app startup)."""
    global _engine
    _engine = engine


def get_scheduler() -> "TradingScheduler | None":
    """Get the global TradingScheduler instance."""
    return _scheduler


def set_scheduler(scheduler: "TradingScheduler") -> None:
    """Set the global TradingScheduler instance."""
    global _scheduler
    _scheduler = scheduler
