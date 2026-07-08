"""TierRiskState 단위 테스트 (순수, 오프라인)."""

import pytest

from src.risk.tier_risk import (
    AGGRESSIVE,
    BALANCED,
    TierLimits,
    TierRiskState,
    make_default_tiers,
)

EQUITY = 10_000_000


def _state(limits: TierLimits) -> TierRiskState:
    return TierRiskState("T", limits)


class TestConcurrencyAndTradeCount:
    def test_max_concurrent_blocks(self):
        s = _state(BALANCED)  # max_concurrent=3
        for i in range(3):
            assert s.can_enter(f"C{i}", None, EQUITY).allowed
            s.record_entry(f"C{i}", None)
        gate = s.can_enter("C9", None, EQUITY)
        assert not gate.allowed and "동시 포지션" in gate.reason

    def test_max_trades_per_day_blocks(self):
        s = _state(AGGRESSIVE)  # max_trades_per_day=4, max_concurrent=2
        for i in range(4):
            s.record_entry(f"C{i}", None)
            s.record_exit(f"C{i}", None, pnl=1000, equity=EQUITY)
        gate = s.can_enter("CX", None, EQUITY)
        assert not gate.allowed and "거래수 초과" in gate.reason


class TestNoAverageDown:
    def test_same_code_blocked_while_open(self):
        s = _state(BALANCED)
        s.record_entry("AAA", None)
        gate = s.can_enter("AAA", None, EQUITY)
        assert not gate.allowed and "물타기" in gate.reason

    def test_reentry_allowed_after_exit(self):
        s = _state(BALANCED)
        s.record_entry("AAA", None)
        s.record_exit("AAA", None, pnl=500, equity=EQUITY)
        assert s.can_enter("AAA", None, EQUITY).allowed


class TestThemeExposure:
    def test_single_theme_capped(self):
        s = _state(BALANCED)  # max_per_theme=1
        s.record_entry("AAA", "AI")
        gate = s.can_enter("BBB", "AI", EQUITY)
        assert not gate.allowed and "테마 노출" in gate.reason

    def test_different_theme_ok(self):
        s = _state(BALANCED)
        s.record_entry("AAA", "AI")
        assert s.can_enter("BBB", "2차전지", EQUITY).allowed

    def test_theme_freed_after_exit(self):
        s = _state(BALANCED)
        s.record_entry("AAA", "AI")
        s.record_exit("AAA", "AI", pnl=0, equity=EQUITY)
        assert s.can_enter("BBB", "AI", EQUITY).allowed


class TestDailyLossCap:
    def test_loss_cap_blocks_and_locks(self):
        s = _state(BALANCED)  # daily_loss_cap_pct=0.03 → -300,000 @1천만
        s.record_entry("AAA", None)
        s.record_exit("AAA", None, pnl=-300_000, equity=EQUITY)
        assert s.locked  # 손실 상한 도달 → 당일 중단
        gate = s.can_enter("BBB", None, EQUITY)
        assert not gate.allowed


class TestProfitLock:
    def test_locks_after_giveback_from_peak(self):
        s = _state(BALANCED)  # lock 4%, trail 1.5%
        # +5%까지 올림(무장) 후 고점 대비 1.5% 반납 → 잠금
        s.record_entry("A", None)
        s.record_exit("A", None, pnl=500_000, equity=EQUITY)   # +5% → armed, peak=500k
        assert s.profit_armed and not s.locked
        s.record_entry("B", None)
        s.record_exit("B", None, pnl=-160_000, equity=EQUITY)  # 340k, 고점대비 -160k(>1.5%=150k)
        assert s.locked

    def test_not_locked_if_small_giveback(self):
        s = _state(BALANCED)
        s.record_entry("A", None)
        s.record_exit("A", None, pnl=500_000, equity=EQUITY)
        s.record_entry("B", None)
        s.record_exit("B", None, pnl=-100_000, equity=EQUITY)  # 고점대비 -100k(<150k)
        assert not s.locked


class TestResetAndDefaults:
    def test_reset_daily_clears(self):
        s = _state(AGGRESSIVE)
        s.record_entry("A", "AI")
        s.record_exit("A", "AI", pnl=-600_000, equity=EQUITY)
        assert s.locked
        s.reset_daily()
        assert not s.locked and s.trade_count == 0 and s.open_themes == {}
        assert s.can_enter("A", "AI", EQUITY).allowed

    def test_default_tiers_present(self):
        tiers = make_default_tiers()
        assert set(tiers) == {"BALANCED", "AGGRESSIVE"}
        assert tiers["AGGRESSIVE"].limits.max_concurrent == 2
