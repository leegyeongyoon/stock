"""System control API routes."""

from fastapi import APIRouter, Depends, HTTPException

from src.engine.trading_engine import EngineState, TradingEngine
from src.server.dependencies import get_engine, get_scheduler

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
async def health_check(engine: TradingEngine = Depends(get_engine)):
    """System health check."""
    return {
        "status": "ok",
        "engine_state": engine.state.value,
    }


@router.post("/start")
async def start_trading(engine: TradingEngine = Depends(get_engine)):
    """Start the trading engine."""
    if engine.state == EngineState.RUNNING:
        return {"message": "이미 실행 중입니다", "state": engine.state.value}

    try:
        await engine.start()
        return {"message": "엔진 시작", "state": engine.state.value}
    except Exception as e:
        engine.add_log("START_FAILED", f"엔진 시작 실패: {e}", severity="ERROR")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_trading(engine: TradingEngine = Depends(get_engine)):
    """Stop the trading engine (graceful)."""
    await engine.stop()
    return {"message": "엔진 중지", "state": engine.state.value}


@router.post("/emergency-stop")
async def emergency_stop(engine: TradingEngine = Depends(get_engine)):
    """Emergency stop - close all positions immediately."""
    await engine.emergency_stop()
    return {"message": "긴급 정지 완료", "state": engine.state.value}


@router.get("/status")
async def get_status(engine: TradingEngine = Depends(get_engine)):
    """Get detailed system status."""
    result = {
        "engine_state": engine.state.value,
        "universe_count": engine.universe.count if engine.universe else 0,
    }

    if engine.data_manager:
        result["data_bars"] = {
            "total_stocks_with_data": sum(
                1 for c in (engine.universe.codes if engine.universe else [])
                if engine.data_manager.get_bar_count(c) > 0
            ),
        }

    if engine.risk_manager:
        result["risk"] = engine.risk_manager.get_risk_status()

    if engine.ws:
        result["ws_subscriptions"] = engine.ws.subscribed_count

    return result


@router.get("/events")
async def get_events(
    limit: int = 50,
    engine: TradingEngine = Depends(get_engine),
):
    """Get recent system events/logs."""
    return {"events": engine.get_event_log(limit=limit)}


# ── Scheduler ────────────────────────────────────────────


@router.get("/scheduler")
async def get_scheduler_status():
    """Get auto-scheduler status."""
    scheduler = get_scheduler()
    if not scheduler:
        return {"enabled": False, "scheduler_running": False}
    return scheduler.get_status()


@router.post("/scheduler/toggle")
async def toggle_scheduler():
    """Toggle auto-scheduler on/off."""
    scheduler = get_scheduler()
    if not scheduler:
        raise HTTPException(status_code=503, detail="스케줄러가 초기화되지 않았습니다")
    scheduler.enabled = not scheduler.enabled
    return {
        "message": f"스케줄러 {'활성화' if scheduler.enabled else '비활성화'}",
        "enabled": scheduler.enabled,
    }
