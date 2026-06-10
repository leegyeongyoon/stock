#!/usr/bin/env python3
"""ML 엣지 테스트 — '데이터 집합체'에 값이 있나? 모든 특징을 ML로 결합해 OOS 검증.

손으로 만든 규칙이 아니라, 14개 특징을 GradientBoosting으로 한꺼번에 학습시켜
"이 봉이 +target before -stop 갈 확률"을 예측한다. 그 예측 상위 봉만 골라 진입하면
비용을 넘는가? IS(앞 70%)에서 학습, OOS(뒤 30%)에서 검증(과적합 차단).

데이터에 추출 가능한 값이 있으면 → OOS 상위예측의 승률이 기본보다 확 높아야 한다.
캐시(/tmp/kq_5m.pkl 등) 사용. .venv/bin/python scripts/ml_edge_test_yf.py --cache /tmp/kq_5m.pkl
"""

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from src.strategies.intraday.base import rolling_mean_np, rsi_np

FEATURES = ["vol_ratio", "vwap_ext", "from_open", "from_high", "rsi", "ret3",
            "green_streak", "bar_range", "above_vwap", "hour",
            "close_strength", "from_low", "down_streak", "rel_vol_daymax"]


def build(cache, horizon, target, stop):
    data = pickle.loads(Path(cache).read_bytes())
    X, y, dates = [], [], []
    for code, df in data.items():
        for d, day in df.groupby(df.index.date):
            o = day["open"].to_numpy(float); h = day["high"].to_numpy(float)
            low = day["low"].to_numpy(float); c = day["close"].to_numpy(float)
            v = day["volume"].to_numpy(float)
            n = len(c)
            if n < 14 + horizon + 2:
                continue
            tp = (h + low + c) / 3.0
            cumv = np.cumsum(v)
            vwap = np.where(cumv > 0, np.cumsum(tp * v) / np.maximum(cumv, 1), c)
            run_high = np.maximum.accumulate(h); run_low = np.minimum.accumulate(low)
            run_max_vol = np.maximum.accumulate(v)
            day_open = o[0]
            rmean = rolling_mean_np(v, 12); vbase = np.full(n, np.nan); vbase[1:] = rmean[:-1]
            vol_ratio = np.where(vbase > 0, v / np.where(vbase > 0, vbase, 1), np.nan)
            rsi = rsi_np(c, 14)
            ret3 = np.full(n, np.nan); ret3[3:] = c[3:] / c[:-3] - 1
            green = (c > o).astype(float); gs = np.zeros(n)
            red = (c < o).astype(float); ds = np.zeros(n)
            for i in range(n):
                gs[i] = gs[i-1]+1 if (i > 0 and green[i]) else green[i]
                ds[i] = ds[i-1]+1 if (i > 0 and red[i]) else red[i]
            rng = (h - low) / np.where(c > 0, c, 1)
            hours = np.array([getattr(ts, "hour", 0) for ts in day.index])
            for i in range(12, n - 1):
                if hours[i] >= 14 or np.isnan(vol_ratio[i]) or np.isnan(rsi[i]):
                    continue
                # 라벨
                entry = c[i]; tp_px = entry*(1+target); sl_px = entry*(1-stop); win = 0
                for j in range(i+1, min(i+1+horizon, n)):
                    if low[j] <= sl_px: win = 0; break
                    if h[j] >= tp_px: win = 1; break
                X.append([
                    vol_ratio[i], c[i]/vwap[i]-1 if vwap[i] > 0 else 0,
                    c[i]/day_open-1 if day_open > 0 else 0,
                    c[i]/run_high[i]-1 if run_high[i] > 0 else 0,
                    rsi[i], ret3[i] if not np.isnan(ret3[i]) else 0, gs[i], rng[i],
                    1.0 if c[i] > vwap[i] else 0.0, float(hours[i]),
                    (c[i]-low[i])/(h[i]-low[i]) if h[i] > low[i] else 0.5,
                    c[i]/run_low[i]-1 if run_low[i] > 0 else 0, ds[i],
                    v[i]/run_max_vol[i] if run_max_vol[i] > 0 else 0,
                ])
                y.append(win); dates.append(d)
    return np.array(X), np.array(y), np.array(dates)


def run(args):
    target, stop = args.target/100, args.stop/100
    X, y, dates = build(args.cache, args.horizon, target, stop)
    if len(y) < 1000:
        print("샘플 부족"); return 1
    udates = sorted(set(dates))
    split = udates[int(len(udates)*0.7)]
    tr = dates <= split; te = dates > split
    base_be = stop/(target+stop)
    cost = args.cost/100

    model = HistGradientBoostingClassifier(max_iter=200, max_depth=4,
                                           learning_rate=0.05, min_samples_leaf=200)
    model.fit(X[tr], y[tr])
    proba = model.predict_proba(X[te])[:, 1]
    yte = y[te]

    print(f"{Path(args.cache).name}: 학습 {tr.sum():,} / 검증 {te.sum():,} | "
          f"라벨 +{args.target}% before -{args.stop}% (손익분기 승률 {base_be:.0%})")
    print(f"OOS 기본 승률(전체): {yte.mean():.1%}\n")
    print("ML 예측확률 상위 X% 만 진입했을 때 OOS 실제 성과:")
    print(f"{'상위':>6}{'건수':>8}{'실제승률':>9}{'기대%(비용후)':>14}")
    for pct in (0.02, 0.05, 0.10, 0.20, 0.50):
        k = int(len(proba)*pct)
        if k < 30:
            continue
        idx = np.argsort(proba)[::-1][:k]
        wr = yte[idx].mean()
        exp = (wr*target - (1-wr)*stop - cost) * 100
        flag = "  <== 비용 넘김!" if exp > 0 else ""
        print(f"{pct*100:>5.0f}%{k:>8}{wr:>8.1%}{exp:>13.2f}%{flag}")

    imp = sorted(zip(FEATURES, model.feature_importances_ if hasattr(model, 'feature_importances_') else [0]*len(FEATURES)),
                 key=lambda x: -x[1]) if hasattr(model, 'feature_importances_') else []
    # HistGB는 feature_importances_ 없음 → permutation 생략, 대신 상관 출력
    print("\n(상위예측 승률이 기본보다 확 높고 기대%가 +면 → 데이터 집합체에 값 있음)")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="/tmp/kq_5m.pkl")
    p.add_argument("--horizon", type=int, default=12)
    p.add_argument("--target", type=float, default=2.0)
    p.add_argument("--stop", type=float, default=1.5)
    p.add_argument("--cost", type=float, default=0.5)
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
