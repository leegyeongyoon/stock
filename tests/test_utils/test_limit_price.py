"""Tests for KRX tick-size and daily price-limit (상/하한가) helpers.

KRX (2023 통합 호가단위 기준):
    < 2,000      → 1원
    2,000~5,000  → 5원
    5,000~20,000 → 10원
    20,000~50,000→ 50원
    50,000~200,000→100원
    200,000~500,000→500원
    >= 500,000   → 1,000원

상한가 = 기준가 × 1.30 → 호가단위로 내림(floor)  (±30% 밴드를 넘지 않도록)
하한가 = 기준가 × 0.70 → 호가단위로 올림(ceil)
"""

import pytest

from src.utils.krx import krx_tick_size, round_to_tick, limit_price


class TestKrxTickSize:
    @pytest.mark.parametrize(
        "price,expected",
        [
            (1, 1),
            (1_999, 1),
            (2_000, 5),
            (4_999, 5),
            (5_000, 10),
            (19_999, 10),
            (20_000, 50),
            (49_999, 50),
            (50_000, 100),
            (199_999, 100),
            (200_000, 500),
            (499_999, 500),
            (500_000, 1_000),
            (1_000_000, 1_000),
        ],
    )
    def test_tick_boundaries(self, price, expected):
        assert krx_tick_size(price) == expected


class TestRoundToTick:
    def test_floor_uses_tick_of_target_band(self):
        # 7,995 sits in 5,000~20,000 band (tick 10) → floor 7,990
        assert round_to_tick(7_995, mode="floor") == 7_990

    def test_ceil_uses_tick_of_target_band(self):
        # 4,301 sits in 2,000~5,000 band (tick 5) → ceil 4,305
        assert round_to_tick(4_301, mode="ceil") == 4_305

    def test_exact_multiple_unchanged(self):
        assert round_to_tick(13_000, mode="floor") == 13_000
        assert round_to_tick(13_000, mode="ceil") == 13_000


class TestLimitPrice:
    @pytest.mark.parametrize(
        "prev_close,upper,lower",
        [
            (10_000, 13_000, 7_000),   # tick 10, exact ±30%
            (1_000, 1_300, 700),       # tick 1
            (3_000, 3_900, 2_100),     # tick 5
            (15_000, 19_500, 10_500),  # tick 10
        ],
    )
    def test_round_numbers(self, prev_close, upper, lower):
        assert limit_price(prev_close, "up") == upper
        assert limit_price(prev_close, "down") == lower

    def test_non_divisible_floors_upper_within_band(self):
        # 6,150 → upper raw 7,995 → floor to tick 10 = 7,990 (<= +30%)
        up = limit_price(6_150, "up")
        assert up == 7_990
        assert (up - 6_150) / 6_150 <= 0.30

    def test_lower_never_below_minus_30pct(self):
        # rounding up keeps 하한가 within the -30% band
        for prev in (1_333, 6_150, 27_350, 123_400):
            low = limit_price(prev, "down")
            assert (low - prev) / prev >= -0.30 - 1e-9

    def test_upper_never_above_plus_30pct(self):
        for prev in (1_333, 6_150, 27_350, 123_400):
            up = limit_price(prev, "up")
            assert (up - prev) / prev <= 0.30 + 1e-9

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            limit_price(10_000, "sideways")

    def test_non_positive_prev_close_raises(self):
        with pytest.raises(ValueError):
            limit_price(0, "up")
