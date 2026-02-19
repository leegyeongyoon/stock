"""Position management API routes."""

import logging

from fastapi import APIRouter, Depends

from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine
from src.server.kis_client_manager import get_shared_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["positions"])


def _build_holdings_summary(holdings: list[dict]) -> dict:
    """Build summary stats from a list of holdings dicts."""
    total_cost = sum(h["cost_basis"] for h in holdings)
    total_market = sum(h["market_value"] for h in holdings)
    total_pnl = total_market - total_cost
    return {
        "count": len(holdings),
        "total_cost": int(round(total_cost)),
        "total_market_value": int(round(total_market)),
        "total_unrealized_pnl": int(round(total_pnl)),
        "total_unrealized_pnl_pct": (
            round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0
        ),
    }


async def _get_holdings_from_kis() -> list[dict]:
    """Fetch holdings from KIS API when engine is not running."""
    client = await get_shared_client()
    if not client:
        return []

    try:
        balance = await client.get_balance()
        return [
            {
                "stock_code": h.stock_code,
                "stock_name": h.stock_name,
                "strategy_name": "기존보유",
                "quantity": h.quantity,
                "avg_price": int(h.avg_price),
                "current_price": h.current_price,
                "unrealized_pnl": h.pnl,
                "unrealized_pnl_pct": round(h.pnl_rate, 2),
                "stop_loss_price": 0,
                "take_profit_price": 0,
                "entry_time": "",
                "market_value": h.eval_amount,
                "cost_basis": int(h.avg_price * h.quantity),
                "pnl_amount": h.pnl,
                "pnl_pct": round(h.pnl_rate, 2),
            }
            for h in balance.holdings
        ]
    except Exception as e:
        logger.warning(f"KIS 보유종목 조회 실패: {e}")
        return []


@router.get("")
async def get_positions(engine: TradingEngine = Depends(get_engine)):
    """Get all current positions."""
    if engine.client:
        positions = engine.get_positions()
        if positions:
            return {"positions": positions}

    # Engine not connected → fetch from KIS
    kis_holdings = await _get_holdings_from_kis()
    return {"positions": kis_holdings}


@router.get("/holdings")
async def get_holdings(engine: TradingEngine = Depends(get_engine)):
    """보유종목 상세 (현재가, 수익률, 시장가치 등)."""
    if engine.client and engine.position_manager:
        holdings = engine.get_holdings_detail()
    else:
        holdings = await _get_holdings_from_kis()

    return {"holdings": holdings, "summary": _build_holdings_summary(holdings)}


@router.get("/summary")
async def get_position_summary(engine: TradingEngine = Depends(get_engine)):
    """Get position summary stats."""
    if engine.client and engine.position_manager:
        positions = engine.position_manager.positions
        total_value = sum(p.market_value for p in positions.values())
        unrealized_pnl = sum(p.unrealized_pnl for p in positions.values())

        return {
            "count": len(positions),
            "total_value": int(total_value),
            "unrealized_pnl": int(unrealized_pnl),
        }

    # Engine not connected → fetch from KIS
    client = await get_shared_client()
    if client:
        try:
            balance = await client.get_balance()
            eval_total = sum(h.eval_amount for h in balance.holdings)
            pnl_total = sum(h.pnl for h in balance.holdings)

            return {
                "count": len(balance.holdings),
                "total_value": eval_total,
                "unrealized_pnl": pnl_total,
            }
        except Exception as e:
            logger.warning(f"포지션 요약 조회 실패: {e}")

    return {"count": 0, "total_value": 0, "unrealized_pnl": 0}
