#!/usr/bin/env python3
"""실매수 백테스트 V3 - 홍인기 필터 단계별 효과 검증

실행:
  python scripts/backtest_realistic_v3.py          # 60일 + 20일 모두
  python scripts/backtest_realistic_v3.py 60        # 60일만
  python scripts/backtest_realistic_v3.py 20        # 20일만

비교 테이블:
  A) 기존 (기술적만, 홍인기 OFF)
  B) +시총 5000억
  C) +시총+끼+일봉자리
  D) +시총+끼+일봉자리+거래대금
  ※ investor_trading 테이블이 비어있어 기관 필터는 제외

실매수 조건:
  - 초기 자본금: 1000만원
  - 최대 동시 보유: 3종목
  - 포지션 사이징: 종목당 30%
  - 수수료: 0.015% × 2, 세금: 0.23%
  - 시그널 다수 시: confidence 높은 순
"""

import copy
import sys
from datetime import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

import pandas as pd
from sqlalchemy import text

from src.backtest.intraday_engine import IntradayBacktestConfig
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2
from src.database.connection import get_backtest_engine as get_engine
from src.strategies.data_driven import get_data_driven_strategies
from src.strategies.data_driven.daily_context import DailyContextLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 실매수 설정
CONFIG = IntradayBacktestConfig(
    initial_capital=10_000_000,
    max_positions=3,
    position_size=0.30,
    commission_rate=0.00015,
    tax_rate=0.0023,
    force_close_time=time(15, 20),
)

# 필터 레벨 정의 (기관 필터 제외 - investor_trading 비어있음)
FILTER_LEVELS = ["A", "B", "C", "D"]
FILTER_LABELS = {
    "A": "기존 (기술적만)",
    "B": "+시총 5000억",
    "C": "+끼+일봉자리",
    "D": "+거래대금 강화 (전체)",
}


def load_intraday_data():
    """DB에서 5분봉 데이터 로드."""
    engine = get_engine()
    with engine.connect() as conn:
        codes = [r[0] for r in conn.execute(text(
            "SELECT code FROM ohlcv_intraday GROUP BY code HAVING COUNT(*) >= 100"
        )).fetchall()]

    data = {}
    with engine.connect() as conn:
        for code in codes:
            rows = conn.execute(text(
                "SELECT datetime, open, high, low, close, volume "
                "FROM ohlcv_intraday WHERE code = :code ORDER BY datetime"
            ), {"code": code}).fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
                df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
                data[code] = df

    logger.info(f"로드: {len(data)}종목, {sum(len(df) for df in data.values()):,}건")
    return data


def filter_data_by_days(data, n_days):
    """마지막 n거래일만 필터."""
    all_dates = sorted(set(d for df in data.values() for d in df.index.date))
    if n_days >= len(all_dates):
        return data, all_dates
    target_dates = set(all_dates[-n_days:])
    filtered = {c: df[df.index.map(lambda x: x.date() in target_dates)] for c, df in data.items()}
    filtered = {k: v for k, v in filtered.items() if not v.empty}
    return filtered, sorted(target_dates)


def split_is_oos(data, is_ratio=0.75):
    """IS/OOS 분리."""
    all_dates = sorted(set(d for df in data.values() for d in df.index.date))
    split_idx = int(len(all_dates) * is_ratio)
    is_dates = set(all_dates[:split_idx])
    oos_dates = set(all_dates[split_idx:])

    is_data = {c: df[df.index.map(lambda x: x.date() in is_dates)] for c, df in data.items()}
    oos_data = {c: df[df.index.map(lambda x: x.date() in oos_dates)] for c, df in data.items()}
    is_data = {k: v for k, v in is_data.items() if not v.empty}
    oos_data = {k: v for k, v in oos_data.items() if not v.empty}

    return is_data, oos_data, len(is_dates), len(oos_dates)


def load_daily_context(codes, dates):
    """DailyContextLoader로 일별 컨텍스트 로드."""
    loader = DailyContextLoader()
    start_date = min(dates)
    end_date = max(dates)
    return loader.load(codes, start_date, end_date)


def run_backtest(strategy, data, daily_context=None):
    """V2 엔진으로 백테스트 실행."""
    engine = IntradayBacktestEngineV2(CONFIG)
    metrics, trades = engine.run(strategy, data, show_progress=False, daily_context=daily_context)
    return metrics, trades


def configure_filter(strategy, level):
    """필터 레벨에 따라 전략 파라미터 조정.

    A: 홍인기 OFF (기존 기술적만)
    B: 시총만 (5000억+)
    C: 시총 + 끼 + 일봉자리
    D: 전체 (시총 + 끼 + 일봉자리 + 거래대금)
    """
    if level == "A":
        strategy.HONG_ENABLED = False
    elif level == "B":
        strategy.HONG_ENABLED = True
        strategy.HONG_MIN_INST_BIL = -999999
        strategy.HONG_MAX_INST_BIL = 999999
        strategy.HONG_MIN_KI_SCORE = 0
        strategy.HONG_PREFERRED_POSITIONS = {"신고가", "전고점돌파", "빈집", "바닥반등", "해당없음"}
        strategy.HONG_MIN_DAILY_VALUE = 0
        strategy.MIN_INTRADAY_CUM_VALUE = 0
    elif level == "C":
        strategy.HONG_ENABLED = True
        strategy.HONG_MIN_INST_BIL = -999999
        strategy.HONG_MAX_INST_BIL = 999999
        strategy.HONG_MIN_DAILY_VALUE = 0
        strategy.MIN_INTRADAY_CUM_VALUE = 0
    elif level == "D":
        strategy.HONG_ENABLED = True
        strategy.HONG_MIN_INST_BIL = -999999
        strategy.HONG_MAX_INST_BIL = 999999
    return strategy


def run_filter_comparison(strategies, data, daily_context):
    """필터 레벨별 비교 백테스트."""
    results = {}

    for level in FILTER_LEVELS:
        combined_return = 0.0
        combined_wr = 0.0
        combined_trades = 0
        combined_mdd = 0.0
        strat_count = 0

        for base_strategy in strategies:
            strategy = copy.deepcopy(base_strategy)
            strategy = configure_filter(strategy, level)

            ctx = daily_context if level != "A" else None
            metrics, _ = run_backtest(strategy, data, daily_context=ctx)

            combined_return += metrics.total_return_pct
            combined_trades += metrics.total_trades
            combined_mdd = max(combined_mdd, metrics.max_drawdown)
            if metrics.total_trades > 0:
                combined_wr += metrics.win_rate
                strat_count += 1

        avg_wr = combined_wr / strat_count if strat_count > 0 else 0
        results[level] = {
            "label": f"{level}) {FILTER_LABELS[level]}",
            "wr": avg_wr,
            "return": combined_return,
            "trades": combined_trades,
            "mdd": combined_mdd,
        }

    return results


def print_filter_table(results, title):
    """필터 비교 테이블 출력."""
    print(f"\n{'━' * 70}")
    print(f"  {title}")
    print(f"{'━' * 70}")
    print(f"  {'조건':30s} {'WR':>7s} {'수익률':>10s} {'거래수':>7s} {'MDD':>7s}")
    print(f"  {'─' * 62}")

    for level in FILTER_LEVELS:
        r = results[level]
        print(f"  {r['label']:30s} {r['wr']:6.1f}% {r['return']:+9.2f}% {r['trades']:6d}건 {r['mdd']:6.2f}%")


def print_strategy_detail(strategies, data, daily_context, title, filter_level="D"):
    """전략별 상세 결과."""
    print(f"\n{'━' * 70}")
    print(f"  {title}")
    print(f"{'━' * 70}")
    print(f"  {'전략':30s} {'WR':>7s} {'수익률':>10s} {'거래수':>7s} {'MDD':>7s}")
    print(f"  {'─' * 62}")

    total_return = 0
    total_trades = 0

    for base_strategy in strategies:
        strategy = copy.deepcopy(base_strategy)
        strategy = configure_filter(strategy, filter_level)

        ctx = daily_context if filter_level != "A" else None
        metrics, _ = run_backtest(strategy, data, daily_context=ctx)

        print(f"  {strategy.name:30s} {metrics.win_rate:6.1f}% {metrics.total_return_pct:+9.2f}% {metrics.total_trades:6d}건 {metrics.max_drawdown:6.2f}%")
        total_return += metrics.total_return_pct
        total_trades += metrics.total_trades

    print(f"  {'─' * 62}")
    print(f"  {'합계':30s} {'':7s} {total_return:+9.2f}% {total_trades:6d}건")
    return total_return


def run_period_test(data, daily_context, strategies, n_days, label):
    """특정 기간의 백테스트 실행."""
    print(f"\n{'=' * 70}")
    print(f"  [{label}] {n_days}일 백테스트")
    print(f"  자본금: {CONFIG.initial_capital:,}원 | 최대 {CONFIG.max_positions}종목")
    print(f"  종목: {len(data)}개")
    print(f"{'=' * 70}")

    # IS/OOS 분리
    is_data, oos_data, is_days, oos_days = split_is_oos(data)
    print(f"  IS: {is_days}일, OOS: {oos_days}일")

    # 1. 전체 필터 비교
    print(f"\n  전체 데이터 필터 비교 중...")
    full_results = run_filter_comparison(strategies, data, daily_context)
    print_filter_table(full_results, f"[{label}] 전체 {n_days}일 필터 비교")

    # 2. IS 필터 비교
    print(f"\n  IS 백테스트 중...")
    is_results = run_filter_comparison(strategies, is_data, daily_context)
    print_filter_table(is_results, f"[{label}] IS ({is_days}일)")

    # 3. OOS 필터 비교
    print(f"\n  OOS 백테스트 중...")
    oos_results = run_filter_comparison(strategies, oos_data, daily_context)
    print_filter_table(oos_results, f"[{label}] OOS ({oos_days}일)")

    # 4. 전략별 상세 (필터 A: 기존 vs 필터 D: 전체)
    print_strategy_detail(strategies, data, daily_context,
                         f"[{label}] 전략별 상세 - 기존 (홍인기 OFF)", "A")
    print_strategy_detail(strategies, data, daily_context,
                         f"[{label}] 전략별 상세 - 홍인기 전체 ON", "D")

    # 5. IS vs OOS 상세
    print_strategy_detail(strategies, is_data, daily_context,
                         f"[{label}] IS 전략별 (홍인기 전체 ON)", "D")
    print_strategy_detail(strategies, oos_data, daily_context,
                         f"[{label}] OOS 전략별 (홍인기 전체 ON)", "D")

    # 6. 과적합 검증
    print(f"\n{'━' * 70}")
    print(f"  [{label}] 과적합 검증 (IS vs OOS)")
    print(f"{'━' * 70}")
    for level in FILTER_LEVELS:
        is_r = is_results[level]
        oos_r = oos_results[level]
        gap = abs(is_r["return"] - oos_r["return"])
        ratio = oos_r["return"] / is_r["return"] * 100 if is_r["return"] != 0 else 0
        status = "OK" if ratio > 70 else ("주의" if ratio > 40 else "경고")
        print(f"  {is_r['label']:30s} IS={is_r['return']:+.1f}% OOS={oos_r['return']:+.1f}% OOS/IS={ratio:.0f}% [{status}]")


def main():
    # 인자 파싱
    target_days = None
    if len(sys.argv) > 1:
        target_days = int(sys.argv[1])

    print("=" * 70)
    print("  실매수 백테스트 V3 - 홍인기 필터 단계별 검증")
    print("  ※ investor_trading 비어있음 → 기관 필터 제외")
    print("=" * 70)

    # 1. 전체 데이터 로드
    all_data = load_intraday_data()
    all_dates = sorted(set(d for df in all_data.values() for d in df.index.date))
    print(f"\n  전체: {len(all_data)}종목, {len(all_dates)}거래일")
    print(f"  기간: {min(all_dates)} ~ {max(all_dates)}")

    # 2. 일별 컨텍스트 로드
    codes = list(all_data.keys())
    print(f"\n  일별 컨텍스트 로딩 중...")
    daily_context = load_daily_context(codes, all_dates)
    ctx_count = sum(len(v) for v in daily_context.values())
    print(f"  컨텍스트 로드 완료: {ctx_count}건")

    # 3. 전략 생성
    strategies = get_data_driven_strategies()
    print(f"  전략: {len(strategies)}개")

    # 4. 백테스트 실행
    if target_days is None or target_days == 60:
        run_period_test(all_data, daily_context, strategies, len(all_dates), "60일")

    if target_days is None or target_days == 20:
        data_20, dates_20 = filter_data_by_days(all_data, 20)
        run_period_test(data_20, daily_context, strategies, 20, "20일")

    print(f"\n{'=' * 70}")
    print(f"  완료!")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
