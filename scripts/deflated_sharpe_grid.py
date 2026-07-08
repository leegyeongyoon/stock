"""타깃/손절 그리드의 '최고' 전략에 디플레이티드 샤프 적용 — 운빨 보정.

각 구조의 선별 진입 거래수익(승=target-cost, 패=-stop-cost) → 샤프.
N개 시도 중 최고 샤프가 무엣지 기대최대(SR0)를 넘는지 DSR로 검정.
"""
import sys, importlib.util
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import GradientBoostingClassifier
sys.path.insert(0, "/Users/igyeong-yun/stock")
from src.ml.feature_builder import build_features
from src.ml.sample_weights import to_sample_weight
from src.ml.deflated_sharpe import sharpe_stats, deflated_sharpe_ratio

spec = importlib.util.spec_from_file_location("ao", "/Users/igyeong-yun/stock/scripts/auto_optimize.py")
ao = importlib.util.module_from_spec(spec); spec.loader.exec_module(ao)

COST, HORIZON, TOP = 0.005, 20, 0.10
s = datetime(2026, 5, 16); e = datetime.now() + timedelta(days=1)
data, flow = ao.load_from_db(s, e)
combos = [(1.5, 1.0), (2.0, 1.0), (2.5, 1.0), (3.0, 1.0), (2.0, 0.7), (1.0, 0.5), (3.0, 1.5)]

rows = []
for tp, sp in combos:
    tgt, stp = tp / 100, sp / 100
    X, y, dates, codes, names, w = build_features(data, HORIZON, tgt, stp, orderflow=flow, return_weights=True)
    udates = sorted(set(dates))
    if len(udates) >= 5:
        sp_d = udates[int(len(udates) * 0.7)]; tr = dates <= sp_d; te = dates > sp_d
    else:
        uniq = sorted(set(codes)); np.random.RandomState(42).shuffle(uniq)
        trc = set(uniq[:max(1, int(len(uniq) * 0.7))])
        tr = np.array([c in trc for c in codes]); te = ~tr
    m = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05,
                                   min_samples_leaf=100, subsample=0.8, random_state=0)
    m.fit(X[tr], y[tr], sample_weight=to_sample_weight(w[tr]))
    thr = float(np.quantile(m.predict_proba(X[tr])[:, 1], 1 - TOP))
    sel = m.predict_proba(X[te])[:, 1] >= thr
    wins = y[te][sel]
    rets = np.where(wins == 1, tgt - COST, -stp - COST)
    sr, T, skw, krt = sharpe_stats(rets)
    rows.append((f"{tp}/{sp}", sr, T, skw, krt, float(rets.mean()) * 100))

print(f"{'구조':>9} {'거래수':>6} {'거래당샤프':>9} {'기대값':>8}")
for nm, sr, T, skw, krt, mexp in rows:
    print(f"{nm:>9} {T:6d} {sr:9.4f} {mexp:+7.3f}%")

srs = [r[1] for r in rows]
best = int(np.argmax(srs))
nm, sr_b, T_b, skw_b, krt_b, _ = rows[best]
dsr, sr0 = deflated_sharpe_ratio(sr_b, srs, T_b, skw_b, krt_b)
print("-" * 44)
print(f"최고 구조: {nm} (샤프 {sr_b:.4f}, 거래 {T_b})")
print(f"무엣지 기대최대 SR0 (7시도 보정): {sr0:.4f}")
print(f"디플레이티드 샤프 DSR = {dsr:.3f}  ({'✅ 운 아님(>0.95)' if dsr > 0.95 else '❌ 운/엣지없음과 구분 불가'})")
