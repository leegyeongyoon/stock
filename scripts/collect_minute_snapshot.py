#!/usr/bin/env python3
"""장마감 후 그날 movers의 1분봉을 KIS API로 복원해 DB에 적재 (전진 수집).

KIS 분봉 API는 당일만 제공하므로 매 거래일 장마감 직후(~15:40) 실행해야 한다.
대상 = 그날 daily_movers 유니버스(수백 종목). 이미 적재된 종목은 skip(재개 가능).

주의: 네트워크 + KIS 키 필요. 모의/실전 무관(시세 조회). KIS_IS_MOCK 설정 따름.

사용:
    python scripts/collect_minute_snapshot.py                 # 오늘(최근 거래일)
    python scripts/collect_minute_snapshot.py --date 2026-06-09
    python scripts/collect_minute_snapshot.py --intervals 1,5
"""

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(project_root / ".env")

from src.broker.kis_auth import KISAuth  # noqa: E402
from src.broker.kis_client import KISClient  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.database.repositories import (  # noqa: E402
    CollectionJobLogRepository,
    DailyMoversRepository,
    OHLCVIntradayRepository,
)
from src.utils.trading_calendar import is_trading_day  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

JOB_NAME = "collect_minute_snapshot"


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"날짜는 YYYY-MM-DD: {s!r}") from e


def _last_trading_day(today: date) -> date:
    d = today
    for _ in range(10):
        if is_trading_day(d):
            return d
        d -= timedelta(days=1)
    return today


def _bars_to_records(bars, interval: str) -> list[dict]:
    """MinuteBar 리스트 → ohlcv_intraday upsert dict."""
    return [
        {
            "code": b.code, "datetime": b.datetime,
            "open": b.open, "high": b.high, "low": b.low, "close": b.close,
            "volume": b.volume, "interval": interval,
        }
        for b in bars
    ]


async def collect(target_date: date, intervals: list[str], force: bool) -> None:
    if not settings.kis_app_key:
        logger.error("KIS API 키가 없습니다(.env 확인) — 중단")
        return

    # 1) 대상 유니버스 + 재개용 기존 적재 종목
    with get_session() as session:
        universe = DailyMoversRepository(session).get_universe(target_date)
        if not universe:
            logger.warning(f"{target_date} daily_movers 유니버스 없음 — 먼저 collect_daily_movers 실행")
            return
        done_codes = OHLCVIntradayRepository(session).get_codes_for_date(target_date, intervals[0])
        CollectionJobLogRepository(session).start(JOB_NAME, target_date, codes_total=len(universe))

    todo = [c for c in universe if force or c not in done_codes]
    logger.info(f"{target_date} 분봉 수집 대상 {len(todo)}/{len(universe)}종목 (interval={intervals})")

    auth = KISAuth(
        app_key=settings.kis_app_key, app_secret=settings.kis_app_secret,
        account_no=settings.kis_account_no, is_mock=settings.kis_is_mock,
    )
    client = KISClient(auth)
    await client.start()

    done = written = failed = 0
    try:
        for i, code in enumerate(todo):
            try:
                records: list[dict] = []
                for iv in intervals:
                    bars = await client.get_intraday_full_day(code, time_unit=iv)
                    # 당일 봉만(혹시 모를 타날 혼입 방지)
                    bars = [b for b in bars if b.datetime.date() == target_date]
                    records.extend(_bars_to_records(bars, iv))
                if records:
                    with get_session() as session:
                        written += OHLCVIntradayRepository(session).upsert_many(records)
                done += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                logger.warning(f"{code} 분봉 수집 실패: {e}")
            if (i + 1) % 50 == 0:
                logger.info(f"  진행 {i+1}/{len(todo)} (성공 {done}, 실패 {failed})")
    finally:
        await client.stop()

    status = "completed" if failed == 0 else "partial"
    with get_session() as session:
        CollectionJobLogRepository(session).finish(
            JOB_NAME, target_date, status, codes_done=done, records_written=written,
        )
    logger.info(f"{target_date} 분봉 수집 완료: {done}종목 / {written}봉 / 실패 {failed} → {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="장마감 후 movers 1분봉 스냅샷 수집")
    parser.add_argument("--date", type=_parse_date, help="대상 일자 (YYYY-MM-DD)")
    parser.add_argument("--intervals", default="1", help="콤마구분 분봉 간격 (예: 1 또는 1,5)")
    parser.add_argument("--force", action="store_true", help="이미 적재된 종목도 재수집")
    args = parser.parse_args()

    target = args.date or _last_trading_day(date.today())
    intervals = [f"{iv.strip()}m" for iv in args.intervals.split(",") if iv.strip()]
    asyncio.run(collect(target, intervals, args.force))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
