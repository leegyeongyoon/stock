"""Order management API routes."""

from fastapi import APIRouter, Depends, HTTPException

from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("")
async def get_orders(engine: TradingEngine = Depends(get_engine)):
    """Get all orders (open + filled)."""
    if not engine.order_manager:
        return {"orders": []}

    orders = []
    for o in engine.order_manager.open_orders:
        orders.append({
            "order_id": o.order_id,
            "stock_code": o.stock_code,
            "side": o.side.value,
            "quantity": o.quantity,
            "filled_quantity": o.filled_quantity,
            "price": o.price,
            "status": o.status.value,
            "strategy_name": o.strategy_name,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        })

    return {"orders": orders}


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    engine: TradingEngine = Depends(get_engine),
):
    """Cancel a specific open order."""
    if not engine.order_manager:
        raise HTTPException(status_code=503, detail="엔진이 실행 중이 아닙니다")

    success = await engine.order_manager.cancel_order(order_id)
    if not success:
        raise HTTPException(status_code=400, detail="주문 취소 실패")

    return {"success": True, "order_id": order_id}
