"""Dashboard API routes."""

from fastapi import APIRouter, Depends

from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_summary(engine: TradingEngine = Depends(get_engine)):
    """Get today's trading summary."""
    return engine.get_dashboard_summary()


@router.get("/pnl")
async def get_pnl(engine: TradingEngine = Depends(get_engine)):
    """Get daily P&L data for chart."""
    if not engine.position_manager:
        return {"daily_pnl": 0, "total_pnl_pct": 0, "trades": []}

    return {
        "daily_pnl": int(engine.position_manager.daily_pnl),
        "total_pnl_pct": round(engine.position_manager.total_pnl_pct, 2),
        "total_equity": int(engine.position_manager.total_equity),
        "cash": int(engine.position_manager.cash),
        "trades": engine.get_trades_today(),
    }
