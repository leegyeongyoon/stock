"""분봉(+호가/체결강도) → ML 특징 행렬. 손으로 찾은 모든 신호를 한곳에서 만든다.

순수 함수(numpy/pandas). data = {code: DataFrame(open/high/low/close/volume, datetime index)}.
orderflow = {code: DataFrame(exec_strength/bid_ask_ratio, captured_at index)} (옵션).
"""

from typing import Optional

import numpy as np

from src.strategies.intraday.base import rolling_mean_np, rsi_np

PRICE_FEATURES = [
    "vol_ratio", "vwap_ext", "from_open", "from_high", "rsi", "ret3",
    "green_streak", "bar_range", "above_vwap", "hour", "close_strength",
    "from_low", "down_streak", "rel_vol_daymax",
    "prior_run10", "bars_since_high", "pullback_vol", "accel",
]
FLOW_FEATURES = ["exec_strength", "bid_ask_ratio"]


def _align_flow(bar_times, flow):
    """각 봉 시각에 직전(<=) 호가 스냅샷 매핑 → (exec_strength[], bid_ask_ratio[])."""
    n = len(bar_times)
    if flow is None or flow.empty:
        return np.full(n, np.nan), np.full(n, np.nan)
    ft = flow.index.to_numpy().astype("datetime64[ns]")
    es = flow["exec_strength"].to_numpy(float)
    br = flow["bid_ask_ratio"].to_numpy(float)
    bt = np.array(list(bar_times), dtype="datetime64[ns]")
    idx = np.searchsorted(ft, bt, side="right") - 1
    ok = idx >= 0
    out_es = np.where(ok, es[np.clip(idx, 0, len(es) - 1)], np.nan)
    out_br = np.where(ok, br[np.clip(idx, 0, len(br) - 1)], np.nan)
    return out_es, out_br


def build_features(
    data: dict,
    horizon: int = 20,
    target: float = 0.015,
    stop: float = 0.01,
    orderflow: Optional[dict] = None,
    max_entry_hour: int = 14,
):
    """(X, y, dates, codes, feature_names) 반환. orderflow가 있으면 2특징 추가."""
    use_flow = orderflow is not None
    names = PRICE_FEATURES + (FLOW_FEATURES if use_flow else [])
    X, y, dates, codes = [], [], [], []

    for code, df in data.items():
        flow = orderflow.get(code) if use_flow else None
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
            gs = np.zeros(n); ds = np.zeros(n); since_h = np.zeros(n, int)
            for i in range(n):
                gs[i] = gs[i - 1] + 1 if (i > 0 and gr[i]) else gr[i]
                ds[i] = ds[i - 1] + 1 if (i > 0 and rd[i]) else rd[i]
                since_h[i] = 0 if (i == 0 or h[i] >= rh[i - 1]) else since_h[i - 1] + 1
            rng = (h - low) / np.where(c > 0, c, 1)
            hours = np.array([getattr(ts, "hour", 0) for ts in day.index])
            f_es, f_br = _align_flow(list(day.index), flow) if use_flow else (None, None)

            for i in range(14, n - 1):
                if hours[i] >= max_entry_hour or np.isnan(vr[i]) or np.isnan(rsi[i]):
                    continue
                prun = c[i] / c[i - 10] - 1 if i >= 10 and c[i - 10] > 0 else 0.0
                up_vol = v[max(0, i - 8):max(1, i - 2)].mean()
                pb_vol = v[max(0, i - 2):i + 1].mean()
                pbv = (pb_vol / up_vol) if up_vol > 0 else 1.0
                accel = ((c[i] / c[i - 1] - 1) - (c[i - 1] / c[i - 2] - 1)
                         if i >= 2 and c[i - 1] > 0 and c[i - 2] > 0 else 0.0)
                entry = c[i]; tpx = entry * (1 + target); spx = entry * (1 - stop); win = 0
                for j in range(i + 1, min(i + 1 + horizon, n)):
                    if low[j] <= spx:
                        win = 0; break
                    if h[j] >= tpx:
                        win = 1; break
                row = [
                    vr[i], c[i] / vwap[i] - 1 if vwap[i] > 0 else 0,
                    c[i] / dopen - 1 if dopen > 0 else 0, c[i] / rh[i] - 1 if rh[i] > 0 else 0,
                    rsi[i], ret3[i] if not np.isnan(ret3[i]) else 0, gs[i], rng[i],
                    1.0 if c[i] > vwap[i] else 0.0, float(hours[i]),
                    (c[i] - low[i]) / (h[i] - low[i]) if h[i] > low[i] else 0.5,
                    c[i] / rl[i] - 1 if rl[i] > 0 else 0, ds[i],
                    v[i] / rmv[i] if rmv[i] > 0 else 0, prun, float(since_h[i]), pbv, accel,
                ]
                if use_flow:
                    row += [f_es[i] if not np.isnan(f_es[i]) else 100.0,
                            f_br[i] if not np.isnan(f_br[i]) else 1.0]
                X.append(row); y.append(win); dates.append(d); codes.append(code)

    return (np.array(X), np.array(y), np.array(dates), np.array(codes), names)
