#!/usr/bin/env python3
"""D+1 모멘텀 백테스트 (일봉) — 그날 급등+거래량급증 종목을 다음날 따라잡기.

분봉이 없을 때 단타 아이디어를 일봉으로 근사:
  신호(T): 등락률 >= surge_pct AND 거래량 >= vol_mult × 직전 20일 평균
  진입(T+1): 시가(+슬리피지)
  청산(T+1): SL/TP를 장중 고저로 판정, 미달 시 종가. (SL·TP 동시 도달 시 보수적으로 SL)
  비용: 수수료 0.015%×2 + 세금 0.23%(이익시) + 슬리피지

등락률은 ohlcv_daily.change_rate 가 NULL이라 종가로 직접 계산한다.

DATABASE_URL 로 DB 지정. 사용:
    DATABASE_URL=postgresql://stock:stock123@localhost:5433/stock_trading \
      .venv/bin/python scripts/backtest_d1_movers.py --surge 5 --vol-mult 2 --sl 3 --tp 5
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.database.connection import get_session  # noqa: E402

COMMISSION = 0.00015
TAX = 0.0023


def load_series() -> dict:
    """{code: dict of numpy arrays(date, open, high, low, close, volume)} 정렬 로드."""
    with get_session() as s:
        rows = s.execute(text(
            "SELECT code, date, open, high, low, close, volume "
            "FROM ohlcv_daily ORDER BY code, date"
        )).fetchall()
    by_code: dict = defaultdict(list)
    for r in rows:
        by_code[r[0]].append(r)
    out = {}
    for code, rs in by_code.items():
        out[code] = {
            "date": [r[1] for r in rs],
            "open": np.array([r[2] for r in rs], dtype=float),
            "high": np.array([r[3] for r in rs], dtype=float),
            "low": np.array([r[4] for r in rs], dtype=float),
            "close": np.array([r[5] for r in rs], dtype=float),
            "volume": np.array([r[6] for r in rs], dtype=float),
        }
    return out


def prior_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """직전 window개 평균(현재 제외). 부족하면 NaN."""
    n = len(arr)
    out = np.full(n, np.nan)
    for i in range(window, n):
        out[i] = arr[i - window:i].mean()
    return out


def run(args) -> int:
    surge = args.surge / 100.0
    sl, tp, slip = args.sl / 100.0, args.tp / 100.0, args.slip / 100.0
    series = load_series()

    # 신호 수집: (entry_date, code, cr, T+1 OHLC)
    signals_by_date: dict = defaultdict(list)
    for code, d in series.items():
        close, vol = d["close"], d["volume"]
        n = len(close)
        if n < 22:
            continue
        cr = np.full(n, np.nan)
        cr[1:] = close[1:] / close[:-1] - 1.0
        v20 = prior_mean(vol, 20)
        for i in range(20, n - 1):
            if np.isnan(cr[i]) or np.isnan(v20[i]) or v20[i] <= 0:
                continue
            triggered = (cr[i] <= -surge) if args.reverse else (cr[i] >= surge)
            if triggered and (vol[i] / v20[i]) >= args.vol_mult:
                signals_by_date[d["date"][i + 1]].append((
                    code, cr[i], d["open"][i + 1], d["high"][i + 1],
                    d["low"][i + 1], d["close"][i + 1],
                ))

    equity = float(args.capital)
    curve = [equity]
    rets, wins, by_reason = [], 0, defaultdict(int)

    for entry_date in sorted(signals_by_date):
        sigs = sorted(signals_by_date[entry_date], key=lambda x: x[1], reverse=True)[: args.max_pos]
        if not sigs:
            continue
        alloc = equity * args.position_size / len(sigs)
        day_pnl = 0.0
        for code, cr, o, h, l, c in sigs:
            entry = o * (1 + slip)
            qty = int(alloc / entry) if entry > 0 else 0
            if qty <= 0:
                continue
            sl_px, tp_px = entry * (1 - sl), entry * (1 + tp)
            if l <= sl_px:
                exit_px, reason = sl_px * (1 - slip), "SL"
            elif h >= tp_px:
                exit_px, reason = tp_px * (1 - slip), "TP"
            else:
                exit_px, reason = c * (1 - slip), "EOD"
            gross = (exit_px - entry) * qty
            comm = (entry + exit_px) * qty * COMMISSION
            tax = exit_px * qty * TAX if gross > 0 else 0.0
            net = gross - comm - tax
            day_pnl += net
            ret = net / (entry * qty)
            rets.append(ret)
            wins += 1 if net > 0 else 0
            by_reason[reason] += 1
        equity += day_pnl
        curve.append(equity)

    # 지표
    n = len(rets)
    if n == 0:
        print(f"신호 0건 (surge>={args.surge}% vol>={args.vol_mult}x) — 조건 완화 필요")
        return 0
    curve_arr = np.array(curve)
    peak = np.maximum.accumulate(curve_arr)
    mdd = float(((peak - curve_arr) / peak).max() * 100)
    total_ret = (equity / args.capital - 1) * 100
    win_rate = wins / n * 100
    avg_ret = float(np.mean(rets)) * 100
    gains = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    pf = (sum(gains) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")

    print("=" * 64)
    print(f"D+1 모멘텀 백테스트 | surge>={args.surge}% vol>={args.vol_mult}x SL{args.sl}% TP{args.tp}%")
    print(f"기간 데이터: ohlcv_daily 50종목(대형주) 2022-01~2025-01")
    print("-" * 64)
    print(f"  초기자본    : {args.capital:,.0f}원")
    print(f"  최종자본    : {equity:,.0f}원")
    print(f"  총수익률    : {total_ret:+.2f}%")
    print(f"  거래수      : {n}건")
    print(f"  승률        : {win_rate:.1f}%")
    print(f"  거래당 평균 : {avg_ret:+.2f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  MDD         : -{mdd:.2f}%")
    print(f"  청산내역    : TP {by_reason['TP']} / SL {by_reason['SL']} / 종가 {by_reason['EOD']}")
    print("=" * 64)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="D+1 모멘텀 일봉 백테스트")
    p.add_argument("--surge", type=float, default=5.0, help="당일 등락률 임계(퍼센트)")
    p.add_argument("--vol-mult", type=float, default=2.0, dest="vol_mult", help="거래량 급증 배수")
    p.add_argument("--sl", type=float, default=3.0, help="손절(퍼센트)")
    p.add_argument("--tp", type=float, default=5.0, help="익절(퍼센트)")
    p.add_argument("--slip", type=float, default=0.15, help="슬리피지(퍼센트, 편도)")
    p.add_argument("--capital", type=float, default=10_000_000)
    p.add_argument("--position-size", type=float, default=0.3, dest="position_size")
    p.add_argument("--max-pos", type=int, default=3, dest="max_pos")
    p.add_argument("--reverse", action="store_true", help="급락주 반등 노림(역방향)")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
