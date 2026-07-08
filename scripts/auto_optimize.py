#!/usr/bin/env python3
"""연속학습 — 누적 데이터로 ML 재학습해 조건을 고도화하고 최적 모델을 저장한다.

매일 수집된 1분봉(+호가/체결강도)을 전부 모아 GradientBoosting 학습 → walk-forward로 검증 →
검증 성과가 개선되면 모델 저장(models/ml_gate_latest.pkl) + 이력 기록(optimize_log.json).
매 실행 = 1회 고도화. 데이터가 쌓일수록 조건이 정교해지고 신뢰도가 오른다.

오프라인 테스트: --cache /tmp/kis_today_1m.pkl
실데이터(당신 PC): --start 2026-06-15 --end 2026-07-15  (DB의 ohlcv_intraday + orderflow_snapshots)
"""

import argparse
import json
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

import numpy as np  # noqa: E402
from sklearn.ensemble import GradientBoostingClassifier  # noqa: E402

from src.ml.feature_builder import build_features  # noqa: E402
from src.ml.gate import MLGate  # noqa: E402
from src.ml.sample_weights import effective_sample_size, to_sample_weight  # noqa: E402

LOG_PATH = Path("models/optimize_log.json")


def load_from_db(start: datetime, end: datetime):
    """ohlcv_intraday(1m) + orderflow_snapshots 를 {code: df} 로 로드."""
    from sqlalchemy import text  # noqa: E402

    from src.database.connection import get_session
    from src.database.repositories import OHLCVIntradayRepository, OrderFlowSnapshotRepository
    data, flow = {}, {}
    with get_session() as s:
        codes = [r[0] for r in s.execute(text(
            "SELECT DISTINCT code FROM ohlcv_intraday WHERE interval='1m' "
            "AND datetime >= :a AND datetime <= :b"), {"a": start, "b": end}).fetchall()]
        bar_repo = OHLCVIntradayRepository(s); flow_repo = OrderFlowSnapshotRepository(s)
        for code in codes:
            df = bar_repo.get_by_code(code, "1m", start, end)
            if not df.empty:
                data[code] = df
                of = flow_repo.get_by_code(code, start, end)
                if not of.empty:
                    flow[code] = of
    return data, (flow or None)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", help="오프라인 테스트용 분봉 캐시(pkl)")
    p.add_argument("--start"); p.add_argument("--end")
    p.add_argument("--horizon", type=int, default=20)
    p.add_argument("--target", type=float, default=1.5)
    p.add_argument("--stop", type=float, default=1.0)
    p.add_argument("--cost", type=float, default=0.5)
    p.add_argument("--top-pct", type=float, default=0.10, dest="top_pct", help="진입 상위 비율")
    a = p.parse_args()
    tgt, stp, cost = a.target / 100, a.stop / 100, a.cost / 100

    if a.cache:
        data = pickle.loads(Path(a.cache).read_bytes()); flow = None
        src = Path(a.cache).name
    else:
        if not (a.start and a.end):
            p.error("--cache 또는 --start/--end 필요")
        s = datetime.strptime(a.start, "%Y-%m-%d"); e = datetime.strptime(a.end, "%Y-%m-%d") + timedelta(days=1)
        data, flow = load_from_db(s, e); src = f"DB {a.start}~{a.end}"
    if not data:
        print("데이터 없음"); return 1

    X, y, dates, codes, names, w = build_features(data, a.horizon, tgt, stp, orderflow=flow,
                                                  return_weights=True)
    if len(y) < 500:
        print(f"샘플 부족 {len(y)} — 더 수집 필요"); return 1

    # 검증 분할: 날짜 충분하면 walk-forward(최근일 OOS), 아니면 종목 분리
    udates = sorted(set(dates))
    if len(udates) >= 5:
        split = udates[int(len(udates) * 0.7)]
        tr = dates <= split; te = dates > split
        mode = f"날짜 walk-forward (학습 ~{split}, 검증 이후)"
    else:
        uniq = sorted(set(codes)); np.random.RandomState(42).shuffle(uniq)
        train_codes = set(uniq[:max(1, int(len(uniq) * 0.7))])
        tr = np.array([c in train_codes for c in codes]); te = ~tr
        mode = f"종목 분리 (날짜 {len(udates)}일뿐)"

    model = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                                       min_samples_leaf=100, subsample=0.8, random_state=0)
    model.fit(X[tr], y[tr], sample_weight=to_sample_weight(w[tr]))
    tr_proba = model.predict_proba(X[tr])[:, 1]
    thr = float(np.quantile(tr_proba, 1 - a.top_pct))
    te_proba = model.predict_proba(X[te])[:, 1]
    sel = te_proba >= thr
    wr = float(y[te][sel].mean()) if sel.sum() else 0.0
    exp = (wr * tgt - (1 - wr) * stp - cost) * 100
    be = stp / (tgt + stp)

    flow_tag = "호가포함" if flow else "가격만"
    print(f"=== 고도화 1회 ({src}, {flow_tag}) ===")
    eff = effective_sample_size(w)
    print(f"샘플 {len(y):,} (유효 {eff:,.0f} / 고유성 {eff/len(y):.3f}) / {len(udates)}일 / "
          f"{len(set(codes))}종목 | 검증: {mode}")
    print(f"검증 기본승률 {y[te].mean():.1%} | 상위{a.top_pct*100:.0f}% 선별 승률 {wr:.1%} "
          f"(손익분기 {be:.0%}) | 기대 {exp:+.2f}%{'  <== 비용 넘김!' if exp > 0 else ''}")
    top_feats = sorted(zip(names, model.feature_importances_), key=lambda x: -x[1])[:6]
    print("핵심 조건:", ", ".join(f"{n}({v:.2f})" for n, v in top_feats))

    # 이력 기록 + 개선 시 모델 저장
    LOG_PATH.parent.mkdir(exist_ok=True)
    log = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else []
    prev_best = max((r["oos_exp"] for r in log), default=-1e9)
    record = {"src": src, "flow": bool(flow), "n": len(y), "days": len(udates),
              "oos_winrate": round(wr, 4), "oos_exp": round(exp, 3), "threshold": round(thr, 4),
              "top_features": [n for n, _ in top_feats]}
    log.append(record)
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2))

    if exp > prev_best:
        MLGate(model, names, thr).save()
        print(f"모델 저장 (이전 최고 기대 {prev_best:+.2f}% → {exp:+.2f}%) → models/ml_gate_latest.pkl")
    else:
        print(f"이전 최고({prev_best:+.2f}%) 미달 → 모델 미갱신")
    print(f"이력 {len(log)}회 기록 → {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
