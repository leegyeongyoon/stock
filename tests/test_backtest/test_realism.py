"""RealismModel 단위 테스트 (순수, 오프라인)."""

import pytest

from src.backtest.realism import RealismConfig, RealismModel


@pytest.fixture
def model():
    return RealismModel(RealismConfig())


class TestSlippage:
    def test_buy_fills_higher_sell_fills_lower(self, model):
        buy = model.apply_slippage("buy", 10_000, 10_100, 9_900, 1_000_000, 100)
        sell = model.apply_slippage("sell", 10_000, 10_100, 9_900, 1_000_000, 100)
        assert buy > 10_000 > sell

    def test_wider_bar_range_increases_slippage(self, model):
        narrow = model.slippage_frac(10_000, 10_050, 9_950, 1_000_000, 100)
        wide = model.slippage_frac(10_000, 11_000, 9_000, 1_000_000, 100)
        assert wide > narrow

    def test_larger_order_impact_increases_slippage(self, model):
        small = model.slippage_frac(10_000, 10_100, 9_900, 1_000_000, 100)
        big = model.slippage_frac(10_000, 10_100, 9_900, 1_000_000, 100_000)
        assert big > small

    def test_illiquid_stock_has_more_slippage_capped(self, model):
        liquid = model.slippage_frac(10_000, 10_100, 9_900, 50_000, 10, vol_avg_20=5_000_000)
        illiquid = model.slippage_frac(10_000, 10_100, 9_900, 50_000, 10, vol_avg_20=50_000)
        assert illiquid > liquid

    def test_slippage_never_exceeds_cap(self):
        m = RealismModel(RealismConfig(max_slippage_frac=0.02))
        frac = m.slippage_frac(10_000, 20_000, 1_000, 100, 100, vol_avg_20=1)
        assert frac <= 0.02 + 1e-12

    def test_zero_price_is_safe(self, model):
        assert model.slippage_frac(0, 0, 0, 0, 0) == 0.0


class TestLiquidityCap:
    def test_caps_to_fraction_of_bar_volume(self):
        m = RealismModel(RealismConfig(liquidity_cap_frac=0.01))
        # 봉거래량 100,000 → 최대 1,000주
        assert m.cap_quantity(5_000, 100_000) == 1_000

    def test_below_cap_unchanged(self):
        m = RealismModel(RealismConfig(liquidity_cap_frac=0.01))
        assert m.cap_quantity(500, 100_000) == 500

    def test_zero_volume_blocks(self, model):
        assert model.cap_quantity(100, 0) == 0


class TestCanFill:
    def test_limit_up_locked_blocks_buy(self, model):
        r = model.can_fill("buy", 13_000, 13_000, 12_500, 1_000_000, 100, is_limit_locked=True)
        assert r.filled_qty == 0
        assert r.reason == "limit_up_blocked"

    def test_thin_volume_blocks(self):
        m = RealismModel(RealismConfig(thin_volume_shares=10_000))
        r = m.can_fill("buy", 1_000, 1_050, 990, 5_000, 100)
        assert r.filled_qty == 0
        assert r.reason == "thin"

    def test_partial_fill_when_desired_exceeds_cap(self, model):
        # 봉거래량 50,000 × 1% = 500주 → 1,000 요청 시 부분체결
        r = model.can_fill("buy", 2_000, 2_050, 1_980, 50_000, 1_000)
        assert r.filled_qty == 500
        assert r.reason == "partial"
        assert r.fill_price > 2_000  # 매수 슬리피지

    def test_full_fill_ok(self, model):
        r = model.can_fill("buy", 2_000, 2_050, 1_980, 50_000, 100)
        assert r.filled_qty == 100
        assert r.reason == "ok"

    def test_no_liquidity_when_volume_zero(self, model):
        r = model.can_fill("buy", 2_000, 2_050, 1_980, 0, 100)
        assert r.filled_qty == 0
        assert r.reason == "no_liquidity"
