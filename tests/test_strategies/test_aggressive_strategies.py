"""2-티어 공격/균형 전략을 V2 엔진(realism)으로 돌리는 통합 테스트 (합성 데이터)."""

from datetime import date, time

import numpy as np
import pandas as pd
import pytest

from src.backtest.intraday_engine import IntradayBacktestConfig
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2
from src.backtest.realism import RealismModel
from src.strategies.aggressive import (
    ConsecutiveSurgeStrategy,
    LimitUpContinuationStrategy,
    MomentumSurgeStrategy,
    VolumeSpikeBreakoutStrategy,
    get_aggressive_limitup,
    get_balanced_scalp,
)

D = date(2026, 6, 10)


def make_day(prices, volumes, base_vol=100_000, d="2026-06-10"):
    """단순 분봉: 각 봉 open=prev close, high=close*1.002, low=open*0.998."""
    idx = pd.DatetimeIndex([pd.Timestamp(f"{d} 09:{m:02d}:00") for m in range(len(prices))])
    opens, highs, lows, closes, vols = [], [], [], [], []
    prev = prices[0]
    for p, v in zip(prices, volumes):
        o = prev
        c = p
        hi = max(o, c) * 1.002
        lo = min(o, c) * 0.998
        opens.append(round(o)); highs.append(round(hi)); lows.append(round(lo)); closes.append(round(c))
        vols.append(v)
        prev = c
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}, index=idx
    )


def _cfg(**kw):
    base = dict(initial_capital=10_000_000, max_positions=1, position_size=0.3)
    base.update(kw)
    return IntradayBacktestConfig(**base)


class TestVolumeSpikeScalp:
    def _data(self):
        # 0~9봉 평탄(거래량 평균 형성), 10봉 급증+돌파 후 점진 상승(+2% 통과, 4% 천장 미만)
        prices = [10_000] * 10 + [10_300, 10_520, 10_600, 10_550, 10_500]
        vols = [100_000] * 10 + [500_000, 300_000, 200_000, 150_000, 150_000]
        return {"AAA": make_day(prices, vols)}

    def test_enters_with_theme_confirmation(self):
        strat = get_balanced_scalp(require_theme=True, vol_mult=2.0, min_bar_idx=5, time_stop_min=999, vol_avg_window=5)
        strat.set_theme_data({"AAA": {D: {"in_hot_theme": True, "is_leader": True}}})
        eng = IntradayBacktestEngineV2(_cfg(realism=RealismModel()))
        _, trades = eng.run(strat, self._data(), show_progress=False)
        assert len(trades) >= 1

    def test_no_entry_without_theme(self):
        strat = get_balanced_scalp(require_theme=True, vol_mult=2.0, min_bar_idx=5, vol_avg_window=5)
        strat.set_theme_data({})  # 테마 데이터 없음 → fail-closed
        eng = IntradayBacktestEngineV2(_cfg(realism=RealismModel()))
        _, trades = eng.run(strat, self._data(), show_progress=False)
        assert trades == []

    def test_partial_take_profit_triggers(self):
        # +2%에서 부분익절 → 거래 2건(부분 + 잔량) 가능
        strat = get_balanced_scalp(require_theme=False, vol_mult=2.0, min_bar_idx=5, time_stop_min=2, vol_avg_window=5)
        eng = IntradayBacktestEngineV2(_cfg())
        _, trades = eng.run(strat, self._data(), show_progress=False)
        assert any(t.exit_reason.startswith("TP1") for t in trades)


class TestLimitUpContinuation:
    def test_enters_on_approach_not_locked(self):
        # 상한가 13,000, 종가가 12,000 부근으로 접근 + 상승, 미잠김
        prices = [10_000, 10_800, 11_500, 12_000, 12_200, 12_100, 12_000, 11_800]
        vols = [200_000] * 8
        data = {"AAA": make_day(prices, vols)}
        strat = get_aggressive_limitup(min_edge=0.03, approach_band=0.20, min_bar_idx=1)
        strat.set_limitup_data({"AAA": {D: {"limit_price": 13_000, "first_hit_time": None}}})
        eng = IntradayBacktestEngineV2(_cfg(realism=RealismModel()))
        _, trades = eng.run(strat, data, show_progress=False)
        assert len(trades) >= 1

    def test_no_entry_when_no_limit_data(self):
        prices = [10_000, 10_800, 11_500, 12_000]
        data = {"AAA": make_day(prices, [200_000] * 4)}
        strat = get_aggressive_limitup()
        strat.set_limitup_data({})  # fail-closed
        eng = IntradayBacktestEngineV2(_cfg())
        _, trades = eng.run(strat, data, show_progress=False)
        assert trades == []

    def test_blocked_after_lock_time(self):
        # first_hit_time 09:02 → 그 이후 봉에서는 진입 불가
        prices = [10_000, 10_800, 11_500, 12_000, 12_200]
        data = {"AAA": make_day(prices, [200_000] * 5)}
        strat = get_aggressive_limitup(min_edge=0.03, approach_band=0.30, min_bar_idx=3)
        strat.set_limitup_data({"AAA": {D: {"limit_price": 13_000, "first_hit_time": time(9, 2)}}})
        eng = IntradayBacktestEngineV2(_cfg())
        _, trades = eng.run(strat, data, show_progress=False)
        assert trades == []


class TestMomentumAndConsecutive:
    def test_momentum_surge_enters_on_streak_breakout(self):
        prices = [10_000] * 6 + [10_200, 10_450, 10_700, 10_600]
        vols = [100_000] * 6 + [400_000, 400_000, 400_000, 400_000]
        data = {"AAA": make_day(prices, vols)}
        strat = MomentumSurgeStrategy(vol_mult=2.0, consecutive=2, min_bar_idx=5, require_theme=False, vol_avg_window=5)
        eng = IntradayBacktestEngineV2(_cfg(realism=RealismModel()))
        _, trades = eng.run(strat, data, show_progress=False)
        assert len(trades) >= 1

    def test_consecutive_surge_constructs_and_runs(self):
        prices = [10_000] * 6 + [10_100, 10_250, 10_400, 10_300]
        vols = [100_000] * 6 + [200_000, 200_000, 200_000, 150_000]
        data = {"AAA": make_day(prices, vols)}
        strat = ConsecutiveSurgeStrategy(consecutive=3, vol_mult=1.5, min_bar_idx=5, vol_avg_window=5)
        eng = IntradayBacktestEngineV2(_cfg())
        _, trades = eng.run(strat, data, show_progress=False)
        # 진입 여부와 무관하게 예외 없이 완주해야 함
        assert isinstance(trades, list)
