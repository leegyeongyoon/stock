"""compute_movers / compute_limit_events 순수 함수 단위 테스트 (pykrx 불필요)."""

from datetime import date

import pandas as pd
import pytest

from src.api.movers_fetcher import MoversConfig, compute_movers, compute_limit_events

D = date(2026, 6, 10)

# top_gainer_n/value_top_n을 작게 잡아 순위 임계를 명확히 검증한다.
CFG = MoversConfig(
    top_gainer_n=2,
    value_top_n=2,
    vol_surge_ratio=3.0,
    vol_surge_min_value=1_000_000_000,
    limit_up_threshold=29.0,
    limit_down_threshold=-29.0,
)


def _frame() -> pd.DataFrame:
    rows = {
        # 상한가 + 거래대금상위 + 급등 + 거래량급증 (flags 4개)
        "AAA": dict(market="KOSPI", open=1100, high=1300, low=1100, close=1300,
                    change_rate=30.0, volume=1_000_000, value=2_000_000_000,
                    market_cap=50_000_000_000, vol_avg_20=200_000, prev_close=1000),
        # 급등 상위 + 거래대금 1위, 거래량급증 아님
        "BBB": dict(market="KOSDAQ", open=5100, high=5600, low=5000, close=5500,
                    change_rate=10.0, volume=500_000, value=3_000_000_000,
                    market_cap=100_000_000_000, vol_avg_20=1_000_000, prev_close=5000),
        # 하한가 + 거래량급증 (등락률·거래대금 순위 밖)
        "CCC": dict(market="KOSDAQ", open=950, high=1000, low=700, close=700,
                    change_rate=-30.0, volume=800_000, value=1_500_000_000,
                    market_cap=30_000_000_000, vol_avg_20=100_000, prev_close=1000),
        # 아무 flag도 없음 → 제외돼야 함
        "DDD": dict(market="KOSPI", open=9900, high=10100, low=9900, close=10000,
                    change_rate=0.5, volume=100_000, value=500_000_000,
                    market_cap=80_000_000_000, vol_avg_20=150_000, prev_close=9950),
    }
    return pd.DataFrame.from_dict(rows, orient="index")


class TestComputeMovers:
    def test_only_flagged_stocks_included(self):
        recs = compute_movers(_frame(), D, CFG)
        codes = {r["code"] for r in recs}
        assert codes == {"AAA", "BBB", "CCC"}  # DDD 제외

    def test_flags_per_stock(self):
        by_code = {r["code"]: r for r in compute_movers(_frame(), D, CFG)}
        assert set(by_code["AAA"]["flags"]) == {"top_gainer", "value_top", "vol_surge", "limit_up"}
        assert set(by_code["BBB"]["flags"]) == {"top_gainer", "value_top"}
        assert set(by_code["CCC"]["flags"]) == {"vol_surge", "limit_down"}

    def test_limit_flags_boolean(self):
        by_code = {r["code"]: r for r in compute_movers(_frame(), D, CFG)}
        assert by_code["AAA"]["is_limit_up"] is True
        assert by_code["AAA"]["is_limit_down"] is False
        assert by_code["CCC"]["is_limit_down"] is True

    def test_volume_ratio_computed(self):
        by_code = {r["code"]: r for r in compute_movers(_frame(), D, CFG)}
        assert by_code["AAA"]["volume_ratio"] == pytest.approx(5.0)  # 1,000,000 / 200,000

    def test_vol_surge_disabled_when_vol_avg_missing(self):
        df = _frame()
        df["vol_avg_20"] = pd.NA  # 공급자 없음
        by_code = {r["code"]: r for r in compute_movers(df, D, CFG)}
        # AAA는 limit_up/top_gainer/value_top로 여전히 포착되지만 vol_surge는 빠진다
        assert "vol_surge" not in by_code["AAA"]["flags"]
        assert by_code["AAA"]["volume_ratio"] is None
        # CCC는 vol_surge가 유일한 비-limit flag였지만 limit_down으로 남는다
        assert set(by_code["CCC"]["flags"]) == {"limit_down"}

    def test_empty_frame_returns_empty(self):
        assert compute_movers(pd.DataFrame(), D, CFG) == []


class TestComputeLimitEvents:
    def test_limit_up_and_down_detected(self):
        recs = compute_limit_events(_frame(), D, CFG)
        by_code = {r["code"]: r for r in recs}
        assert set(by_code) == {"AAA", "CCC"}
        assert by_code["AAA"]["event_type"] == "limit_up"
        assert by_code["CCC"]["event_type"] == "limit_down"

    def test_limit_price_from_prev_close(self):
        by_code = {r["code"]: r for r in compute_limit_events(_frame(), D, CFG)}
        assert by_code["AAA"]["limit_price"] == 1_300  # limit_price(1000,'up')
        assert by_code["CCC"]["limit_price"] == 700    # limit_price(1000,'down')

    def test_closed_at_limit_when_close_equals_high(self):
        by_code = {r["code"]: r for r in compute_limit_events(_frame(), D, CFG)}
        assert by_code["AAA"]["closed_at_limit"] is True   # close 1300 == high 1300
        assert by_code["CCC"]["closed_at_limit"] is True   # close 700 == low 700

    def test_source_is_daily_inferred(self):
        for r in compute_limit_events(_frame(), D, CFG):
            assert r["source"] == "daily_inferred"
            assert r["first_hit_time"] is None
