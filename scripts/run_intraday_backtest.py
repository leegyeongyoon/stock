#!/usr/bin/env python3
"""분봉 기반 단타 전략 5개 백테스트.

ohlcv_intraday 테이블의 5분봉 데이터를 사용하여
IntradayStrategy 기반 전략을 백테스트한다.
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
from src.strategies.intraday import (
    VWAPScalperStrategy,
    OpeningRangeBreakoutStrategy,
    MomentumBurstStrategy,
    MeanReversionScalperStrategy,
    VolumeSurgeStrategy,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

SAMPLE_SIZE = 500  # 백테스트 종목 수
INITIAL_CAPITAL = 5_000_000  # 500만원


def load_intraday_data(sample_size: int = SAMPLE_SIZE) -> dict[str, pd.DataFrame]:
    """ohlcv_intraday 테이블에서 분봉 데이터 로드."""
    engine = get_engine()

    with engine.connect() as conn:
        # 데이터가 충분한 종목 기준 상위 N개 선택
        codes_result = conn.execute(text("""
            SELECT code, COUNT(*) as cnt
            FROM ohlcv_intraday
            GROUP BY code
            HAVING COUNT(*) >= 100
            ORDER BY cnt DESC
            LIMIT :limit
        """), {"limit": sample_size})
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


def run_backtest():
    """Run intraday backtest for all strategies."""
    logger.info("=" * 70)
    logger.info("분봉 단타 전략 백테스트 (DB 데이터)")
    logger.info(f"종목 수: {SAMPLE_SIZE}, 초기자본: {INITIAL_CAPITAL:,}원")
    logger.info("=" * 70)

    # DB에서 분봉 데이터 로드
    logger.info("\n[1/2] 분봉 데이터 로드...")
    data = load_intraday_data(SAMPLE_SIZE)
    if not data:
        logger.error("분봉 데이터가 없습니다. fetch_top_stocks_data.py를 먼저 실행하세요.")
        return

    # 전략 초기화
    strategies = [
        VWAPScalperStrategy(),
        OpeningRangeBreakoutStrategy(),
        MomentumBurstStrategy(),
        MeanReversionScalperStrategy(),
        VolumeSurgeStrategy(),
    ]

    # 백테스트 설정
    config = IntradayBacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        max_positions=3,
        position_size=0.3,
    )
    engine = IntradayBacktestEngineV2(config)

    # 백테스트 실행
    logger.info("\n[2/2] 백테스트 실행...")
    results = {}

    for strategy in strategies:
        logger.info(f"\n--- {strategy.name} ---")
        try:
            metrics, trades = engine.run(strategy, data, show_progress=True)
            results[strategy.name] = {
                "metrics": metrics.to_dict(),
                "num_trades": len(trades),
                "params": {
                    k: v for k, v in strategy.__dict__.items()
                    if k != "name" and not k.startswith("_")
                },
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
                    for t in trades[:20]
                ],
            }
        except Exception as e:
            logger.error(f"{strategy.name} 실패: {e}")
            import traceback
            traceback.print_exc()
            results[strategy.name] = {"error": str(e)}

    # 결과 저장
    report = {
        "timestamp": datetime.now().isoformat(),
        "sample_size": len(data),
        "initial_capital": INITIAL_CAPITAL,
        "data_type": "intraday_5min",
        "config": {
            "initial_capital": config.initial_capital,
            "max_positions": config.max_positions,
            "position_size": config.position_size,
        },
        "strategies": results,
    }

    report_path = project_root / "reports" / "intraday_backtest_results.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # 요약 출력
    logger.info("\n" + "=" * 70)
    logger.info("분봉 단타 전략 백테스트 요약")
    logger.info("=" * 70)
    for name, res in results.items():
        if "error" in res:
            logger.info(f"  {name}: 오류 - {res['error']}")
        else:
            m = res["metrics"]
            logger.info(
                f"  {name}: 수익률={m['total_return_pct']:+.2f}%, "
                f"승률={m['win_rate']:.1f}%, "
                f"거래={m['total_trades']}건, "
                f"평균보유={m['avg_holding_time_minutes']:.0f}분, "
                f"MDD={m['max_drawdown']:.2f}%"
            )
    logger.info("=" * 70)
    logger.info(f"결과 저장: {report_path}")


if __name__ == "__main__":
    run_backtest()
