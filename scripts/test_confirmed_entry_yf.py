#!/usr/bin/env python3
"""확인 후 진입 vs 즉시 진입 — 앞 1분봉을 보고 '턴 확인' 후 들어가면 손절이 주나?

74% 손절의 원인: 신호 뜨자마자 사면 1% 먼저 빠지고 그다음 오름. 해법: 신호봉(오전 눌림+거래량)
이 '무장'되면 바로 사지 말고, 다음 몇 봉을 지켜보다 신호봉 고가를 회복(턴 확인)할 때 진입.
대기 중 무너지면(손절선 이탈) 포기 → 손실 자체를 회피.

캐시(/tmp/kis_today_1m.pkl 등) 사용. .venv/bin/python scripts/test_confirmed_entry_yf.py --cache /tmp/kis_today_1m.pkl
"""

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np  # noqa: E402

from src.strategies.intraday.base import rolling_mean_np  # noqa: E402


def day_arr(day):
    o = day["open"].to_numpy(float); h = day["high"].to_numpy(float)
    low = day["low"].to_numpy(float); c = day["close"].to_numpy(float)
    v = day["volume"].to_numpy(float); n = len(c)
    tp = (h + low + c) / 3; cumv = np.cumsum(v)
    vwap = np.where(cumv > 0, np.cumsum(tp * v) / np.maximum(cumv, 1), c)
    rh = np.maximum.accumulate(h)
    rm = rolling_mean_np(v, 12); vb = np.full(n, np.nan); vb[1:] = rm[:-1]
    vr = np.where(vb > 0, v / np.where(vb > 0, vb, 1), np.nan)
    rng = (h - low) / np.where(c > 0, c, 1)
    hours = np.array([getattr(ts, "hour", 0) for ts in day.index])
    return o, h, low, c, n, vwap, rh, vr, rng, hours


def armed(i, c, vwap, rh, vr, rng, hours, A):
    """오전 눌림 + 거래량 + 변동성 = 진입 후보 무장."""
    return (
        hours[i] <= A.max_hour and not np.isnan(vr[i]) and vr[i] >= A.vol_mult
        and rng[i] >= A.range_thr
        and rh[i] > 0 and (rh[i] / c[i] - 1) >= A.pullback   # 고점 대비 눌림
    )


def sim_exit(h, low, c, n, entry_i, entry_px, stop, target, cost, max_hold):
    sl = entry_px * (1 - stop); tpx = entry_px * (1 + target)
    end = min(entry_i + max_hold, n - 1)
    for j in range(entry_i + 1, end + 1):
        if low[j] <= sl:
            return (sl / entry_px - 1 - cost), 1   # 손절
        if h[j] >= tpx:
            return (tpx / entry_px - 1 - cost), 0
    return (c[end] / entry_px - 1 - cost), 0


def run(args):
    data = pickle.loads(Path(args.cache).read_bytes())
    stop, target, cost = args.stop / 100, args.target / 100, args.cost / 100
    A = argparse.Namespace(max_hour=args.max_hour, vol_mult=args.vol_mult,
                           range_thr=args.range_thr, pullback=args.pullback)

    res = {"즉시": [], "확인후": []}
    skipped_crash = 0
    for code, df in data.items():
        for _, day in df.groupby(df.index.date):
            o, h, low, c, n, vwap, rh, vr, rng, hours = day_arr(day)
            if n < 20:
                continue
            i = 12
            i_imm = 12
            # 즉시 진입 패스
            while i_imm < n - 1:
                if armed(i_imm, c, vwap, rh, vr, rng, hours, A):
                    r, _ = sim_exit(h, low, c, n, i_imm, c[i_imm], stop, target, cost, args.max_hold)
                    res["즉시"].append(r)
                    i_imm += args.max_hold
                else:
                    i_imm += 1
            # 확인 후 진입 패스
            while i < n - 1:
                if armed(i, c, vwap, rh, vr, rng, hours, A):
                    trig = c[i] * (1 - stop)  # 대기 중 이탈선
                    entry_j = None
                    for j in range(i + 1, min(i + 1 + args.wait, n)):
                        if low[j] <= trig:       # 확인 전 무너짐 → 포기(손실 회피)
                            skipped_crash += 1
                            break
                        if c[j] > h[i]:           # 신호봉 고가 회복 = 턴 확인 → 진입
                            entry_j = j
                            break
                    if entry_j is not None:
                        r, _ = sim_exit(h, low, c, n, entry_j, c[entry_j], stop, target, cost, args.max_hold)
                        res["확인후"].append(r)
                        i = entry_j + args.max_hold
                        continue
                    i += args.wait
                else:
                    i += 1

    print(f"{Path(args.cache).name} | 무장조건: 오전+거래량{args.vol_mult}x+눌림{args.pullback*100:.0f}% | "
          f"손절 {args.stop}% 익절 {args.target}% 비용 {args.cost}%")
    print(f"확인 대기 중 무너져 회피한 진입: {skipped_crash}건 (즉시였으면 손절났을 것)\n")
    for tag, rets in res.items():
        if not rets:
            print(f"  [{tag}] 거래 0"); continue
        a = np.array(rets)
        wr = (a > 0).mean() * 100
        sl_rate = (a <= -stop + 1e-9).mean() * 100
        print(f"  [{tag}] 거래 {len(a)} | 승률 {wr:.1f}% | 손절률 {sl_rate:.0f}% | "
              f"거래당 {a.mean()*100:+.2f}% | 기대값 {a.mean()*100:+.2f}%")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="/tmp/kis_today_1m.pkl")
    p.add_argument("--stop", type=float, default=1.5)
    p.add_argument("--target", type=float, default=2.0)
    p.add_argument("--cost", type=float, default=0.5)
    p.add_argument("--wait", type=int, default=5, help="확인 대기 봉수")
    p.add_argument("--max-hold", type=int, default=20, dest="max_hold")
    p.add_argument("--max-hour", type=int, default=11, dest="max_hour")
    p.add_argument("--vol-mult", type=float, default=1.5, dest="vol_mult")
    p.add_argument("--range-thr", type=float, default=0.004, dest="range_thr")
    p.add_argument("--pullback", type=float, default=0.02)
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
