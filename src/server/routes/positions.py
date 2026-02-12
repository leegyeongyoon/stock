"""Position management API routes."""

from fastapi import APIRouter, Depends

from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("")
async def get_positions(engine: TradingEngine = Depends(get_engine)):
    """Get all current positions."""
    return {"positions": engine.get_positions()}


@router.get("/holdings")
async def get_holdings(engine: TradingEngine = Depends(get_engine)):
    """보유종목 상세 (현재가, 수익률, 시장가치 등)."""
    holdings = engine.get_holdings_detail()
    total_cost = sum(h["cost_basis"] for h in holdings)
    total_market = sum(h["market_value"] for h in holdings)
    total_pnl = total_market - total_cost

    return {
        "holdings": holdings,
        "summary": {
            "count": len(holdings),
            "total_cost": int(round(total_cost)),
            "total_market_value": int(round(total_market)),
            "total_unrealized_pnl": int(round(total_pnl)),
            "total_unrealized_pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0,
        },
    }


@router.get("/summary")
async def get_position_summary(engine: TradingEngine = Depends(get_engine)):
    """Get position summary stats."""
    if not engine.position_manager:
        return {"count": 0, "total_value": 0, "unrealized_pnl": 0}

    positions = engine.position_manager.positions
    total_value = sum(p.market_value for p in positions.values())
    unrealized_pnl = sum(p.unrealized_pnl for p in positions.values())

    return {
        "count": len(positions),
        "total_value": int(total_value),
        "unrealized_pnl": int(unrealized_pnl),
    }
