"""표본 고유성(uniqueness) 가중치 — 겹치는 라벨 보정.

López de Prado, *Advances in Financial Machine Learning* Ch.4.
triple-barrier 라벨은 앞으로 horizon봉을 내다봐서 이웃 표본끼리 라벨 구간이 겹친다
→ 표본이 서로 독립이 아님 → 명목 표본수보다 '유효 표본수'가 훨씬 적다.
동시성(concurrency)을 세어 중복 표본을 다운웨이트한다.
구간이 날짜 경계를 안 넘으므로 동시성은 그룹(종목-일) 내에서만 계산한다.
"""
from collections import defaultdict

import numpy as np


def uniqueness_weights(group_ids, starts, ends) -> np.ndarray:
    """각 표본의 평균 고유성 = 라벨 구간 동안 1/동시성 의 평균.

    Args:
        group_ids: 표본별 그룹 id (종목-일 단위 — 동시성은 그룹 내에서만 셈)
        starts, ends: 표본별 라벨 시작/종료 봉 인덱스(그룹 내 상대)
    Returns:
        표본별 고유성(0~1). 1=완전 독립, 1/horizon≈겹침 최대.
    """
    group_ids = np.asarray(group_ids)
    starts = np.asarray(starts, int)
    ends = np.asarray(ends, int)
    n = len(group_ids)
    u = np.ones(n, float)

    idx_by_g: dict = defaultdict(list)
    for k in range(n):
        idx_by_g[group_ids[k]].append(k)

    for _g, idxs in idx_by_g.items():
        lo = min(starts[k] for k in idxs)
        hi = max(ends[k] for k in idxs)
        # 차분배열로 동시성 누적: conc[t] = t봉에 활성인 라벨 수
        diff = np.zeros(hi - lo + 2, int)
        for k in idxs:
            diff[starts[k] - lo] += 1
            diff[ends[k] - lo + 1] -= 1
        conc = np.cumsum(diff)
        for k in idxs:
            span = conc[starts[k] - lo: ends[k] - lo + 1]
            span = span[span > 0]
            u[k] = float(np.mean(1.0 / span)) if len(span) else 1.0
    return u


def effective_sample_size(weights) -> float:
    """유효 표본수 = 고유성 합 (≈ 명목 N / horizon)."""
    return float(np.asarray(weights, float).sum())


def to_sample_weight(uniqueness) -> np.ndarray:
    """sklearn sample_weight 용으로 평균 1 정규화(합=N)."""
    u = np.asarray(uniqueness, float)
    return u * (len(u) / u.sum()) if u.sum() > 0 else np.ones_like(u)
