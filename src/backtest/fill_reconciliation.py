"""모의 포워드 체결 리컨실 — 백테스트 가정 vs 모의 실측 (실거래 진입 게이트).

모든 신호에 대해 '의도한 체결(intended)'과 '실제 모의 체결(actual)'을 비교해
  - 실현 슬리피지(bp): 백테스트가 가정한 것보다 실제로 얼마나 불리하게 체결됐나
  - 체결 적중률: 신호 대비 실제 체결 비율(특히 상따 접근의 미체결)
  - 승률 하락폭: 백테스트 대비 모의 승률
을 산출한다. 이 값들이 백테스트 가정과 충분히 일치해야 실거래로 넘어간다.

전부 순수 함수라 오프라인 테스트가 가능하다(53%→25% 격차를 닫는 측정 메커니즘).
"""

from dataclasses import dataclass
from typing import Literal, Optional

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class FillRecord:
    """한 신호의 의도 체결 vs 실제 체결."""

    code: str
    side: Side
    tier: str
    intended_price: float
    intended_qty: int
    actual_price: Optional[float]  # 미체결이면 None
    actual_qty: int
    reason: str = ""  # filled / partial / blocked / failed
    is_win: Optional[bool] = None  # 청산 결과(있으면). 승률 집계용

    @property
    def filled(self) -> bool:
        return self.actual_qty > 0 and self.actual_price is not None

    @property
    def adverse_slippage_bps(self) -> Optional[float]:
        """불리한 방향 슬리피지(bp). 매수=실제가 더 높음, 매도=실제가 더 낮음이 (+)비용."""
        if not self.filled or self.intended_price <= 0:
            return None
        if self.side == "buy":
            return (self.actual_price - self.intended_price) / self.intended_price * 10_000.0
        return (self.intended_price - self.actual_price) / self.intended_price * 10_000.0


def reconcile(fills: list[FillRecord]) -> dict:
    """체결 적중률·실현 슬리피지·승률 집계(전체 + 티어별)."""
    n_signals = len(fills)
    filled = [f for f in fills if f.filled]
    n_filled = len(filled)

    slips = [f.adverse_slippage_bps for f in filled if f.adverse_slippage_bps is not None]
    avg_slip = sum(slips) / len(slips) if slips else 0.0

    wins = [f for f in filled if f.is_win is True]
    losses = [f for f in filled if f.is_win is False]
    decided = len(wins) + len(losses)
    win_rate = (len(wins) / decided) if decided else 0.0

    tiers: dict[str, dict] = {}
    for f in fills:
        t = tiers.setdefault(f.tier, {"signals": 0, "filled": 0, "slip_sum": 0.0, "slip_n": 0})
        t["signals"] += 1
        if f.filled:
            t["filled"] += 1
            s = f.adverse_slippage_bps
            if s is not None:
                t["slip_sum"] += s
                t["slip_n"] += 1

    by_tier = {
        name: {
            "signals": v["signals"],
            "fill_rate": round(v["filled"] / v["signals"], 4) if v["signals"] else 0.0,
            "avg_slippage_bps": round(v["slip_sum"] / v["slip_n"], 2) if v["slip_n"] else 0.0,
        }
        for name, v in tiers.items()
    }

    return {
        "n_signals": n_signals,
        "n_filled": n_filled,
        "fill_rate": round(n_filled / n_signals, 4) if n_signals else 0.0,
        "avg_adverse_slippage_bps": round(avg_slip, 2),
        "win_rate": round(win_rate, 4),
        "by_tier": by_tier,
    }


def go_live_gate(
    mock_summary: dict,
    backtest_slippage_bps: float,
    backtest_win_rate: float,
    *,
    min_fill_rate: float = 0.70,
    slippage_tolerance_mult: float = 1.5,
    max_winrate_drop: float = 0.15,
) -> dict:
    """모의 실측이 백테스트 가정과 충분히 일치하는지 → 실거래 진입 게이트.

    통과 조건(전부 만족):
      - 체결 적중률 >= min_fill_rate
      - 실현 슬리피지 <= 백테스트 슬리피지 × slippage_tolerance_mult
      - 승률 하락폭(백테스트-모의) <= max_winrate_drop
    """
    fill_rate = mock_summary["fill_rate"]
    mock_slip = mock_summary["avg_adverse_slippage_bps"]
    mock_wr = mock_summary["win_rate"]

    fill_ok = fill_rate >= min_fill_rate
    slip_ok = mock_slip <= backtest_slippage_bps * slippage_tolerance_mult
    winrate_drop = backtest_win_rate - mock_wr
    wr_ok = winrate_drop <= max_winrate_drop

    return {
        "passed": bool(fill_ok and slip_ok and wr_ok),
        "fill_ok": fill_ok,
        "slippage_ok": slip_ok,
        "winrate_ok": wr_ok,
        "fill_rate": fill_rate,
        "mock_slippage_bps": mock_slip,
        "backtest_slippage_bps": backtest_slippage_bps,
        "winrate_drop": round(winrate_drop, 4),
    }
