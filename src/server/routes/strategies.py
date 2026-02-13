"""Strategy management API routes."""

from fastapi import APIRouter, Depends, HTTPException

from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("")
async def get_strategies(engine: TradingEngine = Depends(get_engine)):
    """Get all strategy statuses."""
    if not engine.strategy_runner:
        return {"strategies": []}

    return {"strategies": engine.strategy_runner.get_status()}


@router.get("/{name}/detail")
async def get_strategy_detail(
    name: str,
    engine: TradingEngine = Depends(get_engine),
):
    """Get detailed info for a specific strategy + near entry stocks."""
    if not engine.strategy_runner:
        raise HTTPException(status_code=503, detail="엔진 미초기화")

    names = engine.strategy_runner.strategy_names
    if name not in names:
        raise HTTPException(status_code=404, detail=f"전략 없음: {name}")

    return engine.get_strategy_detail(name)


@router.put("/{name}/toggle")
async def toggle_strategy(
    name: str,
    engine: TradingEngine = Depends(get_engine),
):
    """Toggle a strategy on/off."""
    if not engine.strategy_runner:
        raise HTTPException(status_code=503, detail="엔진이 실행 중이 아닙니다")

    names = engine.strategy_runner.strategy_names
    if name not in names:
        raise HTTPException(status_code=404, detail=f"전략 없음: {name}")

    new_state = engine.strategy_runner.toggle_strategy(name)
    return {"name": name, "enabled": new_state}


@router.put("/all/disable")
async def disable_all_strategies(
    engine: TradingEngine = Depends(get_engine),
):
    """Disable all strategies at once."""
    if not engine.strategy_runner:
        raise HTTPException(status_code=503, detail="엔진이 실행 중이 아닙니다")

    disabled = []
    for name in engine.strategy_runner.strategy_names:
        if engine.strategy_runner.is_enabled(name):
            engine.strategy_runner.toggle_strategy(name)
            disabled.append(name)

    return {"disabled": disabled, "count": len(disabled)}
