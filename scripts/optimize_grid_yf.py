#!/usr/bin/env python3
"""전수 그리드 최적화 — 모든 손절/익절/트레일/부분익절 조합을 계산해 최적 알고리즘 탐색.

과적합 방지: 날짜를 IS(앞 70%)/OOS(뒤 30%)로 분리해 IS에서 좋은 게 OOS에서도 좋은지 본다.
진입은 데이터에서 발견한 좋은 자리(끼+저점반등+변동성+VWAP위+오전), 강도 2단계.
청산은 fixed(tp/sl) · trailing(trail/sl) · partial(절반 +P 후 트레일) 전수.

기대값/거래당손익은 비용(왕복) 차감 후. 종목당 동시 1포지션(겹침 없음).
사용: .venv/bin/python scripts/optimize_grid_yf.py --cache /tmp/kq_5m.pkl --cost 0.5
"""

import argparse
import itertools
import pickle
from pathlib import Path

import numpy as np


def precompute(data):
    out = []
    for code, df in data.items():
        for d, day in df.groupby(df.index.date):
            o = day["open"].to_numpy(float); h = day["high"].to_numpy(float)
            low = day["low"].to_numpy(float); c = day["close"].to_numpy(float)
            v = day["volume"].to_numpy(float)
            m = len(c)
            if m < 8:
                continue
            tp = (h + low + c) / 3.0
            cumv = np.cumsum(v)
            vwap = np.where(cumv > 0, np.cumsum(tp * v) / np.maximum(cumv, 1), c)
            A = dict(o=o, h=h, low=low, c=c, m=m, vwap=vwap,
                     run_high=np.maximum.accumulate(h), run_low=np.minimum.accumulate(low),
                     day_open=o[0], rng=(h - low) / np.where(c > 0, c, 1),
                     hours=np.array([getattr(ts, "hour", 0) for ts in day.index]))
            out.append((d, A))
    return out


def entry_ok(A, i, ep):
    return (
        A["hours"][i] <= ep["max_hour"]
        and A["rng"][i] >= ep["range"]
        and A["run_low"][i] > 0 and (A["c"][i] / A["run_low"][i] - 1) >= ep["low"]
        and A["vwap"][i] > 0 and A["c"][i] > A["vwap"][i]
        and A["c"][i] > A["o"][i]
        and A["day_open"] > 0 and (A["run_high"][i] / A["day_open"] - 1) >= ep["surge"]
    )


def exit_ret(A, i, xp, max_hold, cost):
    """진입 i 종가 → 청산 (return after cost, exit_bar)."""
    entry = A["c"][i]
    if entry <= 0:
        return None, i
    m = A["m"]; end = min(i + max_hold, m - 1)
    peak = entry
    style = xp["type"]
    if style == "fixed":
        tp_px, sl_px = entry * (1 + xp["tp"]), entry * (1 - xp["sl"])
        for j in range(i + 1, end + 1):
            if A["low"][j] <= sl_px:
                return (sl_px / entry - 1 - cost), j
            if A["h"][j] >= tp_px:
                return (tp_px / entry - 1 - cost), j
        return (A["c"][end] / entry - 1 - cost), end
    if style == "trail":
        for j in range(i + 1, end + 1):
            peak = max(peak, A["h"][j])
            stop = max(entry * (1 - xp["sl"]), peak * (1 - xp["trail"]))
            if A["low"][j] <= stop:
                return (stop / entry - 1 - cost), j
        return (A["c"][end] / entry - 1 - cost), end
    # partial: 절반 +P 익절, 나머지 트레일 (비용 양쪽 차감)
    half_done = False
    half_ret = 0.0
    p_px = entry * (1 + xp["p"])
    for j in range(i + 1, end + 1):
        peak = max(peak, A["h"][j])
        if not half_done and A["h"][j] >= p_px:
            half_done = True
            half_ret = (xp["p"] - cost)
        stop = max(entry * (1 - xp["sl"]), peak * (1 - xp["trail"]))
        if A["low"][j] <= stop:
            rest = (stop / entry - 1 - cost)
            return (0.5 * half_ret + 0.5 * rest) if half_done else (stop / entry - 1 - cost), j
    rest = (A["c"][end] / entry - 1 - cost)
    return (0.5 * half_ret + 0.5 * rest) if half_done else rest, end


def run_cfg(days, ep, xp, max_hold, cost, split_date):
    is_r, oos_r = [], []
    for d, A in days:
        i = 4
        while i < A["m"] - 1:
            if not entry_ok(A, i, ep):
                i += 1
                continue
            r, j = exit_ret(A, i, xp, max_hold, cost)
            if r is not None:
                (is_r if d <= split_date else oos_r).append(r)
            i = j + 1
    return is_r, oos_r


def summ(rets):
    if not rets:
        return (0, 0.0, 0.0)
    a = np.array(rets)
    return (len(a), a.mean() * 100, (a > 0).mean() * 100)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="/tmp/kq_5m.pkl")
    p.add_argument("--cost", type=float, default=0.5)
    p.add_argument("--max-hold", type=int, default=40, dest="max_hold")
    a = p.parse_args()
    cost = a.cost / 100.0

    data = pickle.loads(Path(a.cache).read_bytes())
    days = precompute(data)
    all_dates = sorted({d for d, _ in days})
    split_date = all_dates[int(len(all_dates) * 0.7)]
    print(f"{Path(a.cache).name}: {len(days)} 종목-일 / IS<= {split_date} < OOS / 비용 {a.cost}%\n")

    # 진입 강도 2단계
    entries = [
        dict(name="loose", max_hour=13, range=0.006, low=0.03, surge=0.015),
        dict(name="strict", max_hour=11, range=0.010, low=0.05, surge=0.03),
    ]
    # 청산 전수
    exits = []
    for tp in (1.5, 2, 3, 5):
        for sl in (1, 1.5, 2):
            exits.append(dict(type="fixed", tp=tp / 100, sl=sl / 100, name=f"fix tp{tp}/sl{sl}"))
    for tr in (2, 3, 5):
        for sl in (1.5, 2):
            exits.append(dict(type="trail", trail=tr / 100, sl=sl / 100, name=f"trail{tr}/sl{sl}"))
    for pp in (1.5, 2):
        for tr in (3, 5):
            exits.append(dict(type="partial", p=pp / 100, trail=tr / 100, sl=0.015, name=f"part+{pp}/tr{tr}"))

    results = []
    for ep, xp in itertools.product(entries, exits):
        is_r, oos_r = run_cfg(days, ep, xp, a.max_hold, cost, split_date)
        n_is, e_is, w_is = summ(is_r)
        n_oos, e_oos, w_oos = summ(oos_r)
        if n_is >= 50 and n_oos >= 20:
            results.append((ep["name"], xp["name"], n_is, e_is, w_is, n_oos, e_oos, w_oos))

    # OOS 기대값 기준 정렬
    results.sort(key=lambda r: r[6], reverse=True)
    print(f"{'진입':<7}{'청산':<16}{'IS거래':>7}{'IS기대%':>9}{'IS승률':>7}{'OOS거래':>8}{'OOS기대%':>10}{'OOS승률':>8}")
    print("-" * 74)
    for r in results[:18]:
        print(f"{r[0]:<7}{r[1]:<16}{r[2]:>7}{r[3]:>9.2f}{r[4]:>6.0f}%{r[5]:>8}{r[6]:>10.2f}{r[7]:>7.0f}%")
    print("\n(기대% = 거래당 평균손익, 비용 차감 후. OOS가 +면 진짜 엣지, IS만 +면 과적합)")


if __name__ == "__main__":
    raise SystemExit(main())
