#!/usr/bin/env python3
"""그날의 movers 유니버스 + 1분봉 + 테마/상한가로 2-티어 전략을 현실적 백테스트.

데이터 계층(daily_movers / ohlcv_intraday(1m) / stock_themes / limit_events)을
2-티어 전략(균형 스캘프 / 공격 모멘텀·상따)에 연결하고, realism 엔진 + purged
walk-forward 로 검증한다. "이 알고리즘으로 투자했으면?" 에 답하는 스크립트.

신뢰할 1분봉/테마는 전진 수집 구간에만 존재하므로, 그 기간을 --start/--end 로 준다.

사용:
    python scripts/backtest_movers.py --start 2026-06-01 --end 2026-06-30 --tier balanced
    python scripts/backtest_movers.py --start ... --end ... --tier momentum --no-realism
    python scripts/backtest_movers.py --start ... --end ... --tier limitup --walkforward
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(project_root / ".env")

from sqlalchemy import select  # noqa: E402

from src.backtest.intraday_engine import IntradayBacktestConfig  # noqa: E402
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2  # noqa: E402
from src.backtest.realism import RealismModel  # noqa: E402
from src.backtest.walkforward import walk_forward_windows  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.database.models import StockTheme  # noqa: E402
from src.database.repositories import (  # noqa: E402
    DailyMoversRepository,
    LimitEventRepository,
    OHLCVIntradayRepository,
    StockThemeRepository,
)
from src.strategies.aggressive import (  # noqa: E402
    get_aggressive_limitup,
    get_aggressive_momentum,
    get_balanced_scalp,
)
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

MIN_TRADES_RELIABLE = 30  # 이보다 적으면 결과 '신뢰불가' 표기

STRATEGY_FACTORIES = {
    "balanced": get_balanced_scalp,
    "momentum": get_aggressive_momentum,
    "limitup": get_aggressive_limitup,
}


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"날짜는 YYYY-MM-DD: {s!r}") from e


def _load_leaders(session, d: date) -> set[str]:
    """해당 일자 대장주 코드 집합."""
    rows = session.execute(
        select(StockTheme.code).where(StockTheme.date == d, StockTheme.is_leader.is_(True))
    ).scalars().all()
    return set(rows)


def load_backtest_inputs(start: date, end: date) -> tuple[dict, dict, dict, list[date]]:
    """(data, theme_data, limitup_data, dates) 로드.

    data: {code: 1분봉 DataFrame}, theme_data/limitup_data: {code: {date: info}}
    """
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())

    with get_session() as session:
        dm = DailyMoversRepository(session)
        st = StockThemeRepository(session)
        le = LimitEventRepository(session)
        oi = OHLCVIntradayRepository(session)

        dates = dm.get_dates(start, end)
        if not dates:
            return {}, {}, {}, []

        # 유니버스 = 기간 내 movers 합집합
        universe: set[str] = set()
        theme_data: dict[str, dict] = {}
        limitup_data: dict[str, dict] = {}

        for d in dates:
            universe.update(dm.get_universe(d))
            # 테마: 그날 stock_themes 에 있으면 in_hot_theme=True
            members = st.get_for_date(d)  # {code: [theme_name,...]}
            leaders = _load_leaders(session, d)
            for code in members:
                theme_data.setdefault(code, {})[d] = {
                    "in_hot_theme": True,
                    "is_leader": code in leaders,
                    "theme_name": members[code][0] if members[code] else None,
                }
            # 상한가
            for ev in le.get_for_date(d):
                if ev.event_type == "limit_up" and ev.limit_price:
                    limitup_data.setdefault(ev.code, {})[d] = {
                        "limit_price": ev.limit_price,
                        "first_hit_time": ev.first_hit_time,
                    }

        # 1분봉 로드
        data: dict = {}
        for code in universe:
            df = oi.get_by_code(code, "1m", start_dt, end_dt)
            if not df.empty:
                data[code] = df

    return data, theme_data, limitup_data, dates


def _print_metrics(label: str, metrics, n_trades: int) -> None:
    flag = "" if n_trades >= MIN_TRADES_RELIABLE else f"  [신뢰불가 <{MIN_TRADES_RELIABLE}건]"
    m = metrics.to_dict()
    logger.info(
        f"[{label}] 거래 {m['total_trades']} / 승률 {m['win_rate']}% / "
        f"수익 {m['total_return_pct']}% / MDD {m['max_drawdown']}% / PF {m['profit_factor']}{flag}"
    )


def run(args) -> int:
    data, theme_data, limitup_data, dates = load_backtest_inputs(args.start, args.end)
    if not data:
        logger.error("백테스트 입력 없음 — 먼저 collect_daily_movers / collect_minute_snapshot 실행")
        return 1
    logger.info(f"유니버스 {len(data)}종목, {len(dates)}거래일 ({dates[0]}~{dates[-1]})")

    realism = None if args.no_realism else RealismModel()
    config = IntradayBacktestConfig(
        initial_capital=args.capital, max_positions=args.max_positions,
        position_size=args.position_size, realism=realism, execution=args.execution,
    )

    def build_strategy():
        strat = STRATEGY_FACTORIES[args.tier]()
        strat.set_theme_data(theme_data)
        strat.set_limitup_data(limitup_data)
        return strat

    engine = IntradayBacktestEngineV2(config)

    # 전체 구간
    metrics, trades = engine.run(build_strategy(), data, show_progress=True)
    _print_metrics(f"{args.tier} 전체", metrics, len(trades))

    # purged walk-forward
    if args.walkforward and len(dates) >= args.train_size + args.test_size + args.purge:
        windows = walk_forward_windows(
            dates, train_size=args.train_size, test_size=args.test_size, purge=args.purge,
        )
        logger.info(f"--- walk-forward {len(windows)} 윈도우 (test 구간만 평가) ---")
        for w in windows:
            test_set = set(w.test)
            sub = {c: df[df.index.to_series().dt.date.isin(test_set)] for c, df in data.items()}
            sub = {c: df for c, df in sub.items() if not df.empty}
            if not sub:
                continue
            m, t = engine.run(build_strategy(), sub, show_progress=False)
            _print_metrics(f"WF#{w.index} {w.test[0]}~{w.test[-1]}", m, len(t))

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="movers 1분봉 2-티어 현실적 백테스트")
    p.add_argument("--start", type=_parse_date, required=True)
    p.add_argument("--end", type=_parse_date, required=True)
    p.add_argument("--tier", choices=list(STRATEGY_FACTORIES), default="balanced")
    p.add_argument("--no-realism", action="store_true", help="현실성 모델 끄기(룩어헤드 비교용)")
    p.add_argument("--execution", choices=["signal_close", "next_open"], default="next_open")
    p.add_argument("--capital", type=int, default=10_000_000)
    p.add_argument("--max-positions", type=int, default=3, dest="max_positions")
    p.add_argument("--position-size", type=float, default=0.3, dest="position_size")
    p.add_argument("--walkforward", action="store_true")
    p.add_argument("--train-size", type=int, default=20, dest="train_size")
    p.add_argument("--test-size", type=int, default=5, dest="test_size")
    p.add_argument("--purge", type=int, default=1)
    args = p.parse_args()
    if args.start > args.end:
        p.error("--start 는 --end 이전")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
