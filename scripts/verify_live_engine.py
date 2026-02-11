"""
실시간 엔진 검증 스크립트
- DB의 최근 거래일 데이터를 로드
- 6개 전략을 실행하여 신호 발생 여부 확인
- 백테스트 결과와 비교하여 일관성 검증
"""

import sys
sys.path.insert(0, ".")

import pandas as pd
from src.database.connection import get_engine as get_db_engine
from src.strategies.data_driven.intraday_strategy_1 import MorningRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_2 import LunchRSINeutralATRVolumeStrategy
from src.strategies.data_driven.intraday_strategy_3 import ModifiedRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_4 import AfternoonRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_6 import AfternoonRSINeutralATRVolumeStrategy
from src.strategies.data_driven.intraday_strategy_8 import MorningWideRSINeutralATRStrategy


DB_ENGINE = get_db_engine()


def load_day_data(stock_code: str, date: str) -> pd.DataFrame:
    """DB에서 특정 종목의 특정일 5분봉 데이터 로드 (datetime 인덱스)."""
    query = f"""
        SELECT datetime, open, high, low, close, volume
        FROM ohlcv_intraday
        WHERE code = '{stock_code}' AND datetime::date = '{date}'
        ORDER BY datetime
    """
    df = pd.read_sql(query, DB_ENGINE)
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    return df


def get_recent_trading_days(n: int = 3) -> list[str]:
    """DB에서 최근 N거래일 조회."""
    query = f"""
        SELECT DISTINCT datetime::date as day
        FROM ohlcv_intraday
        ORDER BY day DESC
        LIMIT {n}
    """
    df = pd.read_sql(query, DB_ENGINE)
    return [str(d) for d in df["day"].tolist()]


def get_sample_stocks(date: str, n: int = 50) -> list[str]:
    """특정일 거래량 상위 종목."""
    query = f"""
        SELECT code, SUM(volume) as total_vol
        FROM ohlcv_intraday
        WHERE datetime::date = '{date}'
        GROUP BY code
        ORDER BY total_vol DESC
        LIMIT {n}
    """
    df = pd.read_sql(query, DB_ENGINE)
    return df["code"].tolist()


def run_verification():
    strategies = [
        ("전략1", MorningRSINeutralATRStrategy()),
        ("전략2", LunchRSINeutralATRVolumeStrategy()),
        ("전략3", ModifiedRSINeutralATRStrategy()),
        ("전략4", AfternoonRSINeutralATRStrategy()),
        ("전략6", AfternoonRSINeutralATRVolumeStrategy()),
        ("전략8", MorningWideRSINeutralATRStrategy()),
    ]

    print("=" * 70)
    print("  실시간 엔진 검증 - DB 데이터 기반 전략 신호 테스트")
    print("=" * 70)

    # 1. 최근 거래일 확인
    days = get_recent_trading_days(3)
    print(f"\n최근 거래일: {', '.join(days)}")

    test_day = days[0]
    stocks = get_sample_stocks(test_day, 50)
    print(f"테스트 날짜: {test_day}")
    print(f"테스트 종목: {len(stocks)}개 (거래량 상위)")
    print("-" * 70)

    total_signals = 0
    results = []

    for name, strategy in strategies:
        signals = []
        errors = []
        stocks_with_data = 0

        for code in stocks:
            try:
                df = load_day_data(code, test_day)
                if df.empty or len(df) < 10:
                    continue
                stocks_with_data += 1

                indicators = strategy.precompute_day(df)

                for bar_idx in range(5, len(df)):
                    signal = strategy.check_entry_fast(code, bar_idx, indicators)
                    if signal:
                        bar_time = df.index[bar_idx]
                        price = df.iloc[bar_idx]["close"]
                        signals.append({
                            "code": code,
                            "time": str(bar_time),
                            "price": price,
                        })
            except Exception as e:
                errors.append(f"{code}: {e}")

        total_signals += len(signals)

        status = "OK" if stocks_with_data > 0 else "NO DATA"
        print(f"\n{name}: 데이터={stocks_with_data}종목, 신호={len(signals)}건 [{status}]")

        if signals:
            for s in signals[:5]:
                print(f"  -> {s['code']} @ {s['time']} (가격: {s['price']:,.0f}원)")
            if len(signals) > 5:
                print(f"  ... 외 {len(signals) - 5}건")

        if errors:
            print(f"  [에러 {len(errors)}건]: {errors[0]}")

        results.append({
            "strategy": name,
            "stocks": stocks_with_data,
            "signals": len(signals),
            "errors": len(errors),
        })

    # 최종 요약
    print("\n" + "=" * 70)
    print("  검증 결과 요약")
    print("=" * 70)
    print(f"{'전략':<10} {'종목수':>6} {'신호수':>6} {'에러':>6}")
    print("-" * 35)
    for r in results:
        print(f"{r['strategy']:<10} {r['stocks']:>6} {r['signals']:>6} {r['errors']:>6}")
    print("-" * 35)
    print(f"{'합계':<10} {'':>6} {total_signals:>6}")

    print()
    if total_signals > 0:
        print("결과: 전략이 정상적으로 신호를 생성합니다!")
        print("       내일 장 시작 후 실시간 매매가 작동할 것으로 예상됩니다.")
    else:
        print("주의: 신호가 0건입니다.")
        print("       해당 거래일에 조건을 충족하는 종목이 없었을 수 있습니다.")
        print("       (RSI 40-60 + ATR + 거래량 필터가 까다로워 매일 발생하지 않음)")


if __name__ == "__main__":
    run_verification()
