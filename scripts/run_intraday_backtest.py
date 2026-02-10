#!/usr/bin/env python3
"""Run intraday backtest for day trading strategies."""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.intraday_fetcher import IntradayDataFetcher, ACTIVE_TRADING_CODES
from src.backtest.intraday_engine import IntradayBacktestEngine, IntradayBacktestConfig
from src.strategies.intraday import (
    VWAPScalperStrategy,
    OpeningRangeBreakoutStrategy,
    MomentumBurstStrategy,
    MeanReversionScalperStrategy,
    VolumeSurgeStrategy,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def run_backtest():
    """Run intraday backtest for all strategies."""
    print("=" * 60)
    print("인트라데이 백테스트 시작")
    print("=" * 60)

    # Fetch intraday data
    print("\n1. 분봉 데이터 수집 중...")
    fetcher = IntradayDataFetcher(delay=0.5)

    # Use active trading stocks (20 stocks)
    codes = list(ACTIVE_TRADING_CODES.keys())
    print(f"   대상 종목: {len(codes)}개")

    data = fetcher.get_multiple_stocks(
        codes=codes,
        interval="5m",  # 5분봉
        period="60d",  # 60일
    )

    if not data:
        print("❌ 데이터 수집 실패")
        return

    print(f"   수집 완료: {len(data)}개 종목")

    # Initialize strategies
    strategies = [
        VWAPScalperStrategy(),
        OpeningRangeBreakoutStrategy(),
        MomentumBurstStrategy(),
        MeanReversionScalperStrategy(),
        VolumeSurgeStrategy(),
    ]

    # Configure backtest
    config = IntradayBacktestConfig(
        initial_capital=5_000_000,  # 500만원
        max_positions=3,
        position_size=0.3,
    )

    engine = IntradayBacktestEngine(config)

    # Run backtest for each strategy
    print("\n2. 백테스트 실행 중...")
    results = {}

    for strategy in strategies:
        print(f"\n   [{strategy.name}]")
        try:
            metrics, trades = engine.run(strategy, data, show_progress=True)
            results[strategy.name] = {
                "metrics": metrics.to_dict(),
                "trades_count": len(trades),
            }

            print(f"   ✓ 거래 수: {metrics.total_trades}")
            print(f"   ✓ 승률: {metrics.win_rate:.1f}%")
            print(f"   ✓ 총 수익: {metrics.total_pnl:,.0f}원 ({metrics.total_return_pct:.2f}%)")
            print(f"   ✓ 최대 손실폭: {metrics.max_drawdown:.2f}%")
            print(f"   ✓ 평균 보유시간: {metrics.avg_holding_time_minutes:.1f}분")

        except Exception as e:
            logger.error(f"Error running {strategy.name}: {e}")
            print(f"   ❌ 오류: {e}")
            results[strategy.name] = {"error": str(e)}

    # Summary
    print("\n" + "=" * 60)
    print("백테스트 결과 요약")
    print("=" * 60)

    print(f"\n{'전략':<25} {'거래수':>8} {'승률':>8} {'수익률':>10} {'MDD':>8}")
    print("-" * 60)

    for name, result in results.items():
        if "error" in result:
            print(f"{name:<25} {'오류':<40}")
        else:
            m = result["metrics"]
            print(
                f"{name:<25} "
                f"{m['total_trades']:>8} "
                f"{m['win_rate']:>7.1f}% "
                f"{m['total_return_pct']:>9.2f}% "
                f"{m['max_drawdown']:>7.2f}%"
            )

    # Save results
    output_path = Path("reports/intraday_backtest_results.json")
    output_path.parent.mkdir(exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "config": {
                    "initial_capital": config.initial_capital,
                    "max_positions": config.max_positions,
                    "position_size": config.position_size,
                },
                "stocks_count": len(data),
                "results": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    run_backtest()
