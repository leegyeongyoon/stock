#!/usr/bin/env python3
"""추세 태우기(불타기/트레일링) 기대값 테스트 — 승자를 안 자르고 끝까지 태운다.

기존 테스트는 +2~3%에서 익절해 승자를 잘랐다. 여기선 반대로:
  진입: 좋은 자리(끼 + 저점서 반등 + 변동성 + VWAP위 + 오전)
  청산: 손절은 짧게(-S%), 익절은 안 함 — 고점 대비 trail% 트레일링으로 끝까지 태움.
승률은 낮아도 승자가 크게 먹으면 +가 되는지 본다. 종목당 동시 1포지션(겹침 없음).

DATABASE_URL 불필요(캐시만 사용). 사용:
    .venv/bin/python scripts/test_trend_ride_yf.py --cache /tmp/kq_5m.pkl --trail 3 --stop 2 --cost 0.5
"""

import argparse
import pickle
from pathlib import Path

import numpy as np


def sim(cache, trail, stop, cost, max_hold, range_thr, low_thr, surge_thr, max_hour):
    data = pickle.loads(Path(cache).read_bytes())
    trail, stop, cost = trail / 100.0, stop / 100.0, cost / 100.0
    rets, wins, n = [], 0, 0
    mfe_capture = []
    for code, df in data.items():
        for _, day in df.groupby(df.index.date):
            o = day["open"].to_numpy(float); h = day["high"].to_numpy(float)
            low = day["low"].to_numpy(float); c = day["close"].to_numpy(float)
            v = day["volume"].to_numpy(float)
            m = len(c)
            if m < 8:
                continue
            tp = (h + low + c) / 3.0
            cumv = np.cumsum(v)
            vwap = np.where(cumv > 0, np.cumsum(tp * v) / np.maximum(cumv, 1), c)
            run_high = np.maximum.accumulate(h)
            run_low = np.minimum.accumulate(low)
            day_open = o[0]
            rng = (h - low) / np.where(c > 0, c, 1)
            hours = np.array([getattr(ts, "hour", 0) for ts in day.index])

            i = 4
            while i < m - 1:
                # 진입 조건(데이터에서 발견한 좋은 자리)
                entry_ok = (
                    hours[i] <= max_hour
                    and rng[i] >= range_thr
                    and run_low[i] > 0 and (c[i] / run_low[i] - 1) >= low_thr
                    and vwap[i] > 0 and c[i] > vwap[i]
                    and c[i] > o[i]
                    and day_open > 0 and (run_high[i] / day_open - 1) >= surge_thr
                )
                if not entry_ok:
                    i += 1
                    continue
                entry = c[i]
                peak = entry
                exit_px = None
                j = i + 1
                end = min(i + max_hold, m - 1)
                while j <= end:
                    peak = max(peak, h[j])
                    eff_stop = max(entry * (1 - stop), peak * (1 - trail))
                    if low[j] <= eff_stop:
                        exit_px = eff_stop
                        break
                    j += 1
                if exit_px is None:
                    exit_px = c[end]
                    j = end
                ret = exit_px / entry - 1.0 - cost
                rets.append(ret)
                mfe_capture.append((peak / entry - 1.0, exit_px / entry - 1.0))
                wins += 1 if ret > 0 else 0
                n += 1
                i = j + 1  # 청산 후 다음 봉부터 (겹침 없음)

    if n == 0:
        print("진입 0건 — 조건 완화 필요")
        return
    rets = np.array(rets)
    win_rate = wins / n * 100
    avg = rets.mean() * 100
    med = np.median(rets) * 100
    gains = rets[rets > 0].sum()
    losses = abs(rets[rets <= 0].sum())
    pf = gains / losses if losses > 0 else float("inf")
    big = (rets >= 0.05).mean() * 100  # +5% 이상 비율
    print(f"  trail{trail*100:.0f}% stop{stop*100:.0f}% 비용{cost*100:.1f}% | "
          f"거래 {n} 승률 {win_rate:.1f}% 거래당평균 {avg:+.2f}%(중앙 {med:+.2f}%) "
          f"PF {pf:.2f} +5%이상 {big:.0f}% | 기대값 {avg:+.2f}%")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="/tmp/kq_5m.pkl")
    p.add_argument("--trail", type=float, default=3.0, help="트레일링 폭(퍼센트)")
    p.add_argument("--stop", type=float, default=2.0, help="초기 손절(퍼센트)")
    p.add_argument("--cost", type=float, default=0.5, help="왕복 비용+슬리피지(퍼센트)")
    p.add_argument("--max-hold", type=int, default=40, dest="max_hold", help="최대 보유 봉수")
    p.add_argument("--range-thr", type=float, default=0.008, dest="range_thr")
    p.add_argument("--low-thr", type=float, default=0.04, dest="low_thr")
    p.add_argument("--surge-thr", type=float, default=0.02, dest="surge_thr")
    p.add_argument("--max-hour", type=int, default=11, dest="max_hour")
    a = p.parse_args()
    print(f"=== 추세 태우기 테스트 ({Path(a.cache).name}) ===")
    sim(a.cache, a.trail, a.stop, a.cost, a.max_hold,
        a.range_thr, a.low_thr, a.surge_thr, a.max_hour)


if __name__ == "__main__":
    raise SystemExit(main())
