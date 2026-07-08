#!/usr/bin/env python3
"""분봉 패턴 마이닝 — '오르는 봉'이 오르기 직전 공통 특징을 데이터에서 캐낸다.

전략을 가정하지 않고, 실제로 오른 구간을 라벨링한 뒤 그 직전 봉의 특징이
나머지와 어떻게 다른지 통계로 본다. 그 결과로 진입 규칙을 역설계한다.

라벨: 봉 i 종가 진입 가정, 다음 N봉 안에 -stop 전에 +target 먼저 도달하면 win(1).
캐시(/tmp/kq_5m.pkl, KOSDAQ movers 150종목 5분봉)를 사용.
"""

import argparse
import pickle
import sys
from collections import defaultdict
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np  # noqa: E402

from src.strategies.intraday.base import rsi_np, rolling_mean_np  # noqa: E402

CACHE = Path("/tmp/kq_5m.pkl")


def day_features(day_df):
    """하루치 봉별 특징 dict(numpy 배열)."""
    o = day_df["open"].to_numpy(float)
    h = day_df["high"].to_numpy(float)
    low = day_df["low"].to_numpy(float)
    c = day_df["close"].to_numpy(float)
    v = day_df["volume"].to_numpy(float)
    n = len(c)
    tp = (h + low + c) / 3.0
    cum_v = np.cumsum(v)
    vwap = np.where(cum_v > 0, np.cumsum(tp * v) / np.maximum(cum_v, 1), c)
    run_high = np.maximum.accumulate(h)
    day_open = o[0] if n else 0.0
    rmean = rolling_mean_np(v, 12)
    vbase = np.full(n, np.nan)
    vbase[1:] = rmean[:-1]
    vol_ratio = np.where((vbase > 0), v / np.where(vbase > 0, vbase, 1), np.nan)
    rsi = rsi_np(c, 14)
    ret3 = np.full(n, np.nan)
    ret3[3:] = c[3:] / c[:-3] - 1.0
    green = (c > o).astype(float)
    green_streak = np.zeros(n)
    for i in range(n):
        green_streak[i] = green_streak[i - 1] + 1 if (i > 0 and green[i]) else green[i]
    bar_range = (h - low) / np.where(c > 0, c, 1)
    hours = np.array([getattr(ts, "hour", 0) for ts in day_df.index])
    # 추가 공통값
    run_low = np.minimum.accumulate(low) if n else low
    red = (c < o).astype(float)
    down_streak = np.zeros(n)
    for i in range(n):
        down_streak[i] = down_streak[i - 1] + 1 if (i > 0 and red[i]) else red[i]
    run_max_vol = np.maximum.accumulate(v) if n else v
    return dict(o=o, h=h, low=low, c=c, v=v, n=n, vwap=vwap, run_high=run_high,
                day_open=day_open, vol_ratio=vol_ratio, rsi=rsi, ret3=ret3,
                green_streak=green_streak, bar_range=bar_range, hours=hours,
                run_low=run_low, down_streak=down_streak, run_max_vol=run_max_vol)


def label(f, i, N, target, stop):
    """봉 i 진입 → (win, MFE, MAE). win: N봉 내 +target before -stop(1/0)."""
    entry = f["c"][i]
    if entry <= 0:
        return None
    tp_px, sl_px = entry * (1 + target), entry * (1 - stop)
    win, decided = 0, False
    hi = lo = entry
    for j in range(i + 1, min(i + 1 + N, f["n"])):
        hi = max(hi, f["h"][j])
        lo = min(lo, f["low"][j])
        if not decided:
            if f["low"][j] <= sl_px:
                win, decided = 0, True
            elif f["h"][j] >= tp_px:
                win, decided = 1, True
    return win, hi / entry - 1.0, lo / entry - 1.0


def run(args):
    data = pickle.loads(Path(args.cache).read_bytes())
    N, target, stop = args.horizon, args.target / 100.0, args.stop / 100.0
    warm = 12

    rows = []  # (win, feat dict)
    for code, df in data.items():
        for _, day_df in df.groupby(df.index.date):
            if len(day_df) < warm + N + 2:
                continue
            f = day_features(day_df)
            for i in range(warm, f["n"] - 1):
                if f["hours"][i] >= 14:  # 장 막판 제외
                    continue
                res = label(f, i, N, target, stop)
                if res is None or np.isnan(f["vol_ratio"][i]) or np.isnan(f["rsi"][i]):
                    continue
                y, mfe, mae = res
                rows.append((y, mfe, mae, {
                    "vol_ratio": f["vol_ratio"][i],
                    "vwap_ext": f["c"][i] / f["vwap"][i] - 1 if f["vwap"][i] > 0 else 0,
                    "from_open": f["c"][i] / f["day_open"] - 1 if f["day_open"] > 0 else 0,
                    "from_high": f["c"][i] / f["run_high"][i] - 1 if f["run_high"][i] > 0 else 0,
                    "rsi": f["rsi"][i],
                    "ret3": f["ret3"][i] if not np.isnan(f["ret3"][i]) else 0,
                    "green_streak": f["green_streak"][i],
                    "bar_range": f["bar_range"][i],
                    "above_vwap": 1.0 if f["c"][i] > f["vwap"][i] else 0.0,
                    "hour": float(f["hours"][i]),
                    # 추가 공통값
                    "close_strength": (f["c"][i] - f["low"][i]) / (f["h"][i] - f["low"][i]) if f["h"][i] > f["low"][i] else 0.5,
                    "from_low": f["c"][i] / f["run_low"][i] - 1 if f["run_low"][i] > 0 else 0,
                    "down_streak": f["down_streak"][i],
                    "rel_vol_daymax": f["v"][i] / f["run_max_vol"][i] if f["run_max_vol"][i] > 0 else 0,
                }))

    if not rows:
        print("샘플 없음")
        return 1
    ys = np.array([r[0] for r in rows], dtype=float)
    mfes = np.array([r[1] for r in rows], dtype=float)
    maes = np.array([r[2] for r in rows], dtype=float)
    base = ys.mean()
    print(f"총 샘플 {len(rows):,}봉 | 라벨: 다음 {N}봉({N*5}분) 내 +{args.target}% before -{args.stop}%")
    print(f"기본 승률(무조건 진입): {base:.1%}\n")

    feats = list(rows[0][3].keys())
    print("=== 특징별 구간 승률 (승률 - 기본 = 엣지) ===")
    for feat in feats:
        vals = np.array([r[3][feat] for r in rows])
        # 사분위 경계
        qs = np.quantile(vals, [0, 0.25, 0.5, 0.75, 1.0])
        print(f"\n[{feat}]  (기본 {base:.1%})")
        for a, b in zip(qs[:-1], qs[1:]):
            mask = (vals >= a) & (vals <= b) if b == qs[-1] else (vals >= a) & (vals < b)
            if mask.sum() < 50:
                continue
            wr = ys[mask].mean()
            edge = wr - base
            bar = "+" * int(max(0, edge) * 100) or ("-" * int(max(0, -edge) * 100))
            print(f"   {a:+.3f}~{b:+.3f}: 승률 {wr:.1%} ({mask.sum():,}건) {edge:+.1%} {bar}")

    # 승자 vs 패자 평균 특징
    print("\n=== 승자 vs 패자 평균 특징 ===")
    win_mask = ys == 1
    print(f"{'특징':<14}{'승자평균':>12}{'패자평균':>12}")
    for feat in feats:
        vals = np.array([r[3][feat] for r in rows])
        print(f"{feat:<14}{vals[win_mask].mean():>12.4f}{vals[~win_mask].mean():>12.4f}")

    # === 조합(AND) 분석: 발견된 엣지를 겹치면 승률이 손익분기 위로 가나 ===
    # 임계값은 분위수 기반 → 5분봉/1분봉 무관하게 적응
    F = {k: np.array([r[3][k] for r in rows]) for k in feats}
    q_range = float(np.quantile(F["bar_range"], 0.75))   # 변동성 상위 25%
    q_high = float(np.quantile(F["from_high"], 0.25))    # 눌림 깊은 하위 25%
    q_open = float(np.quantile(np.abs(F["from_open"]), 0.60))
    q_low = float(np.quantile(F["from_low"], 0.75))       # 저점서 충분히 반등
    q_rv = float(np.quantile(F["rel_vol_daymax"], 0.75))  # 거래량 실린 봉
    cond = {
        f"변동성확장(range>={q_range:.3f})": F["bar_range"] >= q_range,
        "오전(hour<=11)": F["hour"] <= 11,
        f"눌림(from_high<={q_high:.3f})": F["from_high"] <= q_high,
        f"반등시작(from_low>={q_low:.3f})": F["from_low"] >= q_low,
        f"거래량(rel_vol>={q_rv:.3f})": F["rel_vol_daymax"] >= q_rv,
    }
    be = stop / (target + stop)  # 손익분기 승률(비용 전) = 위험/(보상+위험)
    print(f"\n=== 조합 AND 승률 (손익분기 ~{be:.0%}, 비용 전) ===")
    score = np.zeros(len(ys))
    for m in cond.values():
        score += m.astype(float)
    for s in range(0, len(cond) + 1):
        mask = score == s
        if mask.sum() >= 50:
            print(f"  조건 {s}개 충족: 승률 {ys[mask].mean():.1%} ({mask.sum():,}건)")
    # 최강 3개 AND
    import itertools
    keys = list(cond.keys())
    print("\n  [강한 조합 AND]")
    for combo in itertools.combinations(keys, 3):
        m = cond[combo[0]] & cond[combo[1]] & cond[combo[2]]
        if m.sum() >= 80:
            wr = ys[m].mean()
            flag = "  <== 손익분기 돌파" if wr >= be else ""
            print(f"   {' + '.join(c.split('(')[0] for c in combo)}: {wr:.1%} ({m.sum():,}건){flag}")

    # === MFE: 좋은 자리의 승자가 얼마나 멀리 가나 (익절 상향/트레일링 여지 판단) ===
    strong = (F["bar_range"] >= q_range) & (F["hour"] <= 11) & (F["from_high"] <= q_high)
    print(f"\n=== MFE 분석 (진입 후 {N}봉 내 최대 상승폭) ===")
    for name, m in [("전체", np.ones(len(ys), bool)),
                    ("강한자리(변동성+오전+눌림)", strong),
                    ("강한자리 중 win만", strong & (ys == 1))]:
        if m.sum() < 50:
            continue
        sub = mfes[m]
        print(f"  [{name}] {m.sum():,}건 | MFE 평균 {sub.mean():+.1%} 중앙값 {np.median(sub):+.1%} | "
              f">=+2% {(sub >= 0.02).mean():.0%} / >=+3% {(sub >= 0.03).mean():.0%} / >=+5% {(sub >= 0.05).mean():.0%}")
    print(f"  강한자리 MAE(최대 하락폭) 평균 {maes[strong].mean():+.1%}")

    # 강한자리에서 익절폭(T)별 기대값(손절 -stop 고정, MFE 기준 근사)
    print(f"\n=== 강한자리 익절폭별 기대 손익 (손절 -{args.stop}% 고정, MFE 근사) ===")
    s_mfe, s_mae = mfes[strong], maes[strong]
    for T in (0.015, 0.02, 0.03, 0.04, 0.05):
        # 손절 먼저면 -stop, 아니면 +T(도달) 또는 마감가 근사로 MFE(미달분은 0 근사)
        hit_stop = s_mae <= -stop
        hit_tp = (~hit_stop) & (s_mfe >= T)
        neither = (~hit_stop) & (~hit_tp)
        exp = (hit_tp.mean() * T) + (hit_stop.mean() * (-stop)) + (neither.mean() * 0.0)
        cost = 0.005  # 왕복 비용+슬리피지 근사 0.5%
        print(f"   TP +{T*100:.1f}%: 도달 {hit_tp.mean():.0%} / 손절 {hit_stop.mean():.0%} | "
              f"기대 {exp*100:+.2f}% (비용 0.5% 차감 {(exp-cost)*100:+.2f}%)")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="/tmp/kq_5m.pkl", help="분봉 캐시 경로(5m/1m)")
    p.add_argument("--horizon", type=int, default=12, help="전방 봉수")
    p.add_argument("--target", type=float, default=2.0, help="목표 상승(퍼센트)")
    p.add_argument("--stop", type=float, default=1.5, help="손절(퍼센트)")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
