#!/usr/bin/env python3
"""DB 기반 ML 엣지 검증 — 1분봉(KIS) + 체결강도/잔량비 결합 → OOS 검증.

핵심: yfinance ML은 price-only로 OOS 상위2% 승률 41%(손익분기 43% 코앞)까지 왔다.
여기에 호가/체결강도(collect_orderflow로 수집)를 15·16번째 특징으로 더해,
'있을 때 vs 없을 때' OOS 승률을 비교한다. 체결강도 추가로 43%를 넘으면 → 진짜 +엣지.

전제: ohlcv_intraday(interval='1m', KIS 수집) + orderflow_snapshots 가 같은 날짜로 채워져 있어야 함.
    DATABASE_URL=... python scripts/ml_edge_test_db.py --start 2026-06-10 --end 2026-06-20
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

import numpy as np  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.database.connection import get_session  # noqa: E402
from src.database.repositories import OHLCVIntradayRepository, OrderFlowSnapshotRepository  # noqa: E402
from src.strategies.intraday.base import rolling_mean_np, rsi_np  # noqa: E402

PRICE_FEATS = ["vol_ratio", "vwap_ext", "from_open", "from_high", "rsi", "ret3",
               "green_streak", "bar_range", "above_vwap", "hour",
               "close_strength", "from_low", "down_streak", "rel_vol_daymax"]
FLOW_FEATS = ["exec_strength", "bid_ask_ratio"]


def _codes(start, end):
    with get_session() as s:
        return [r[0] for r in s.execute(text(
            "SELECT DISTINCT code FROM ohlcv_intraday WHERE interval='1m' "
            "AND datetime >= :s AND datetime <= :e"
        ), {"s": start, "e": end}).fetchall()]


def _align_flow(bar_times, flow):
    """각 봉 시각에 대해 직전(<=) orderflow 스냅샷 값을 매핑. flow=DataFrame(index=time)."""
    if flow is None or flow.empty:
        n = len(bar_times)
        return np.full(n, np.nan), np.full(n, np.nan)
    ft = flow.index.to_numpy()
    es = flow["exec_strength"].to_numpy(float)
    br = flow["bid_ask_ratio"].to_numpy(float)
    bt = np.array(bar_times, dtype="datetime64[ns]")
    ft = ft.astype("datetime64[ns]")
    idx = np.searchsorted(ft, bt, side="right") - 1
    out_es = np.where(idx >= 0, es[np.clip(idx, 0, len(es)-1)], np.nan)
    out_br = np.where(idx >= 0, br[np.clip(idx, 0, len(br)-1)], np.nan)
    return out_es, out_br


def build(start, end, horizon, target, stop, use_flow):
    codes = _codes(start, end)
    X, y, dates = [], [], []
    with get_session() as s:
        bar_repo = OHLCVIntradayRepository(s)
        flow_repo = OrderFlowSnapshotRepository(s)
        for code in codes:
            bars = bar_repo.get_by_code(code, "1m", start, end)
            if bars.empty:
                continue
            flow = flow_repo.get_by_code(code, start, end) if use_flow else None
            for d, day in bars.groupby(bars.index.date):
                o = day["open"].to_numpy(float); h = day["high"].to_numpy(float)
                low = day["low"].to_numpy(float); c = day["close"].to_numpy(float)
                v = day["volume"].to_numpy(float); n = len(c)
                if n < 14 + horizon + 2:
                    continue
                tp = (h+low+c)/3; cumv = np.cumsum(v)
                vwap = np.where(cumv > 0, np.cumsum(tp*v)/np.maximum(cumv, 1), c)
                rh = np.maximum.accumulate(h); rl = np.minimum.accumulate(low)
                rmv = np.maximum.accumulate(v); dopen = o[0]
                rm = rolling_mean_np(v, 12); vb = np.full(n, np.nan); vb[1:] = rm[:-1]
                vr = np.where(vb > 0, v/np.where(vb > 0, vb, 1), np.nan)
                rsi = rsi_np(c, 14); ret3 = np.full(n, np.nan); ret3[3:] = c[3:]/c[:-3]-1
                gr = (c > o).astype(float); rd = (c < o).astype(float)
                gs = np.zeros(n); ds = np.zeros(n)
                for i in range(n):
                    gs[i] = gs[i-1]+1 if (i > 0 and gr[i]) else gr[i]
                    ds[i] = ds[i-1]+1 if (i > 0 and rd[i]) else rd[i]
                rng = (h-low)/np.where(c > 0, c, 1)
                hours = np.array([getattr(ts, "hour", 0) for ts in day.index])
                f_es, f_br = _align_flow(list(day.index), flow) if use_flow else (None, None)
                for i in range(12, n-1):
                    if hours[i] >= 14 or np.isnan(vr[i]) or np.isnan(rsi[i]):
                        continue
                    entry = c[i]; tpx = entry*(1+target); spx = entry*(1-stop); win = 0
                    for j in range(i+1, min(i+1+horizon, n)):
                        if low[j] <= spx: win = 0; break
                        if h[j] >= tpx: win = 1; break
                    row = [vr[i], c[i]/vwap[i]-1 if vwap[i] > 0 else 0,
                           c[i]/dopen-1 if dopen > 0 else 0, c[i]/rh[i]-1 if rh[i] > 0 else 0,
                           rsi[i], ret3[i] if not np.isnan(ret3[i]) else 0, gs[i], rng[i],
                           1.0 if c[i] > vwap[i] else 0.0, float(hours[i]),
                           (c[i]-low[i])/(h[i]-low[i]) if h[i] > low[i] else 0.5,
                           c[i]/rl[i]-1 if rl[i] > 0 else 0, ds[i],
                           v[i]/rmv[i] if rmv[i] > 0 else 0]
                    if use_flow:
                        row += [f_es[i] if not np.isnan(f_es[i]) else 100.0,
                                f_br[i] if not np.isnan(f_br[i]) else 1.0]
                    X.append(row); y.append(win); dates.append(d)
    return np.array(X), np.array(y), np.array(dates)


def evaluate(tag, X, y, dates, target, stop, cost):
    if len(y) < 500:
        print(f"[{tag}] 샘플 부족 ({len(y)})"); return
    ud = sorted(set(dates)); split = ud[int(len(ud)*0.7)]
    tr = dates <= split; te = dates > split
    m = HistGradientBoostingClassifier(max_iter=200, max_depth=4, learning_rate=0.05, min_samples_leaf=200)
    m.fit(X[tr], y[tr]); proba = m.predict_proba(X[te])[:, 1]; yte = y[te]
    print(f"[{tag}] OOS {te.sum():,}건 / 기본승률 {yte.mean():.1%}")
    for pct in (0.02, 0.05, 0.10):
        k = int(len(proba)*pct)
        if k < 30:
            continue
        idx = np.argsort(proba)[::-1][:k]; wr = yte[idx].mean()
        exp = (wr*target - (1-wr)*stop - cost)*100
        flag = "  <== +!" if exp > 0 else ""
        print(f"    상위{pct*100:.0f}%: 승률 {wr:.1%} / 기대 {exp:+.2f}%{flag}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--target", type=float, default=2.0)
    p.add_argument("--stop", type=float, default=1.5)
    p.add_argument("--cost", type=float, default=0.5)
    a = p.parse_args()
    s = datetime.strptime(a.start, "%Y-%m-%d"); e = datetime.strptime(a.end, "%Y-%m-%d") + timedelta(days=1)
    tgt, stp, cost = a.target/100, a.stop/100, a.cost/100
    be = a.stop/(a.target+a.stop)
    print(f"손익분기 승률 {be:.0%} | 라벨 +{a.target}% before -{a.stop}%\n")

    Xp, yp, dp = build(s, e, a.horizon, tgt, stp, use_flow=False)
    evaluate("price만 (14특징)", Xp, yp, dp, tgt, stp, cost)
    print()
    Xf, yf, df = build(s, e, a.horizon, tgt, stp, use_flow=True)
    evaluate("price+체결강도 (16특징)", Xf, yf, df, tgt, stp, cost)
    print("\n체결강도 추가로 상위2% 승률이 43%를 넘으면 → 호가데이터가 그 마지막 2%p를 채운 것")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
