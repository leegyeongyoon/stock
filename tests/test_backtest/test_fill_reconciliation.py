"""fill_reconciliation 단위 테스트 (순수, 오프라인) — 실거래 진입 게이트 측정."""

import pytest

from src.backtest.fill_reconciliation import FillRecord, go_live_gate, reconcile


def buy(code, intended, actual, qty=100, aqty=None, tier="BALANCED", win=None, reason="filled"):
    return FillRecord(code, "buy", tier, intended, qty, actual,
                      qty if aqty is None else aqty, reason, win)


class TestAdverseSlippage:
    def test_buy_higher_is_positive_cost(self):
        f = buy("A", 10_000, 10_050)  # +50bp
        assert f.adverse_slippage_bps == pytest.approx(50.0)

    def test_sell_lower_is_positive_cost(self):
        f = FillRecord("A", "sell", "BALANCED", 10_000, 100, 9_950, 100)
        assert f.adverse_slippage_bps == pytest.approx(50.0)

    def test_unfilled_has_no_slippage(self):
        f = FillRecord("A", "buy", "AGGRESSIVE", 10_000, 100, None, 0, "blocked")
        assert not f.filled
        assert f.adverse_slippage_bps is None


class TestReconcile:
    def test_fill_rate_and_avg_slippage(self):
        fills = [
            buy("A", 10_000, 10_050),               # filled, +50bp
            buy("B", 20_000, 20_040),               # filled, +20bp
            FillRecord("C", "buy", "AGGRESSIVE", 5_000, 100, None, 0, "blocked"),  # 미체결(상한가)
        ]
        s = reconcile(fills)
        assert s["n_signals"] == 3
        assert s["n_filled"] == 2
        assert s["fill_rate"] == pytest.approx(2 / 3, abs=1e-3)
        assert s["avg_adverse_slippage_bps"] == pytest.approx(35.0)

    def test_win_rate_from_decided(self):
        fills = [
            buy("A", 10_000, 10_010, win=True),
            buy("B", 10_000, 10_010, win=True),
            buy("C", 10_000, 10_010, win=False),
        ]
        assert reconcile(fills)["win_rate"] == pytest.approx(2 / 3, abs=1e-3)

    def test_per_tier_breakdown(self):
        fills = [
            buy("A", 10_000, 10_050, tier="BALANCED"),
            FillRecord("C", "buy", "AGGRESSIVE", 5_000, 100, None, 0, "blocked"),
        ]
        s = reconcile(fills)
        assert s["by_tier"]["BALANCED"]["fill_rate"] == 1.0
        assert s["by_tier"]["AGGRESSIVE"]["fill_rate"] == 0.0

    def test_empty(self):
        s = reconcile([])
        assert s["n_signals"] == 0 and s["fill_rate"] == 0.0


class TestGoLiveGate:
    def _summary(self, fill_rate, slip, wr):
        return {"fill_rate": fill_rate, "avg_adverse_slippage_bps": slip, "win_rate": wr}

    def test_passes_when_aligned(self):
        g = go_live_gate(self._summary(0.85, 30.0, 0.55), backtest_slippage_bps=25.0, backtest_win_rate=0.60)
        assert g["passed"]

    def test_fails_on_low_fill_rate(self):
        g = go_live_gate(self._summary(0.50, 20.0, 0.60), backtest_slippage_bps=25.0, backtest_win_rate=0.60)
        assert not g["passed"] and not g["fill_ok"]

    def test_fails_on_excess_slippage(self):
        g = go_live_gate(self._summary(0.90, 100.0, 0.60), backtest_slippage_bps=25.0, backtest_win_rate=0.60)
        assert not g["passed"] and not g["slippage_ok"]

    def test_fails_on_winrate_collapse(self):
        # 백테스트 60% → 모의 25% (= 53%→25% 실패 패턴) → 게이트 차단
        g = go_live_gate(self._summary(0.90, 30.0, 0.25), backtest_slippage_bps=25.0, backtest_win_rate=0.60)
        assert not g["passed"] and not g["winrate_ok"]
        assert g["winrate_drop"] == pytest.approx(0.35)
