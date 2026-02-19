"""Dashboard API routes."""

import logging

from fastapi import APIRouter, Depends

from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine
from src.server.kis_client_manager import get_shared_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_summary(engine: TradingEngine = Depends(get_engine)):
    """Get today's trading summary."""
    summary = engine.get_dashboard_summary()

    # Engine not connected → override portfolio with real KIS balance
    if not engine.client:
        client = await get_shared_client()
        if client:
            try:
                balance = await client.get_balance()
                eval_total = balance.total_eval or balance.net_asset or 0
                cash = max(0, balance.total_deposit - balance.purchase_total)
                summary = {
                    **summary,
                    "portfolio": {
                        "total_equity": eval_total,
                        "cash": cash,
                        "positions": len(balance.holdings),
                        "daily_pnl": balance.total_pnl,
                        "daily_pnl_pct": balance.total_pnl_rate,
                        "purchase_total": balance.purchase_total,
                    },
                }
            except Exception as e:
                logger.warning(f"대시보드 잔고 조회 실패: {e}")

    return summary


@router.get("/pnl")
async def get_pnl(engine: TradingEngine = Depends(get_engine)):
    """Get daily P&L data for chart."""
    if engine.client and engine.position_manager:
        return {
            "daily_pnl": int(engine.position_manager.daily_pnl),
            "total_pnl_pct": round(engine.position_manager.total_pnl_pct, 2),
            "total_equity": int(engine.position_manager.total_equity),
            "cash": int(engine.position_manager.cash),
            "trades": engine.get_trades_today(),
        }

    # Engine not connected → fetch from shared KIS client
    client = await get_shared_client()
    if client:
        try:
            balance = await client.get_balance()
            eval_total = balance.total_eval or balance.net_asset or 0
            cash = max(0, balance.total_deposit - balance.purchase_total)
            return {
                "daily_pnl": balance.total_pnl,
                "total_pnl_pct": balance.total_pnl_rate,
                "total_equity": eval_total,
                "cash": cash,
                "trades": [],
            }
        except Exception as e:
            logger.warning(f"PnL 잔고 조회 실패: {e}")

    return {"daily_pnl": 0, "total_pnl_pct": 0, "total_equity": 0, "cash": 0, "trades": []}
