#!/usr/bin/env python3
"""데이터 기반 전략 통합 백테스트.

data_driven/ 패키지의 모든 전략을 V2 엔진으로 백테스트.
In-sample(75%) / Out-of-sample(25%) 분리 리포트 생성.

Output: reports/data_driven_intraday_results.json
"""

import json
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

import pandas as pd
from sqlalchemy import text

from src.backtest.intraday_engine import IntradayBacktestConfig
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2
from src.database.connection import get_backtest_engine as get_engine
from src.strategies.data_driven import get_data_driven_strategies
from src.utils.logger import get_logger

logger = get_logger(__name__)

INITIAL_CAPITAL = 5_000_000
IS_RATIO = 0.75


def load_intraday_data() -> dict[str, pd.DataFrame]:
    """DB에서 전체 분봉 데이터 로드."""
    engine = get_engine()

    with engine.connect() as conn:
        codes_result = conn.execute(text("""
            SELECT code, COUNT(*) as cnt
            FROM ohlcv_intraday
            GROUP BY code
            HAVING COUNT(*) >= 100
            ORDER BY cnt DESC
        """))
        codes = [row[0] for row in codes_result.fetchall()]

    logger.info(f"분봉 데이터 로드: {len(codes)}종목")

    data = {}
    with engine.connect() as conn:
        for code in codes:
            result = conn.execute(text("""
                SELECT datetime, open, high, low, close, volume
                FROM ohlcv_intraday
                WHERE code = :code
                ORDER BY datetime
            """), {"code": code})
            rows = result.fetchall()

            if rows:
                df = pd.DataFrame(
                    rows,
                    columns=["datetime", "open", "high", "low", "close", "volume"],
                )
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
                df = df.astype({
                    "open": float, "high": float, "low": float,
                    "close": float, "volume": float,
                })
                data[code] = df

    total_bars = sum(len(df) for df in data.values())
    logger.info(f"로드 완료: {len(data)}종목, 총 {total_bars:,}건")
    return data


def split_data(
    data: dict[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """IS/OOS 분리."""
    all_dates = set()
    for df in data.values():
        all_dates.update(df.index.date)
    all_dates = sorted(all_dates)

    split_idx = int(len(all_dates) * IS_RATIO)
    is_dates = set(all_dates[:split_idx])
    oos_dates = set(all_dates[split_idx:])

    is_data = {}
    oos_data = {}

    for code, df in data.items():
        is_mask = df.index.map(lambda x: x.date() in is_dates)
        oos_mask = df.index.map(lambda x: x.date() in oos_dates)

        is_df = df[is_mask]
        oos_df = df[oos_mask]

        if not is_df.empty:
            is_data[code] = is_df
        if not oos_df.empty:
            oos_data[code] = oos_df

    logger.info(
        f"IS: {len(is_dates)}일 ({len(is_data)}종목), "
        f"OOS: {len(oos_dates)}일 ({len(oos_data)}종목)"
    )
    return is_data, oos_data


def run_backtest():
    """전체 백테스트 실행."""
    logger.info("=" * 70)
    logger.info("데이터 기반 전략 통합 백테스트")
    logger.info(f"초기자본: {INITIAL_CAPITAL:,}원")
    logger.info("=" * 70)

    # 전략 로드
    strategies = get_data_driven_strategies()
    if not strategies:
        logger.error(
            "data_driven 전략이 없습니다.\n"
            "먼저 scripts/design_intraday_strategies_with_ai.py를 실행하세요."
        )
        return

    logger.info(f"\n전략 {len(strategies)}개 발견:")
    for s in strategies:
        logger.info(f"  - {s.name}")

    # 데이터 로드 & 분리
    logger.info("\n[1/3] 분봉 데이터 로드...")
    data = load_intraday_data()
    is_data, oos_data = split_data(data)

    config = IntradayBacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        max_positions=3,
        position_size=0.3,
    )
    engine = IntradayBacktestEngineV2(config)

    # 백테스트
    results = {}

    for strategy in strategies:
        logger.info(f"\n--- {strategy.name} ---")
        strat_result = {}

        # 전체 데이터
        logger.info(f"  [FULL] 전체 데이터 백테스트...")
        try:
            metrics, trades = engine.run(strategy, data, show_progress=True)
            strat_result["full"] = {
                "metrics": metrics.to_dict(),
                "num_trades": len(trades),
                "trades_sample": [
                    {
                        "code": t.code,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "entry_time": str(t.entry_time),
                        "exit_time": str(t.exit_time),
                        "pnl": round(t.pnl, 0),
                        "pnl_pct": round(t.pnl_pct, 2),
                        "exit_reason": t.exit_reason,
                    }
                    for t in trades[:30]
                ],
            }
        except Exception as e:
            logger.error(f"  FULL 실패: {e}")
            strat_result["full"] = {"error": str(e)}

        # In-Sample
        logger.info(f"  [IS] In-Sample 백테스트...")
        try:
            is_metrics, is_trades = engine.run(strategy, is_data, show_progress=False)
            strat_result["in_sample"] = {
                "metrics": is_metrics.to_dict(),
                "num_trades": len(is_trades),
            }
        except Exception as e:
            logger.error(f"  IS 실패: {e}")
            strat_result["in_sample"] = {"error": str(e)}

        # Out-of-Sample
        logger.info(f"  [OOS] Out-of-Sample 백테스트...")
        try:
            oos_metrics, oos_trades = engine.run(strategy, oos_data, show_progress=False)
            strat_result["out_of_sample"] = {
                "metrics": oos_metrics.to_dict(),
                "num_trades": len(oos_trades),
            }
        except Exception as e:
            logger.error(f"  OOS 실패: {e}")
            strat_result["out_of_sample"] = {"error": str(e)}

        # 파라미터
        strat_result["params"] = {
            k: v for k, v in strategy.__dict__.items()
            if k != "name" and not k.startswith("_") and not callable(v)
        }

        results[strategy.name] = strat_result

    # 결과 저장
    report = {
        "timestamp": datetime.now().isoformat(),
        "stocks": len(data),
        "initial_capital": INITIAL_CAPITAL,
        "is_ratio": IS_RATIO,
        "config": {
            "initial_capital": config.initial_capital,
            "max_positions": config.max_positions,
            "position_size": config.position_size,
        },
        "strategies": results,
    }

    report_path = project_root / "reports" / "data_driven_intraday_results.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # 요약
    logger.info("\n" + "=" * 70)
    logger.info("백테스트 결과 요약")
    logger.info("=" * 70)
    logger.info(f"{'전략':30s} {'전체 수익률':>12s} {'IS 수익률':>12s} {'OOS 수익률':>12s} {'전체 승률':>10s}")
    logger.info("-" * 70)

    for name, res in results.items():
        full_ret = res.get("full", {}).get("metrics", {}).get("total_return_pct", "N/A")
        is_ret = res.get("in_sample", {}).get("metrics", {}).get("total_return_pct", "N/A")
        oos_ret = res.get("out_of_sample", {}).get("metrics", {}).get("total_return_pct", "N/A")
        full_wr = res.get("full", {}).get("metrics", {}).get("win_rate", "N/A")

        full_str = f"{full_ret:+.2f}%" if isinstance(full_ret, (int, float)) else str(full_ret)
        is_str = f"{is_ret:+.2f}%" if isinstance(is_ret, (int, float)) else str(is_ret)
        oos_str = f"{oos_ret:+.2f}%" if isinstance(oos_ret, (int, float)) else str(oos_ret)
        wr_str = f"{full_wr:.1f}%" if isinstance(full_wr, (int, float)) else str(full_wr)

        logger.info(f"  {name:28s} {full_str:>12s} {is_str:>12s} {oos_str:>12s} {wr_str:>10s}")

    logger.info("=" * 70)
    logger.info(f"결과 저장: {report_path}")


if __name__ == "__main__":
    run_backtest()
