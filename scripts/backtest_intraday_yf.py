#!/usr/bin/env python3
"""yfinance 5분봉으로 거래량급증 스캘프(균형 티어) 실측 백테스트.

pykrx가 막힌 환경에서 야후 5분봉(최근 ~60일)으로 '장초반 거래량 붙으며 치고 올라가는
종목을 타서 +2% 부분익절 후 트레일링' 전략을 realism 엔진으로 검증한다.

한계: 야후 한국 분봉은 5분봉/최근60일/대형주 위주(소형 테마주는 부정확). 방법론 실측용.

DATABASE_URL 로 종목 유니버스(stocks/ohlcv_daily) 조회. 사용:
    DATABASE_URL=... .venv/bin/python scripts/backtest_intraday_yf.py --vol-mult 2 --tp 4
"""

import argparse
import pickle
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.api.intraday_fetcher import BLUE_CHIP_CODES  # noqa: E402
from src.backtest.intraday_engine import IntradayBacktestConfig  # noqa: E402
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2  # noqa: E402
from src.backtest.realism import RealismConfig, RealismModel  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.strategies.aggressive import get_balanced_scalp, get_pro_pullback  # noqa: E402

CACHE_PATH = Path("/tmp/yf5m_cache.pkl")


def get_universe() -> list[tuple[str, str]]:
    """(code, yf_ticker) 대형주 유니버스 = BLUE_CHIP_CODES(시총상위 큐레이션) ∪ DB ohlcv_daily 종목.

    stocks.market 으로 KOSPI=.KS / KOSDAQ=.KQ 부여(없으면 KOSPI 가정).
    """
    with get_session() as s:
        rows = s.execute(text("SELECT code, market FROM stocks")).fetchall()
    market_of = {code: (market or "KOSPI") for code, market in rows}
    with get_session() as s:
        db_codes = [r[0] for r in s.execute(text("SELECT DISTINCT code FROM ohlcv_daily")).fetchall()]

    codes = set(BLUE_CHIP_CODES) | set(db_codes)  # 대형주 큐레이션 ∪ DB
    out = []
    for code in sorted(codes):
        suffix = ".KQ" if market_of.get(code, "KOSPI").upper() == "KOSDAQ" else ".KS"
        out.append((code, f"{code}{suffix}"))
    return out


def fetch_5m(universe: list[tuple[str, str]]) -> dict:
    """yfinance 5분봉 60일 다운로드 → {code: DataFrame(open/high/low/close/volume)}."""
    data = {}
    for code, ticker in universe:
        try:
            df = yf.download(ticker, period="60d", interval="5m",
                             progress=False, auto_adjust=False)
        except Exception:  # noqa: BLE001
            continue
        if df is None or df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })[["open", "high", "low", "close", "volume"]].copy()
        df = df.dropna()
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[df["volume"] > 0]
        if len(df) > 50:
            data[code] = df
    return data


def load_data(refresh: bool) -> dict:
    """5분봉 데이터 로드(캐시 우선). --refresh 시 야후 재다운로드."""
    if not refresh and CACHE_PATH.exists():
        with open(CACHE_PATH, "rb") as f:
            data = pickle.load(f)
        print(f"캐시 로드: {len(data)}종목 ({CACHE_PATH})")
        return data
    universe = get_universe()
    print(f"유니버스 {len(universe)}종목 — yfinance 5분봉 다운로드 중...")
    data = fetch_5m(universe)
    if data:
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(data, f)
    return data


def build_strategy(args):
    """--strategy 에 따라 전략 생성."""
    if args.strategy == "pullback":
        return get_pro_pullback(
            vol_spike_min=args.vol_mult,
            take_profit_pct=args.tp / 100.0,
            partial_tp=args.partial / 100.0,
            stop_loss_pct=args.sl / 100.0,
            time_stop_min=args.time_stop,
            vol_avg_window=args.vol_window,
            max_entry_hour=args.max_entry_hour or 12,
            morning_surge_min=args.surge_min / 100.0,
            bar_minutes=5,
        )
    return get_balanced_scalp(
        require_theme=False,
        vol_mult=args.vol_mult,
        take_profit_pct=args.tp / 100.0,
        partial_tp=args.partial / 100.0,
        stop_loss_pct=args.sl / 100.0,
        bar_minutes=5,
        vol_avg_window=args.vol_window,
        min_bar_idx=args.vol_window,
        time_stop_min=args.time_stop,
        max_entry_hour=args.max_entry_hour,
    )


def run(args) -> int:
    data = load_data(args.refresh)
    if not data:
        print("분봉 데이터 0 — yfinance 응답 없음")
        return 1
    total_bars = sum(len(d) for d in data.values())
    days = sorted({ts.date() for d in data.values() for ts in d.index})
    print(f"수집 {len(data)}종목 / {total_bars:,}봉 / {len(days)}거래일 ({days[0]}~{days[-1]})")

    strat = build_strategy(args)
    # 슬리피지 모델: illiquid 배수는 '일봉 거래량' 기준이라 5분봉엔 과대 → 1.0으로 끔
    # (체결 충격은 impact 항 order_qty/bar_volume 이 이미 반영). 5분봉 현실적 슬리피지.
    realism = None if args.no_realism else RealismModel(RealismConfig(illiquid_mult_cap=1.0))
    config = IntradayBacktestConfig(
        initial_capital=args.capital, max_positions=args.max_pos,
        position_size=args.position_size,
        realism=realism,
        execution="signal_close" if args.no_realism else "next_open",
    )
    metrics, trades = IntradayBacktestEngineV2(config).run(strat, data, show_progress=True)
    m = metrics.to_dict()

    label = "고수 눌림목+VWAP" if args.strategy == "pullback" else "거래량급증 돌파 스캘프"
    print("=" * 64)
    print(f"{label}(5분봉) | 끼>={args.vol_mult}x, 부분익절+{args.partial}% / TP{args.tp}% / SL{args.sl}% / 오전{args.max_entry_hour or '제한없음'}")
    print(f"realism={'OFF' if args.no_realism else 'ON'} | 데이터: yfinance 5m {len(data)}종목 {len(days)}일")
    print("-" * 64)
    print(f"  초기자본    : {args.capital:,.0f}원")
    final = args.capital + m["total_pnl"]
    print(f"  최종자본    : {final:,.0f}원")
    print(f"  총수익률    : {m['total_return_pct']:+.2f}%")
    print(f"  거래수      : {m['total_trades']}건  (신뢰{'O' if m['total_trades']>=30 else 'X(표본부족)'})")
    print(f"  승률        : {m['win_rate']:.1f}%")
    print(f"  거래당 평균손익: 승 {m['avg_win']:+.2f}% / 패 {m['avg_loss']:+.2f}%")
    print(f"  Profit Factor: {m['profit_factor']:.2f}")
    print(f"  MDD         : -{m['max_drawdown']:.2f}%")
    print(f"  평균보유    : {m['avg_holding_time_minutes']:.0f}분")
    print("=" * 64)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="yfinance 5분봉 거래량급증 스캘프 백테스트")
    p.add_argument("--vol-mult", type=float, default=2.0, dest="vol_mult")
    p.add_argument("--tp", type=float, default=4.0, help="익절 천장(퍼센트)")
    p.add_argument("--partial", type=float, default=2.0, help="부분익절(퍼센트)")
    p.add_argument("--sl", type=float, default=1.5, help="손절(퍼센트)")
    p.add_argument("--time-stop", type=int, default=60, dest="time_stop", help="시간청산(분)")
    p.add_argument("--vol-window", type=int, default=20, dest="vol_window")
    p.add_argument("--max-entry-hour", type=int, default=0, dest="max_entry_hour",
                   help="이 시각 이후 진입 금지(예: 11=초반/오전만). 0=제한없음")
    p.add_argument("--capital", type=float, default=10_000_000)
    p.add_argument("--max-pos", type=int, default=3, dest="max_pos")
    p.add_argument("--position-size", type=float, default=0.3, dest="position_size")
    p.add_argument("--no-realism", action="store_true")
    p.add_argument("--strategy", choices=["breakout", "pullback"], default="breakout")
    p.add_argument("--surge-min", type=float, default=2.0, dest="surge_min",
                   help="(pullback) 장중 고점이 시가 대비 최소 상승률(퍼센트)")
    p.add_argument("--refresh", action="store_true", help="yfinance 재다운로드(캐시 무시)")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
