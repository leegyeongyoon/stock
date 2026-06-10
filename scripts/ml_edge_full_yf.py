"""ML 교집합 — 발견한 모든 조건(18특징)을 결합해 최적 조합을 찾고, 종목분리로 검증.

손으로 하나씩 테스트한 모든 신호(단일봉 + 맥락/시퀀스)를 GradientBoosting에 다 넣는다.
1일치라 날짜 OOS는 불가 → '학습종목 70% vs 검증종목 30%'로 분리(다른 종목 일반화 검증).
ML 예측 상위 X%의 검증종목 실제 승률이 손익분기를 넘으면 = 교집합에 진짜 엣지.
"""

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np  # noqa: E402
from sklearn.ensemble import GradientBoostingClassifier  # noqa: E402

from src.strategies.intraday.base import rolling_mean_np, rsi_np  # noqa: E402

FEATS = ["vol_ratio", "vwap_ext", "from_open", "from_high", "rsi", "ret3",
         "green_streak", "bar_range", "above_vwap", "hour", "close_strength",
         "from_low", "down_streak", "rel_vol_daymax",
         "prior_run10", "bars_since_high", "pullback_vol", "accel"]


def build(cache, horizon, target, stop):
    data = pickle.loads(Path(cache).read_bytes())
    X, y, codes = [], [], []
    for code, df in data.items():
        for d, day in df.groupby(df.index.date):
            o = day["open"].to_numpy(float); h = day["high"].to_numpy(float)
            low = day["low"].to_numpy(float); c = day["close"].to_numpy(float)
            v = day["volume"].to_numpy(float); n = len(c)
            if n < 16 + horizon:
                continue
            tp = (h + low + c) / 3; cumv = np.cumsum(v)
            vwap = np.where(cumv > 0, np.cumsum(tp * v) / np.maximum(cumv, 1), c)
            rh = np.maximum.accumulate(h); rl = np.minimum.accumulate(low)
            rmv = np.maximum.accumulate(v); dopen = o[0]
            rm = rolling_mean_np(v, 12); vb = np.full(n, np.nan); vb[1:] = rm[:-1]
            vr = np.where(vb > 0, v / np.where(vb > 0, vb, 1), np.nan)
            rsi = rsi_np(c, 14); ret3 = np.full(n, np.nan); ret3[3:] = c[3:] / c[:-3] - 1
            gr = (c > o).astype(float); rd = (c < o).astype(float)
            gs = np.zeros(n); ds = np.zeros(n)
            argrh = np.zeros(n, int)  # bars since run-high
            for i in range(n):
                gs[i] = gs[i-1]+1 if (i > 0 and gr[i]) else gr[i]
                ds[i] = ds[i-1]+1 if (i > 0 and rd[i]) else rd[i]
                argrh[i] = 0 if (i == 0 or h[i] >= rh[i-1]) else argrh[i-1]+1
            rng = (h - low) / np.where(c > 0, c, 1)
            hours = np.array([getattr(ts, "hour", 0) for ts in day.index])
            for i in range(14, n - 1):
                if hours[i] >= 14 or np.isnan(vr[i]) or np.isnan(rsi[i]):
                    continue
                # 맥락/시퀀스
                prun = c[i]/c[i-10]-1 if i >= 10 and c[i-10] > 0 else 0
                up_vol = v[max(0, i-8):max(1, i-2)].mean()
                pb_vol = v[max(0, i-2):i+1].mean()
                pbv = (pb_vol/up_vol) if up_vol > 0 else 1.0
                accel = (c[i]/c[i-1]-1) - (c[i-1]/c[i-2]-1) if i >= 2 and c[i-1] > 0 and c[i-2] > 0 else 0
                # 라벨
                entry = c[i]; tpx = entry*(1+target); spx = entry*(1-stop); win = 0
                for j in range(i+1, min(i+1+horizon, n)):
                    if low[j] <= spx: win = 0; break
                    if h[j] >= tpx: win = 1; break
                X.append([
                    vr[i], c[i]/vwap[i]-1 if vwap[i] > 0 else 0, c[i]/dopen-1 if dopen > 0 else 0,
                    c[i]/rh[i]-1 if rh[i] > 0 else 0, rsi[i], ret3[i] if not np.isnan(ret3[i]) else 0,
                    gs[i], rng[i], 1.0 if c[i] > vwap[i] else 0.0, float(hours[i]),
                    (c[i]-low[i])/(h[i]-low[i]) if h[i] > low[i] else 0.5,
                    c[i]/rl[i]-1 if rl[i] > 0 else 0, ds[i], v[i]/rmv[i] if rmv[i] > 0 else 0,
                    prun, float(argrh[i]), pbv, accel,
                ])
                y.append(win); codes.append(code)
    return np.array(X), np.array(y), np.array(codes)


def run(args):
    target, stop = args.target/100, args.stop/100
    X, y, codes = build(args.cache, args.horizon, target, stop)
    if len(y) < 500:
        print(f"샘플 부족 {len(y)}"); return 1
    uniq = sorted(set(codes))
    rng = np.random.RandomState(42)
    rng.shuffle(uniq)
    train_codes = set(uniq[:int(len(uniq)*0.7)])
    tr = np.array([c in train_codes for c in codes]); te = ~tr
    be = stop/(target+stop)
    cost = args.cost/100

    m = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                                   min_samples_leaf=100, subsample=0.8, random_state=0)
    m.fit(X[tr], y[tr])
    proba = m.predict_proba(X[te])[:, 1]; yte = y[te]
    print(f"{Path(args.cache).name} | 학습종목 {len(train_codes)} / 검증종목 {len(uniq)-len(train_codes)} | "
          f"학습 {tr.sum():,} / 검증 {te.sum():,} | 라벨 +{args.target}% before -{args.stop}% (손익분기 {be:.0%})")
    print(f"검증종목 기본 승률: {yte.mean():.1%}\n")
    print("ML 예측 상위 X% (검증=학습에 안 쓴 다른 종목) 실제 성과:")
    for pct in (0.05, 0.10, 0.20, 0.33):
        k = int(len(proba)*pct)
        if k < 20:
            continue
        idx = np.argsort(proba)[::-1][:k]; wr = yte[idx].mean()
        exp = (wr*target - (1-wr)*stop - cost)*100
        flag = "  <== 비용 넘김!" if exp > 0 else ""
        print(f"   상위{pct*100:.0f}%: 승률 {wr:.1%} ({k}건) | 기대 {exp:+.2f}%{flag}")
    print("\n=== 교집합 핵심 특징 (ML 중요도 상위) ===")
    for name, imp in sorted(zip(FEATS, m.feature_importances_), key=lambda x: -x[1])[:8]:
        print(f"   {name:<16} {imp:.3f}")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="/tmp/kis_today_1m.pkl")
    p.add_argument("--horizon", type=int, default=20)
    p.add_argument("--target", type=float, default=1.5)
    p.add_argument("--stop", type=float, default=1.0)
    p.add_argument("--cost", type=float, default=0.5)
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
