#!/usr/bin/env python3
"""불 플래그 — 쭉 오른 뒤 2~3봉 살짝 눌리면(거래량없이) 사서 추세 재개를 먹는다.

사용자 패턴: ① 선행 강한 상승(run) ② 2~3봉 얕은 눌림(저거래량) ③ 진입 → 다시 상승.
앞 테스트는 선행상승을 안 걸렀음. 여기선 정확히: run-up + 얕은눌림 + (저/고)거래량 비교.

KIS 진짜 거래량 1분봉으로 검증. .venv/bin/python scripts/test_bullflag_yf.py --cache /tmp/kis_today_1m.pkl
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
    pb, RUN = args.pb_len, args.run_bars
    flags_y, flags_pbvol = [], []
    n_total = 0
    for code, df in data.items():
        for _, day in df.groupby(df.index.date):
            h = day["high"].to_numpy(float); low = day["low"].to_numpy(float)
            c = day["close"].to_numpy(float); v = day["volume"].to_numpy(float)
            n = len(c)
            if n < RUN + pb + H + 2:
                continue
            tp = (h + low + c) / 3; cumv = np.cumsum(v)
            vwap = np.where(cumv > 0, np.cumsum(tp * v) / np.maximum(cumv, 1), c)
            for i in range(RUN + pb, n - 1):
                n_total += 1
                top = i - pb   # 눌림 직전(고점) 봉
                # ① 선행 상승: top 봉이 RUN봉 전 대비 충분히 올랐나
                if c[top - RUN] <= 0:
                    continue
                run_up = c[top] / c[top - RUN] - 1
                if run_up < args.run_up:
                    continue
                # ② 얕은 눌림: 최근 pb봉이 하락(종가 하향) + 얕음
                if not all(c[k] <= c[k - 1] for k in range(top + 1, i + 1)):
                    continue
                depth = c[top] / c[i] - 1
                if depth <= 0 or depth > args.max_depth:
                    continue
                # 추세 유지: VWAP 위
                if vwap[i] <= 0 or c[i] < vwap[i]:
                    continue
                # 눌림 거래량비 = 눌림봉 평균 / 상승봉 평균
                up_vol = v[top - RUN:top].mean()
                pb_vol = v[top + 1:i + 1].mean()
                pbv = (pb_vol / up_vol) if up_vol > 0 else 1.0
                # 라벨
                entry = c[i]; tpx = entry * (1 + T); spx = entry * (1 - S); win = 0
                for j in range(i + 1, min(i + 1 + H, n)):
                    if low[j] <= spx:
                        win = 0; break
                    if h[j] >= tpx:
                        win = 1; break
                flags_y.append(win); flags_pbvol.append(pbv)

    if not flags_y:
        print(f"불플래그 패턴 0건 (run_up>={args.run_up*100:.1f}% pb={pb} 조건). 완화 필요"); return 1
    y = np.array(flags_y, float); pbv = np.array(flags_pbvol)
    be = S / (T + S)
    print(f"{Path(args.cache).name} | 불플래그 {len(y):,}건 / 전체봉 {n_total:,} | "
          f"선행상승>={args.run_up*100:.1f}%({RUN}봉) + {pb}봉 얕은눌림(<{args.max_depth*100:.0f}%) | 손익분기 {be:.0%}")
    print(f"불플래그 전체 승률: {y.mean():.1%} (전체 눌림 기본 ~15% 대비)\n")
    # 눌림 거래량 저/고 비교
    lo = pbv <= np.quantile(pbv, 0.5)
    print(f"  저거래량 눌림(하위50%): 승률 {y[lo].mean():.1%} ({lo.sum()}건)")
    print(f"  고거래량 눌림(상위50%): 승률 {y[~lo].mean():.1%} ({(~lo).sum()}건)")
    exp = (y.mean() * T - (1 - y.mean()) * S) * 100
    print(f"  불플래그 전체 비용전 기대값: {exp:+.2f}% (비용0.5% 후 {exp-0.5:+.2f}%)")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="/tmp/kis_today_1m.pkl")
    p.add_argument("--horizon", type=int, default=20)
    p.add_argument("--target", type=float, default=2.0)
    p.add_argument("--stop", type=float, default=1.5)
    p.add_argument("--pb-len", type=int, default=2, dest="pb_len", help="눌림 봉 수(2~3)")
    p.add_argument("--run-bars", type=int, default=5, dest="run_bars", help="선행 상승 측정 봉수")
    p.add_argument("--run-up", type=float, default=0.015, dest="run_up", help="선행 최소 상승률")
    p.add_argument("--max-depth", type=float, default=0.015, dest="max_depth", help="눌림 최대 깊이")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
