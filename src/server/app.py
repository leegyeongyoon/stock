"""FastAPI application - main entry point for the web server."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.engine.trading_engine import TradingEngine
from src.engine.scheduler import TradingScheduler
from src.server.dependencies import get_engine, get_scheduler, set_engine, set_scheduler
from src.server.routes import analysis, dashboard, orders, positions, strategies, system, themes, stockking
from src.server.websocket_hub import hub
from src.analysis.theme_analyzer import get_theme_analyzer


async def _warmup_theme_cache():
    """서버 시작 후 테마 분석 캐시를 미리 채움."""
    await asyncio.sleep(3)  # 서버 안정화 대기
    try:
        analyzer = get_theme_analyzer()
        logger.info("테마 캐시 워밍업 시작...")
        # 순차 실행 (외부 API rate limit 방지)
        await analyzer.get_market_analysis()
        await analyzer.analyze_news_for_themes(["AI", "반도체", "2차전지", "로봇", "바이오"])
        await analyzer.get_theme_ranking(top_n=30)
        await analyzer.get_hot_themes_by_period(days=1, top_n=20)
        logger.info("테마 캐시 워밍업 완료")
    except Exception as e:
        logger.warning(f"테마 캐시 워밍업 실패: {e}")


async def _periodic_cache_refresh():
    """4분마다 테마 캐시를 백그라운드에서 갱신."""
    await asyncio.sleep(300)  # 첫 워밍업 후 5분 뒤부터
    while True:
        try:
            now = datetime.now().time()
            if time(8, 50) <= now <= time(15, 40):  # 장 시간에만
                analyzer = get_theme_analyzer()
                logger.info("테마 캐시 백그라운드 갱신 시작...")
                await analyzer.get_market_analysis(force_refresh=True)
                await analyzer.analyze_news_for_themes(["AI", "반도체", "2차전지", "로봇", "바이오"])
                await analyzer.get_theme_ranking(top_n=30, force_refresh=True)
                await analyzer.get_hot_themes_by_period(days=1, top_n=20, force_refresh=True)
                logger.info("테마 캐시 백그라운드 갱신 완료")
        except Exception as e:
            logger.warning(f"테마 캐시 갱신 실패: {e}")
        await asyncio.sleep(240)  # 4분 간격


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

    # init_balance 제거: _sync_balance()가 engine.start()에서 정확하게 처리
    # (init_balance와 _sync_balance 동시 실행 시 레이스 컨디션으로 현금 이중 계산 버그 발생)

    # Auto-scheduler: 장 시간 자동 시작/종료
    scheduler = TradingScheduler(engine)
    set_scheduler(scheduler)
    scheduler.start()

    # 테마 캐시 워밍업 + 주기적 갱신
    warmup_task = asyncio.create_task(_warmup_theme_cache())
    refresh_task = asyncio.create_task(_periodic_cache_refresh())

    logger.info("FastAPI 서버 시작 (스케줄러 활성화)")
    yield

    # Shutdown
    warmup_task.cancel()
    refresh_task.cancel()
    scheduler.stop()
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
app.include_router(stockking.router)


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
