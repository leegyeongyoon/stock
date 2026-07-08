"""Market-hours auto scheduler for TradingEngine.

Automatically starts the engine before market open and stops after close.
Schedule (KST, weekdays only):
    08:30  Auto-start engine (경윤 + DD 전략 포함)
    15:35  Auto-stop engine
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

# 거래일/장중 판정은 경량 모듈로 분리(데이터 수집 스크립트가 엔진 스택을 끌어오지 않게).
# 하위호환: 기존 `from src.engine.scheduler import is_trading_day/KOREAN_HOLIDAYS` 유지.
from src.utils.trading_calendar import (  # noqa: F401
    KOREAN_HOLIDAYS,
    is_market_hours,
    is_trading_day,
)

if TYPE_CHECKING:
    from src.engine.trading_engine import TradingEngine


class TradingScheduler:
    """APScheduler-based auto start/stop for TradingEngine."""

    def __init__(self, engine: TradingEngine):
        self._engine = engine
        self._scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
        self._enabled = True

        # 08:30 월-금: 엔진 자동 시작 (경윤 + DD 전략 포함)
        self._scheduler.add_job(
            self._auto_start,
            CronTrigger(hour=8, minute=30, day_of_week="mon-fri", timezone="Asia/Seoul"),
            id="auto_start",
            name="장전 엔진 자동 시작",
            replace_existing=True,
        )

        # 15:35 월-금: 엔진 자동 종료
        self._scheduler.add_job(
            self._auto_stop,
            CronTrigger(hour=15, minute=35, day_of_week="mon-fri", timezone="Asia/Seoul"),
            id="auto_stop",
            name="장후 엔진 자동 종료",
            replace_existing=True,
        )

        logger.info("TradingScheduler 초기화 완료 (08:30 시작 / 15:35 종료)")

    def start(self) -> None:
        """Start the scheduler."""
        self._scheduler.start()
        logger.info("TradingScheduler 시작됨")

        # 서버 시작 시점이 장 시간 내이면 즉시 엔진 시작
        asyncio.get_event_loop().create_task(self._check_midday_start())

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("TradingScheduler 종료됨")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        logger.info(f"TradingScheduler {'활성화' if value else '비활성화'}")

    def get_status(self) -> dict:
        """Get scheduler status for API."""
        now = datetime.now()
        next_start = None
        next_stop = None

        for job in self._scheduler.get_jobs():
            nrt = job.next_run_time
            if nrt:
                if job.id == "auto_start":
                    next_start = nrt.isoformat()
                elif job.id == "auto_stop":
                    next_stop = nrt.isoformat()

        return {
            "enabled": self._enabled,
            "scheduler_running": self._scheduler.running,
            "is_trading_day": is_trading_day(),
            "next_auto_start": next_start,
            "next_auto_stop": next_stop,
            "current_time": now.isoformat(),
        }

    async def _check_midday_start(self) -> None:
        """If server starts during market hours, auto-start engine immediately."""
        await asyncio.sleep(5)  # Wait for server init

        if not self._enabled:
            return
        if not is_trading_day():
            logger.info("오늘은 휴장일 - 자동 시작 스킵")
            return

        now = datetime.now().time()
        market_start = time(8, 30)
        market_end = time(15, 20)

        if market_start <= now <= market_end:
            logger.info("장 시간 중 서버 시작 감지 → 엔진 즉시 자동 시작")
            await self._auto_start()

    async def _auto_start(self) -> None:
        """Scheduled: auto-start the trading engine."""
        if not self._enabled:
            logger.info("스케줄러 비활성화 상태 - 자동 시작 스킵")
            return

        if not is_trading_day():
            logger.info(f"오늘({date.today()})은 휴장일 - 자동 시작 스킵")
            return

        from src.engine.trading_engine import EngineState

        if self._engine.state == EngineState.RUNNING:
            logger.info("엔진이 이미 실행 중 - 자동 시작 스킵")
            return

        try:
            logger.info("=== 스케줄러: 트레이딩 엔진 자동 시작 ===")
            self._engine.add_log("SCHEDULER", "장전 자동 시작")
            await self._engine.start()
            logger.info("=== 스케줄러: 엔진 자동 시작 완료 ===")
        except Exception as e:
            logger.error(f"스케줄러 자동 시작 실패: {e}")
            self._engine.add_log("SCHEDULER", f"자동 시작 실패: {e}", severity="ERROR")

    async def _auto_stop(self) -> None:
        """Scheduled: auto-stop the trading engine."""
        if not self._enabled:
            return

        from src.engine.trading_engine import EngineState

        if self._engine.state != EngineState.RUNNING:
            return

        try:
            logger.info("=== 스케줄러: 트레이딩 엔진 자동 종료 ===")
            self._engine.add_log("SCHEDULER", "장후 자동 종료")
            await self._engine.stop()
            logger.info("=== 스케줄러: 엔진 자동 종료 완료 ===")
        except Exception as e:
            logger.error(f"스케줄러 자동 종료 실패: {e}")
