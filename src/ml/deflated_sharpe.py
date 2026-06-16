"""디플레이티드 샤프 비율(DSR) — 다중검정 선택편향 보정.

López de Prado, "The Deflated Sharpe Ratio" (2014) / AFML Ch.8.
전략 N개를 시도해 '최고'를 고르면, 그 샤프는 운(선택편향)으로 부풀려진다.
DSR = 관측 샤프가 "N번 시도 중 무엣지 기대 최대치(SR0)"를 넘을 확률.
- 시도 수 N, 시도별 샤프 분산, 표본수 T, 수익률 비정규성(skew/kurt) 반영.
- DSR > 0.95 면 그 최고 전략이 운이 아닐 가능성 높음.
"""
import numpy as np
from scipy.stats import kurtosis, norm, skew

EULER = 0.5772156649015329


def sharpe_stats(returns) -> tuple[float, int, float, float]:
    """수익률 시리즈 → (샤프, 표본수, 왜도, 첨도(비초과))."""
    r = np.asarray(returns, float)
    sd = r.std(ddof=1)
    sr = float(r.mean() / sd) if sd > 0 else 0.0
    return sr, len(r), float(skew(r)), float(kurtosis(r, fisher=False))


def probabilistic_sharpe_ratio(sr: float, T: int, skw: float, krt: float,
                               sr0: float = 0.0) -> float:
    """PSR: 관측 샤프 sr이 기준 sr0보다 클 확률 (비정규성 보정)."""
    den = np.sqrt(max(1e-12, 1 - skw * sr + (krt - 1) / 4 * sr ** 2))
    return float(norm.cdf((sr - sr0) * np.sqrt(max(1, T - 1)) / den))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """무엣지 전략 N개 시도 시 기대되는 최대 샤프 (deflation 기준선 SR0)."""
    if n_trials < 2 or var_sr <= 0:
        return 0.0
    z1 = norm.ppf(1 - 1.0 / n_trials)
    z2 = norm.ppf(1 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(var_sr) * ((1 - EULER) * z1 + EULER * z2))


def deflated_sharpe_ratio(sr_best: float, sr_trials, T: int,
                          skw: float, krt: float) -> tuple[float, float]:
    """DSR = PSR(sr0 = N시도 무엣지 기대최대). 반환 (DSR, SR0)."""
    sr0 = expected_max_sharpe(len(sr_trials), float(np.var(sr_trials, ddof=1)))
    return probabilistic_sharpe_ratio(sr_best, T, skw, krt, sr0), sr0
