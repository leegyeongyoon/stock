#!/usr/bin/env python3
"""리서치 에이전트 제안 후보 피처를 자동 구간분석 검증 → 승격 추천 알림.

launchd(com.gylee.stock.candidate-validate)로 매일 16:25 실행(리서치 16:15 직후).
- 최신 research/candidate_features_*.py 의 함수들을 동적 임포트(시그니처 보고 인자 맞춤)
- feature_builder와 동일 타깃(+1.5%/-1.0%/20봉)으로 상/하위 25% 승률차 ≥ +3%p 검증
- 결과를 logs/candidate_validation.log + macOS 알림. **코드 수정/승격은 사람이 한다(안전 게이트).**
"""
import glob
import importlib.util
import inspect
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

project = Path(__file__).parent.parent
sys.path.insert(0, str(project))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(project / ".env")
from sqlalchemy import text  # noqa: E402

from src.database.connection import get_session  # noqa: E402
from src.ml.feature_builder import PRICE_FEATURES, _align_flow, rolling_mean_np  # noqa: E402

HORIZON, TARGET, STOP, MAX_HOUR, THRESH = 20, 0.015, 0.01, 14, 3.0
LOG = project / "logs" / "candidate_validation.log"


def latest_candidate_file() -> Path | None:
    files = sorted(glob.glob(str(project / "research" / "candidate_features_*.py")))
    return Path(files[-1]) if files else None


def load_candidate_funcs(path: Path) -> dict:
    spec = importlib.util.spec_from_file_location("cand", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    funcs = {}
    for name in dir(m):
        obj = getattr(m, name)
        if (inspect.isfunction(obj) and not name.startswith("_")
                and obj.__module__ == m.__name__ and name not in PRICE_FEATURES):
            funcs[name] = obj
    return funcs


def load_data():
    with get_session() as s:
        rows = s.execute(text(
            "select code, datetime, open, high, low, close, volume from ohlcv_intraday "
            "where interval='1m' and datetime >= now() - interval '45 days' order by code, datetime"
        )).fetchall()
        ofr = s.execute(text(
            "select code, captured_at, exec_strength, bid_ask_ratio from orderflow_snapshots "
            "where captured_at >= now() - interval '45 days' order by code, captured_at"
        )).fetchall()
    df = pd.DataFrame(rows, columns=["code", "datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    of = pd.DataFrame(ofr, columns=["code", "captured_at", "exec_strength", "bid_ask_ratio"])
    of["captured_at"] = pd.to_datetime(of["captured_at"])
    for c in ("exec_strength", "bid_ask_ratio"):
        of[c] = pd.to_numeric(of[c], errors="coerce")
    flow = {code: g.set_index("captured_at")[["exec_strength", "bid_ask_ratio"]]
            for code, g in of.groupby("code")} if not of.empty else {}
    return df, flow


def collect(funcs: dict, df: pd.DataFrame, flow: dict):
    vals = {name: [] for name in funcs}
    ys = []
    for code, g in df.groupby("code"):
        fdf = flow.get(code)
        for _d, day in g.groupby(g["datetime"].dt.date):
            day = day.sort_values("datetime")
            h = day["high"].to_numpy(); low = day["low"].to_numpy()
            c = day["close"].to_numpy(); v = day["volume"].to_numpy()
            n = len(c)
            if n < 16 + HORIZON:
                continue
            rm = rolling_mean_np(v, 12); vb = np.full(n, np.nan); vb[1:] = rm[:-1]
            hours = day["datetime"].dt.hour.to_numpy()
            vr = np.where(vb > 0, v / np.where(vb > 0, vb, 1), np.nan)
            if fdf is not None and not fdf.empty:
                es, br = _align_flow(list(day["datetime"]), fdf)
            else:
                es = np.full(n, np.nan); br = np.full(n, np.nan)
            # 봉배열 + 체결강도(es)/잔량비(br) — orderflow 피처도 검증 가능하게 별칭 제공
            avail = {"h": h, "low": low, "c": c, "v": v, "vb": vb,
                     "es": es, "br": br, "exec_strength": es, "bid_ask_ratio": br}
            for i in range(14, n - 1):
                if hours[i] >= MAX_HOUR or np.isnan(vr[i]):
                    continue
                entry = c[i]; tpx = entry * (1 + TARGET); spx = entry * (1 - STOP); win = 0
                for j in range(i + 1, min(i + 1 + HORIZON, n)):
                    if low[j] <= spx:
                        win = 0; break
                    if h[j] >= tpx:
                        win = 1; break
                ys.append(win)
                for name, fn in funcs.items():
                    ps = inspect.signature(fn).parameters
                    kw = {k: avail[k] for k in ps if k in avail}
                    if "i" in ps:
                        kw["i"] = i
                    try:
                        vals[name].append(float(fn(**kw)))
                    except Exception:  # noqa: BLE001
                        vals[name].append(np.nan)
    return vals, np.array(ys, float)


def main() -> int:
    path = latest_candidate_file()
    if path is None:
        return 0
    funcs = load_candidate_funcs(path)
    lines = [f"[{datetime.now():%Y-%m-%d %H:%M}] 후보검증 ({path.name})"]
    if not funcs:
        lines.append("  검증할 신규 함수 없음(이미 승격됐거나 없음)")
        _write(lines, "신규 후보 없음")
        return 0

    df, flow = load_data()
    vals, ys = collect(funcs, df, flow)
    lines.append(f"  표본 {len(ys):,} / 기본승률 {ys.mean() * 100:.1f}%")
    recommend = []
    for name, raw in vals.items():
        f = np.array(raw); mask = ~np.isnan(f)
        f, yv = f[mask], ys[mask]
        if len(f) < 100:
            lines.append(f"  {name}: 표본부족"); continue
        q1, q3 = np.percentile(f, 25), np.percentile(f, 75)
        bot = yv[f <= q1].mean() * 100; top = yv[f >= q3].mean() * 100; diff = top - bot
        ok = abs(diff) >= THRESH
        lines.append(f"  {name}: 상위25% {top:.1f}% vs 하위25% {bot:.1f}% = {diff:+.1f}%p  "
                     f"{'✅ 승격추천' if ok else '❌ 미달'}")
        if ok:
            recommend.append(f"{name}({diff:+.1f}%p)")
    msg = "승격추천: " + ", ".join(recommend) if recommend else "승격할 후보 없음"
    lines.append(f"  → {msg}")
    _write(lines, msg)
    return 0


def _write(lines: list[str], notify_msg: str) -> None:
    report = "\n".join(lines)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(report + "\n")
    safe = notify_msg.replace('"', "'")
    os.system(f'osascript -e \'display notification "{safe}" with title "단타 피처 검증"\' 2>/dev/null')
    print(report)


if __name__ == "__main__":
    raise SystemExit(main())
