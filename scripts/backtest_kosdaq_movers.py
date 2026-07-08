#!/usr/bin/env python3
"""KOSDAQ '그날 거래량 폭발 + 급등' 소형/중형 테마주에 고수 눌림목 전략 실측.

pykrx가 막힌 환경에서 yfinance로:
  1) KOSDAQ 전 종목 일봉(60일) 배치 다운로드
  2) movers 선별: 등락률>=surge AND 거래량>=vol_mult×직전20일 AND 거래대금>=floor
  3) mover 종목들의 5분봉 다운로드
  4) 고수 눌림목+VWAP 전략을 realism 엔진으로 백테스트

캐시: /tmp/kq_movers.pkl(스크리닝), /tmp/kq_5m.pkl(5분봉). --rescreen/--refresh 로 갱신.

DATABASE_URL 로 KOSDAQ 종목 목록 조회. 사용:
    DATABASE_URL=... .venv/bin/python scripts/backtest_kosdaq_movers.py \
        --surge 10 --vol-mult 3 --topk 150 --tp 3 --partial 2 --sl 1.5
"""

import argparse
import pickle
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.backtest.intraday_engine import IntradayBacktestConfig  # noqa: E402
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2  # noqa: E402
from src.backtest.realism import RealismConfig, RealismModel  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.strategies.aggressive import get_oscillation_scalp, get_pro_pullback  # noqa: E402

MOVERS_CACHE = Path("/tmp/kq_movers.pkl")
FIVE_M_CACHE = Path("/tmp/kq_5m.pkl")


def kosdaq_codes() -> list[str]:
    with get_session() as s:
        return [r[0] for r in s.execute(
            text("SELECT code FROM stocks WHERE market='KOSDAQ' ORDER BY code")
        ).fetchall()]


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                            "Close": "close", "Volume": "volume"})
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols].dropna()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def screen_movers(codes: list[str], surge: float, vol_mult: float, value_floor: float) -> dict:
    """일봉 배치 다운로드 → {code: {'days': n_mover, 'maxval': 최대거래대금}}."""
    movers: dict = {}
    chunk = 200
    for ci in range(0, len(codes), chunk):
        batch = codes[ci:ci + chunk]
        tickers = [c + ".KQ" for c in batch]
        try:
            raw = yf.download(tickers, period="60d", interval="1d", progress=False,
                              auto_adjust=False, group_by="ticker", threads=True)
        except Exception:  # noqa: BLE001
            continue
        for code, tk in zip(batch, tickers):
            try:
                df = _norm(raw[tk])
            except Exception:  # noqa: BLE001
                continue
            if len(df) < 22:
                continue
            close = df["close"].to_numpy(float)
            vol = df["volume"].to_numpy(float)
            cr = np.full(len(close), np.nan)
            cr[1:] = close[1:] / close[:-1] - 1.0
            mover_days, maxval = 0, 0.0
            for i in range(20, len(close)):
                vbase = vol[i - 20:i].mean()
                if vbase <= 0:
                    continue
                value = close[i] * vol[i]
                if cr[i] >= surge and (vol[i] / vbase) >= vol_mult and value >= value_floor:
                    mover_days += 1
                    maxval = max(maxval, value)
            if mover_days > 0:
                movers[code] = {"days": mover_days, "maxval": maxval}
        print(f"  스크리닝 {min(ci+chunk, len(codes))}/{len(codes)} … movers {len(movers)}")
    return movers


def fetch_5m(codes: list[str]) -> dict:
    data = {}
    for i, code in enumerate(codes):
        try:
            df = _norm(yf.download(code + ".KQ", period="60d", interval="5m",
                                   progress=False, auto_adjust=False))
        except Exception:  # noqa: BLE001
            continue
        df = df[df["volume"] > 0]
        if len(df) > 50:
            data[code] = df
        if (i + 1) % 25 == 0:
            print(f"  5분봉 {i+1}/{len(codes)} … 수집 {len(data)}")
    return data


def run(args) -> int:
    surge = args.surge / 100.0

    # 1) movers 스크리닝 (캐시)
    if not args.rescreen and MOVERS_CACHE.exists():
        movers = pickle.loads(MOVERS_CACHE.read_bytes())
        print(f"movers 캐시 로드: {len(movers)}종목")
    else:
        codes = kosdaq_codes()
        print(f"KOSDAQ {len(codes)}종목 일봉 스크리닝 (surge>={args.surge}% vol>={args.vol_mult}x 거래대금>={args.value_floor/1e8:.0f}억)…")
        movers = screen_movers(codes, surge, args.vol_mult, args.value_floor)
        MOVERS_CACHE.write_bytes(pickle.dumps(movers))
    if not movers:
        print("movers 0 — 조건 완화 필요")
        return 1

    # 상위 K (거래대금 큰 순)
    top = sorted(movers.items(), key=lambda kv: kv[1]["maxval"], reverse=True)[: args.topk]
    top_codes = [c for c, _ in top]
    print(f"movers {len(movers)}종목 중 거래대금 상위 {len(top_codes)}종목 선택")

    # 2) 분봉 (캐시 — 5m 기본, --cache로 1m 등 지정 가능)
    data_cache = Path(args.cache)
    if not args.refresh and data_cache.exists():
        data = pickle.loads(data_cache.read_bytes())
        print(f"분봉 캐시 로드: {len(data)}종목 ({data_cache.name})")
    else:
        print(f"상위 {len(top_codes)}종목 5분봉 다운로드…")
        data = fetch_5m(top_codes)
        data_cache.write_bytes(pickle.dumps(data))
    if not data:
        print("5분봉 0 — yfinance 응답 없음")
        return 1

    total_bars = sum(len(d) for d in data.values())
    days = sorted({ts.date() for d in data.values() for ts in d.index})
    print(f"백테스트 대상 {len(data)}종목 / {total_bars:,}봉 / {len(days)}일 ({days[0]}~{days[-1]})")

    if args.strategy == "oscillation":
        strat = get_oscillation_scalp(
            morning_surge_min=args.surge_min / 100.0,
            take_profit_pct=args.tp / 100.0, stop_loss_pct=args.sl / 100.0,
            time_stop_min=args.time_stop, vol_avg_window=args.vol_window,
            max_entry_hour=args.max_entry_hour or 13, bar_minutes=args.bar_minutes,
        )
    else:
        strat = get_pro_pullback(
            vol_spike_min=args.vol_mult, morning_surge_min=args.surge_min / 100.0,
            take_profit_pct=args.tp / 100.0, partial_tp=args.partial / 100.0,
            stop_loss_pct=args.sl / 100.0, time_stop_min=args.time_stop,
            vol_avg_window=args.vol_window, max_entry_hour=args.max_entry_hour or 12,
            bar_minutes=args.bar_minutes, min_bar_idx=args.vol_window,
        )
    realism = None if args.no_realism else RealismModel(RealismConfig(illiquid_mult_cap=1.0))
    config = IntradayBacktestConfig(
        initial_capital=args.capital, max_positions=args.max_pos,
        position_size=args.position_size, realism=realism,
        execution="signal_close" if args.no_realism else "next_open",
    )
    metrics, trades = IntradayBacktestEngineV2(config).run(strat, data, show_progress=True)
    m = metrics.to_dict()
    final = args.capital + m["total_pnl"]

    print("=" * 66)
    print(f"KOSDAQ 테마주 눌림목+VWAP(5분봉) | 끼>={args.vol_mult}x 시가대비고점+{args.surge_min}% / 부분익절+{args.partial}% TP{args.tp}% SL{args.sl}%")
    print(f"유니버스: 거래량폭발 KOSDAQ movers {len(data)}종목 / {len(days)}일 / realism {'OFF' if args.no_realism else 'ON'}")
    print("-" * 66)
    print(f"  초기자본    : {args.capital:,.0f}원")
    print(f"  최종자본    : {final:,.0f}원")
    print(f"  총수익률    : {m['total_return_pct']:+.2f}%")
    print(f"  거래수      : {m['total_trades']}건  (신뢰{'O' if m['total_trades']>=30 else 'X표본부족'})")
    print(f"  승률        : {m['win_rate']:.1f}%")
    print(f"  거래당 평균손익: 승 {m['avg_win']:+.2f}% / 패 {m['avg_loss']:+.2f}%")
    print(f"  Profit Factor: {m['profit_factor']:.2f}")
    print(f"  MDD         : -{m['max_drawdown']:.2f}%")
    print(f"  평균보유    : {m['avg_holding_time_minutes']:.0f}분")
    print("=" * 66)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="KOSDAQ 거래량폭발 테마주 눌림목 백테스트")
    p.add_argument("--surge", type=float, default=10.0, help="일봉 movers 등락률 임계(퍼센트)")
    p.add_argument("--vol-mult", type=float, default=3.0, dest="vol_mult", help="거래량 급증 배수")
    p.add_argument("--value-floor", type=float, default=2_000_000_000, dest="value_floor",
                   help="일 거래대금 최소(원). 잡주 제거")
    p.add_argument("--topk", type=int, default=150, help="5분봉 받을 상위 movers 수")
    p.add_argument("--surge-min", type=float, default=2.0, dest="surge_min",
                   help="(눌림목) 장중 고점이 시가 대비 최소 상승률(퍼센트)")
    p.add_argument("--tp", type=float, default=3.0)
    p.add_argument("--partial", type=float, default=2.0)
    p.add_argument("--sl", type=float, default=1.5)
    p.add_argument("--time-stop", type=int, default=40, dest="time_stop")
    p.add_argument("--vol-window", type=int, default=12, dest="vol_window")
    p.add_argument("--max-entry-hour", type=int, default=12, dest="max_entry_hour")
    p.add_argument("--capital", type=float, default=10_000_000)
    p.add_argument("--max-pos", type=int, default=3, dest="max_pos")
    p.add_argument("--position-size", type=float, default=0.3, dest="position_size")
    p.add_argument("--no-realism", action="store_true")
    p.add_argument("--rescreen", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--cache", default=str(FIVE_M_CACHE), help="분봉 캐시 경로(5m/1m)")
    p.add_argument("--bar-minutes", type=int, default=5, dest="bar_minutes")
    p.add_argument("--strategy", choices=["pullback", "oscillation"], default="pullback")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
