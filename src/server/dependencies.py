"""FastAPI dependency injection - shared engine and DB access."""

from src.engine.trading_engine import TradingEngine

_engine: TradingEngine | None = None


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
