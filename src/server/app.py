"""FastAPI application - main entry point for the web server."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine, set_engine
from src.server.routes import analysis, dashboard, orders, positions, strategies, system, themes
from src.server.websocket_hub import hub


async def _init_balance_background(engine):
    """백그라운드에서 초기 잔고 조회 (서버 시작 차단 방지)"""
    try:
        await asyncio.wait_for(engine.init_balance(), timeout=30.0)
    except asyncio.TimeoutError:
        logger.warning("초기 잔고 조회 타임아웃 (30초) - 기본값 사용")
    except Exception as e:
        logger.warning(f"초기 잔고 조회 실패: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    engine = TradingEngine()
    set_engine(engine)

    # Wire engine events → WebSocket hub
    engine.on_signal(lambda s: hub.broadcast_signal({
        "stock_code": s.stock_code,
        "strategy_name": s.strategy_name,
        "reason": s.reason,
        "timestamp": s.timestamp.isoformat(),
    }))
    engine.on_order(lambda data: hub.broadcast_order(data))
    engine.on_position(lambda data: hub.broadcast_position(data))
    engine.on_system(lambda data: hub.broadcast_system(data))

    # Start periodic PnL push
    hub.start_pnl_push(lambda: engine.position_manager.get_summary() if engine.position_manager else {})

    # 서버 시작 시 KIS 잔고 조회 - 백그라운드에서 실행 (서버 시작 차단 방지)
    asyncio.create_task(_init_balance_background(engine))

    logger.info("FastAPI 서버 시작")
    yield

    # Shutdown
    await engine.stop()
    logger.info("FastAPI 서버 종료")


app = FastAPI(
    title="Stock Auto-Trading Server",
    description="한국 주식 5분봉 인트라데이 자동매매 시스템",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3007",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "https://stock.honbabnono.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routes
app.include_router(dashboard.router)
app.include_router(positions.router)
app.include_router(orders.router)
app.include_router(strategies.router)
app.include_router(analysis.router)
app.include_router(system.router)
app.include_router(themes.router)


# WebSocket endpoints
@app.websocket("/ws/positions")
async def ws_positions(websocket: WebSocket):
    await hub.positions.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.positions.disconnect(websocket)


@app.websocket("/ws/orders")
async def ws_orders(websocket: WebSocket):
    await hub.orders.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.orders.disconnect(websocket)


@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    await hub.signals.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.signals.disconnect(websocket)


@app.websocket("/ws/pnl")
async def ws_pnl(websocket: WebSocket):
    await hub.pnl.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.pnl.disconnect(websocket)


@app.websocket("/ws/system")
async def ws_system(websocket: WebSocket):
    await hub.system.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.system.disconnect(websocket)
