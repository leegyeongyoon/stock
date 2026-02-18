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

if TYPE_CHECKING:
    from src.engine.trading_engine import TradingEngine

# 2025-2026 한국 공휴일 (주식시장 휴장일)
KOREAN_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1),   # 신정
    date(2025, 1, 28),  # 설날 연휴
    date(2025, 1, 29),  # 설날
    date(2025, 1, 30),  # 설날 연휴
    date(2025, 3, 1),   # 삼일절
    date(2025, 5, 1),   # 근로자의 날
    date(2025, 5, 5),   # 어린이날
    date(2025, 5, 6),   # 부처님오신날
    date(2025, 6, 6),   # 현충일
    date(2025, 8, 15),  # 광복절
    date(2025, 10, 3),  # 개천절
    date(2025, 10, 6),  # 추석 연휴
    date(2025, 10, 7),  # 추석
    date(2025, 10, 8),  # 추석 연휴
    date(2025, 10, 9),  # 한글날
    date(2025, 12, 25), # 크리스마스
    date(2025, 12, 31), # 연말 휴장
    # 2026
    date(2026, 1, 1),   # 신정
    date(2026, 2, 16),  # 설날 연휴
    date(2026, 2, 17),  # 설날
    date(2026, 2, 18),  # 설날 연휴
    date(2026, 3, 1),   # 삼일절 (일요일→3/2 대체)
    date(2026, 3, 2),   # 삼일절 대체휴일
    date(2026, 5, 1),   # 근로자의 날
    date(2026, 5, 5),   # 어린이날
    date(2026, 5, 24),  # 부처님오신날
    date(2026, 6, 6),   # 현충일
    date(2026, 8, 15),  # 광복절
    date(2026, 9, 24),  # 추석 연휴
    date(2026, 9, 25),  # 추석
    date(2026, 9, 26),  # 추석 연휴
    date(2026, 10, 3),  # 개천절
    date(2026, 10, 9),  # 한글날
    date(2026, 12, 25), # 크리스마스
    date(2026, 12, 31), # 연말 휴장
}


def is_trading_day(d: date | None = None) -> bool:
    """Check if given date is a trading day (weekday + not holiday)."""
    d = d or date.today()
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if d in KOREAN_HOLIDAYS:
        return False
    return True


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
