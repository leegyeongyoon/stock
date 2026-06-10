#!/usr/bin/env python3
"""그날의 movers 유니버스 + 상/하한가 이벤트를 수집해 DB에 적재.

생존편향 없는 '그날 스캐너가 띄웠을 종목 전체'(급등/거래대금/거래량급증/상한가)를
pykrx 일봉으로 계산해 daily_movers / limit_events 테이블에 멱등 upsert 한다.
pykrx는 과거 일봉을 제공하므로 수년치 백필이 가능하다.

사용:
    python scripts/collect_daily_movers.py                      # 최근 거래일 1일
    python scripts/collect_daily_movers.py --date 2026-06-09
    python scripts/collect_daily_movers.py --start 2024-01-01 --end 2026-06-09
    python scripts/collect_daily_movers.py --start 2026-06-01 --end 2026-06-09 --force

거래량급증(vol_surge) 판정은 ohlcv_daily의 직전 20거래일 평균 거래량이 필요하므로,
일봉이 먼저 수집돼 있어야 한다(없으면 vol_surge는 비활성, 나머지 flag는 정상).
"""

import argparse
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(project_root / ".env")

from sqlalchemy import select  # noqa: E402

from src.api.movers_fetcher import MoversConfig, MoversFetcher, VolAvgProvider  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.database.models import OHLCVDaily  # noqa: E402
from src.database.repositories import (  # noqa: E402
    CollectionJobLogRepository,
    DailyMoversRepository,
    LimitEventRepository,
)
from src.utils.trading_calendar import is_trading_day  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

JOB_NAME = "collect_daily_movers"
VOL_AVG_LOOKBACK = 20  # 거래일
VOL_AVG_CALENDAR_WINDOW = 40  # 20거래일을 커버할 캘린더 일수
INTER_DAY_DELAY = 0.5  # pykrx 레이트리밋 여유(초)


def _parse_date(s: str) -> date:
    """YYYY-MM-DD 문자열 → date. 잘못된 형식이면 명확히 에러."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"날짜는 YYYY-MM-DD 형식이어야 합니다: {s!r}") from e


def _last_trading_day(today: date) -> date:
    d = today
    for _ in range(10):
        if is_trading_day(d):
            return d
        d -= timedelta(days=1)
    return today


def build_vol_avg_provider(session, target_date: date) -> VolAvgProvider:
    """ohlcv_daily에서 target_date 직전 20거래일 평균 거래량을 code별로 계산한 공급자."""
    start = target_date - timedelta(days=VOL_AVG_CALENDAR_WINDOW)
    rows = session.execute(
        select(OHLCVDaily.code, OHLCVDaily.volume)
        .where(OHLCVDaily.date >= start, OHLCVDaily.date < target_date)
        .order_by(OHLCVDaily.code, OHLCVDaily.date)
    ).all()

    vols: dict[str, list[int]] = defaultdict(list)
    for code, volume in rows:
        if volume is not None:
            vols[code].append(volume)

    avg: dict[str, float] = {}
    for code, series in vols.items():
        recent = series[-VOL_AVG_LOOKBACK:]
        if recent:
            avg[code] = sum(recent) / len(recent)

    if not avg:
        logger.warning(
            f"{target_date}: ohlcv_daily 20일 평균 거래량 없음 → vol_surge 비활성 "
            "(일봉을 먼저 수집하세요)"
        )

    return lambda code: avg.get(code)


def collect_one(target_date: date, fetcher: MoversFetcher, force: bool = False) -> dict:
    """하루치 수집. 멱등(완료된 날짜는 skip), 재개 가능."""
    # 1) 완료 여부 확인 + 공급자 구성 + 작업 시작 기록
    with get_session() as session:
        job_repo = CollectionJobLogRepository(session)
        if not force and job_repo.is_completed(JOB_NAME, target_date):
            return {"date": target_date, "status": "skipped", "movers": 0, "limits": 0}
        provider = build_vol_avg_provider(session, target_date)
        job_repo.start(JOB_NAME, target_date)

    # 2) 수집(네트워크) — 세션 밖에서
    try:
        movers, limits = fetcher.fetch(target_date, vol_avg_provider=provider)
    except Exception as e:  # noqa: BLE001
        logger.error(f"{target_date} 수집 실패: {e}")
        with get_session() as session:
            CollectionJobLogRepository(session).finish(
                JOB_NAME, target_date, "failed", error=str(e)
            )
        return {"date": target_date, "status": "failed", "movers": 0, "limits": 0}

    # 3) 적재 + 완료 기록
    # 거래일인데 0건이면 일시적 pykrx 실패/미공개일 수 있으므로 'partial'로 남겨
    # (is_completed가 'completed'만 done으로 보므로) 다음 실행 때 재시도되게 한다.
    with get_session() as session:
        n_m = DailyMoversRepository(session).upsert_many(movers)
        n_l = LimitEventRepository(session).upsert_many(limits)
        status = "completed" if (n_m or n_l) else "partial"
        CollectionJobLogRepository(session).finish(
            JOB_NAME, target_date, status,
            codes_done=n_m, records_written=n_m + n_l,
        )
    if status == "partial":
        logger.warning(f"{target_date}: 0건 수집 — partial로 기록(다음 실행 시 재시도)")
    return {"date": target_date, "status": status, "movers": n_m, "limits": n_l}


def daterange_trading(start: date, end: date) -> list[date]:
    days, cur = [], start
    while cur <= end:
        if is_trading_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


def main() -> int:
    parser = argparse.ArgumentParser(description="그날의 movers 유니버스 + 상/하한가 수집")
    parser.add_argument("--date", type=_parse_date, help="단일 일자 (YYYY-MM-DD)")
    parser.add_argument("--start", type=_parse_date, help="백필 시작 (YYYY-MM-DD)")
    parser.add_argument("--end", type=_parse_date, help="백필 끝 (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="완료된 날짜도 재수집")
    args = parser.parse_args()

    if args.date and (args.start or args.end):
        parser.error("--date 와 --start/--end 는 함께 쓸 수 없습니다")
    if bool(args.start) ^ bool(args.end):
        parser.error("--start 와 --end 는 함께 지정해야 합니다")
    if args.start and args.end and args.start > args.end:
        parser.error("--start 는 --end 보다 이전이어야 합니다")

    if args.date:
        if not is_trading_day(args.date):
            logger.warning(f"{args.date}는 비거래일로 보입니다(주말/공휴일) — 그대로 진행합니다")
        targets = [args.date]
    elif args.start:
        targets = daterange_trading(args.start, args.end)
    else:
        targets = [_last_trading_day(date.today())]

    if not targets:
        logger.info("처리할 거래일이 없습니다")
        return 0

    fetcher = MoversFetcher(MoversConfig())
    logger.info(f"수집 대상 {len(targets)}거래일: {targets[0]} ~ {targets[-1]}")

    total_m = total_l = done = skipped = partial = failed = 0
    for i, d in enumerate(targets):
        res = collect_one(d, fetcher, force=args.force)
        if res["status"] == "completed":
            done += 1
            total_m += res["movers"]
            total_l += res["limits"]
            logger.info(f"[{i+1}/{len(targets)}] {d} OK movers {res['movers']} / 상하한가 {res['limits']}")
        elif res["status"] == "skipped":
            skipped += 1
        elif res["status"] == "partial":
            partial += 1
        else:
            failed += 1
        if i < len(targets) - 1:
            time.sleep(INTER_DAY_DELAY)

    logger.info(
        f"완료: {done}일 수집 / {skipped}일 skip / {partial}일 partial(재시도 대상) / {failed}일 실패 | "
        f"movers {total_m}행, 상하한가 {total_l}건"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
