#!/usr/bin/env python3
"""그날의 테마 소속 + 핫테마 리더보드를 네이버 크롤로 수집해 DB에 적재 (전진 수집).

기존 src/analysis/theme_analyzer.py·theme_crawler.py 를 재사용한다(크롤 로직 안 다시 짬).
네이버 테마는 라이브 크롤만 가능하므로 매 거래일 장마감 후 실행해야 한다(과거 백필 불가).

산출:
  - daily_hot_themes : 핫테마 랭킹(점수/감성/대장주)
  - stock_themes     : 종목↔테마 소속 + 대장주 플래그
  - daily_movers.theme_tags 역정규화 갱신

주의: 네트워크 필요. 사용:
    python scripts/collect_themes_daily.py
    python scripts/collect_themes_daily.py --date 2026-06-09 --top 50
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

from src.analysis.theme_analyzer import get_theme_analyzer  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.database.repositories import (  # noqa: E402
    CollectionJobLogRepository,
    DailyHotThemeRepository,
    DailyMoversRepository,
    StockThemeRepository,
)
from src.utils.trading_calendar import is_trading_day  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

JOB_NAME = "collect_themes_daily"


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


async def collect(target_date: date, top_n: int) -> None:
    analyzer = get_theme_analyzer()
    crawler = analyzer.crawler

    with get_session() as session:
        CollectionJobLogRepository(session).start(JOB_NAME, target_date)

    try:
        rankings = await analyzer.get_theme_ranking(top_n=top_n)
        themes_by_code = {t.code: t for t in await crawler.get_theme_list()}
    except Exception as e:  # noqa: BLE001
        logger.error(f"테마 랭킹/목록 수집 실패: {e}")
        with get_session() as session:
            CollectionJobLogRepository(session).finish(JOB_NAME, target_date, "failed", error=str(e))
        return

    hot_rows: list[dict] = []
    theme_rows: list[dict] = []
    movers_theme_tags: dict[str, list[str]] = {}

    for r in rankings:
        theme = themes_by_code.get(r.theme_code)
        leader_name = getattr(theme, "leader_stock", None) if theme else None
        hot_rows.append({
            "date": target_date, "theme_code": r.theme_code, "theme_name": r.theme_name,
            "rank": r.rank, "change_rate": r.change_rate,
            "up_count": getattr(theme, "up_count", None) if theme else None,
            "down_count": getattr(theme, "down_count", None) if theme else None,
            "stock_count": getattr(theme, "stock_count", None) if theme else None,
            "leader_code": None, "leader_name": leader_name,
            "total_score": r.total_score, "news_hot_score": r.news_hot_score,
            "sentiment": r.sentiment,
        })

        # 멤버십
        try:
            stocks = await crawler.get_theme_stocks(r.theme_code)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"{r.theme_name} 종목 수집 실패: {e}")
            continue
        for s in stocks:
            is_leader = bool(leader_name and s.name == leader_name)
            theme_rows.append({
                "date": target_date, "code": s.code, "theme_code": r.theme_code,
                "theme_name": r.theme_name, "is_leader": is_leader,
            })
            movers_theme_tags.setdefault(s.code, [])
            if r.theme_name not in movers_theme_tags[s.code]:
                movers_theme_tags[s.code].append(r.theme_name)

    with get_session() as session:
        n_hot = DailyHotThemeRepository(session).upsert_many(hot_rows)
        n_theme = StockThemeRepository(session).upsert_many(theme_rows)
        # daily_movers.theme_tags 역정규화 (해당 일자 movers 종목만 갱신)
        dm = DailyMoversRepository(session)
        movers = {m.code for m in dm.get_for_date(target_date)}
        for code in movers & set(movers_theme_tags):
            dm.update_theme_tags(target_date, code, movers_theme_tags[code])
        CollectionJobLogRepository(session).finish(
            JOB_NAME, target_date, "completed", codes_done=n_theme, records_written=n_hot + n_theme,
        )

    logger.info(f"{target_date} 테마 수집 완료: 핫테마 {n_hot} / 소속 {n_theme}행")


def main() -> int:
    parser = argparse.ArgumentParser(description="그날 테마 소속/핫테마 수집")
    parser.add_argument("--date", type=_parse_date, help="대상 일자 (YYYY-MM-DD)")
    parser.add_argument("--top", type=int, default=50, help="핫테마 상위 N (기본 50)")
    args = parser.parse_args()

    target = args.date or _last_trading_day(date.today())
    asyncio.run(collect(target, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
