#!/usr/bin/env python3
"""저거래량 눌림 가설 — '거래량 없이 눌리면 매수, 거래량 터지며 떨어지면 회피'.

고수 원리: 상승 후 눌림이 *적은 거래량*이면 건강한 쉼(매수기회), *큰 거래량*이면 진짜 매도(회피).
KIS 진짜 거래량 1분봉으로 검증. 눌림 봉의 거래량비로 갈라 전방수익을 비교한다.

진입 후보(눌림): 일중 상승추세(>VWAP or >시가) + 직전 고점 대비 살짝 눌림 + 하락틱.
dip_vol = 현재(눌림) 봉 거래량 / 직전 5봉 평균. 낮을수록 '거래량 없는 눌림'.
"""

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np  # noqa: E402


def run(args):
    data = pickle.loads(Path(args.cache).read_bytes())
    H, T, S = args.horizon, args.target / 100, args.stop / 100
    dipvols, fwd_wins, near = [], [], []
    for code, df in data.items():
        for _, day in df.groupby(df.index.date):
            o = day["open"].to_numpy(float); h = day["high"].to_numpy(float)
            low = day["low"].to_numpy(float); c = day["close"].to_numpy(float)
            v = day["volume"].to_numpy(float); n = len(c)
            if n < 12 + H:
                continue
            tp = (h + low + c) / 3; cumv = np.cumsum(v)
            vwap = np.where(cumv > 0, np.cumsum(tp * v) / np.maximum(cumv, 1), c)
            rh = np.maximum.accumulate(h)
            for i in range(6, n - 1):
                # 눌림 맥락: 상승추세(>VWAP) + 고점 대비 -0.3~-3% + 하락틱
                if c[i] <= vwap[i] or vwap[i] <= 0:
                    continue
                drop = rh[i] / c[i] - 1
                if drop < 0.003 or drop > 0.03:
                    continue
                if c[i] > c[i - 1]:  # 하락/보합 틱만 (눌림)
                    continue
                base = v[i - 5:i].mean()
                if base <= 0:
                    continue
                dv = v[i] / base  # 눌림 봉 거래량비 (낮을수록 '거래량 없는 눌림')
                # 라벨: 다음 H봉 +T before -S
                entry = c[i]; tpx = entry * (1 + T); spx = entry * (1 - S); win = 0
                for j in range(i + 1, min(i + 1 + H, n)):
                    if low[j] <= spx:
                        win = 0; break
                    if h[j] >= tpx:
                        win = 1; break
                dipvols.append(dv); fwd_wins.append(win); near.append(drop)

    if not dipvols:
        print("눌림 샘플 없음"); return 1
    dv = np.array(dipvols); y = np.array(fwd_wins, float)
    base = y.mean()
    be = S / (T + S)
    print(f"{Path(args.cache).name} | 눌림 {len(dv):,}건 | 라벨 +{args.target}% before -{args.stop}% (손익분기 {be:.0%})")
    print(f"전체 눌림 승률: {base:.1%}\n")
    print("눌림 봉 거래량비(dip_vol)별 — 낮을수록 '거래량 없는 눌림' (고수 가설: 낮을수록 좋아야)")
    qs = np.quantile(dv, [0, 0.25, 0.5, 0.75, 1.0])
    labels = ["최저(거래량없는눌림)", "낮음", "높음", "최고(거래량터진하락)"]
    for (a, b), lab in zip(zip(qs[:-1], qs[1:]), labels):
        m = (dv >= a) & (dv <= b) if b == qs[-1] else (dv >= a) & (dv < b)
        if m.sum() < 20:
            continue
        wr = y[m].mean()
        exp = (wr * T - (1 - wr) * S) * 100
        print(f"   dip_vol {a:.2f}~{b:.2f} [{lab}]: 승률 {wr:.1%} ({m.sum():,}건) | 비용전 기대 {exp:+.2f}%")
    # 저거래량 눌림만 (하위 33%) vs 고거래량 (상위 33%)
    lo = dv <= np.quantile(dv, 0.33); hi = dv >= np.quantile(dv, 0.67)
    print(f"\n  저거래량 눌림(하위33%): 승률 {y[lo].mean():.1%} ({lo.sum()}건)")
    print(f"  고거래량 하락(상위33%): 승률 {y[hi].mean():.1%} ({hi.sum()}건)")
    diff = (y[lo].mean() - y[hi].mean()) * 100
    print(f"  차이: {diff:+.1f}%p  {'<== 가설 맞음(거래량없는눌림이 우위)' if diff > 3 else '(차이 작음)'}")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="/tmp/kis_today_1m.pkl")
    p.add_argument("--horizon", type=int, default=20)
    p.add_argument("--target", type=float, default=2.0)
    p.add_argument("--stop", type=float, default=1.5)
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
