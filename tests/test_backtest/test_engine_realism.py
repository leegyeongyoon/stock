"""V2 엔진의 realism 통합 테스트 (합성 데이터, 오프라인).

핵심: realism=None + execution="signal_close"이면 기존 동작과 동일(하위호환),
realism/next_open을 켜면 슬리피지·체결불가·유동성캡·다음봉체결·부분익절이 반영된다.
"""

import pandas as pd
import pytest

from src.backtest.intraday_engine import IntradayBacktestConfig
from src.backtest.intraday_engine_v2 import IntradayBacktestEngineV2
from src.backtest.realism import RealismConfig, RealismModel
from src.strategies.intraday.base import IntradayStrategy


def day(bars, d="2026-06-10") -> pd.DataFrame:
    """bars: list of (hh, mm, open, high, low, close, volume) → 하루치 분봉 DataFrame."""
    idx = pd.DatetimeIndex([pd.Timestamp(f"{d} {b[0]:02d}:{b[1]:02d}:00") for b in bars])
    return pd.DataFrame(
        {
            "open": [b[2] for b in bars],
            "high": [b[3] for b in bars],
            "low": [b[4] for b in bars],
            "close": [b[5] for b in bars],
            "volume": [b[6] for b in bars],
        },
        index=idx,
    )


class EnterBar0(IntradayStrategy):
    """bar 0에서 진입하고 SL/TP로만 청산하는 토이 전략."""

    def __init__(self, sl=0.02, tp=0.03, limit_locked=False):
        super().__init__("toy_entry")
        self.sl, self.tp, self.limit_locked = sl, tp, limit_locked

    def check_entry(self, *a):
        return None

    def check_exit(self, *a):
        return None

    def check_entry_fast(self, code, idx, ind):
        if idx != 0:
            return None
        sig = {"reason": "toy", "stop_loss": self.sl, "take_profit": self.tp, "confidence": 1.0}
        if self.limit_locked:
            sig["limit_locked"] = True
        return sig

    def check_exit_fast(self, pos, idx, ind):
        return None


class PartialExit(IntradayStrategy):
    """bar1에서 절반 익절, bar2에서 전량 청산하는 토이 전략 (SL/TP는 넓게)."""

    def __init__(self):
        super().__init__("toy_partial")

    def check_entry(self, *a):
        return None

    def check_exit(self, *a):
        return None

    def check_entry_fast(self, code, idx, ind):
        if idx == 0:
            return {"reason": "toy", "stop_loss": 0.5, "take_profit": 0.5, "confidence": 1.0}
        return None

    def check_exit_fast(self, pos, idx, ind):
        if idx == 1 and not pos.partial_done:
            return {"action": "partial", "fraction": 0.5, "reason": "TP1"}
        if idx >= 2:
            return {"action": "close", "reason": "final"}
        return None


def _cfg(**kw):
    base = dict(initial_capital=5_000_000, max_positions=1, position_size=0.3)
    base.update(kw)
    return IntradayBacktestConfig(**base)


class TestBackwardCompat:
    def test_default_path_fills_at_close_and_exact_tp(self):
        # bar0 종가 10,000 진입 → bar1 고가가 TP(10,300) 돌파 → 정확히 10,300 체결
        data = {"AAA": day([
            (9, 0, 10_000, 10_050, 9_950, 10_000, 1_000_000),
            (9, 1, 10_100, 10_400, 10_050, 10_350, 800_000),
        ])}
        eng = IntradayBacktestEngineV2(_cfg())
        _, trades = eng.run(EnterBar0(sl=0.02, tp=0.03), data, show_progress=False)
        assert len(trades) == 1
        t = trades[0]
        assert t.entry_price == 10_000.0           # 슬리피지 없음
        assert t.exit_price == pytest.approx(10_300.0)  # TP 레벨 정확 체결
        assert t.quantity == 150                   # int(1,500,000 / 10,000)


class TestSlippage:
    def test_entry_higher_and_tp_exit_lower(self):
        data = {"AAA": day([
            (9, 0, 10_000, 10_050, 9_950, 10_000, 1_000_000),
            (9, 1, 10_100, 10_400, 10_050, 10_350, 800_000),
        ])}
        eng = IntradayBacktestEngineV2(_cfg(realism=RealismModel()))
        _, trades = eng.run(EnterBar0(sl=0.02, tp=0.03), data, show_progress=False)
        assert len(trades) == 1
        t = trades[0]
        assert t.entry_price > 10_000.0   # 매수 슬리피지
        assert t.exit_price < 10_300.0    # 매도 슬리피지(레벨을 뚫고 불리하게)


class TestNextOpen:
    def test_fills_at_next_bar_open(self):
        data = {"AAA": day([
            (9, 0, 10_000, 10_050, 9_950, 10_000, 1_000_000),  # 신호
            (9, 1, 10_100, 10_150, 10_050, 10_120, 800_000),   # 여기 시가로 체결
            (9, 2, 10_120, 10_500, 10_100, 10_450, 800_000),   # TP 도달
        ])}
        eng = IntradayBacktestEngineV2(_cfg(execution="next_open"))
        _, trades = eng.run(EnterBar0(sl=0.02, tp=0.03), data, show_progress=False)
        assert len(trades) == 1
        assert trades[0].entry_price == 10_100.0  # open[1]
        assert trades[0].entry_time == pd.Timestamp("2026-06-10 09:01:00")  # 다음 봉 시각


class TestLimitUpBlock:
    def test_locked_limit_up_blocks_entry(self):
        data = {"AAA": day([
            (9, 0, 10_000, 10_050, 9_950, 10_000, 1_000_000),
            (9, 1, 10_100, 10_400, 10_050, 10_350, 800_000),
        ])}
        eng = IntradayBacktestEngineV2(_cfg(realism=RealismModel()))
        _, trades = eng.run(EnterBar0(limit_locked=True), data, show_progress=False)
        assert trades == []


class TestLiquidityCap:
    def test_partial_fill_caps_quantity(self):
        # 봉거래량 5,000 × 1% = 50주 상한 → 150 요청해도 50만 체결
        data = {"AAA": day([
            (9, 0, 10_000, 10_050, 9_950, 10_000, 5_000),
            (9, 1, 10_100, 10_400, 10_050, 10_350, 5_000),
        ])}
        eng = IntradayBacktestEngineV2(_cfg(realism=RealismModel()))
        _, trades = eng.run(EnterBar0(sl=0.02, tp=0.03), data, show_progress=False)
        assert len(trades) == 1
        assert trades[0].quantity == 50


class TestPartialExit:
    def test_partial_then_full_creates_two_trades(self):
        data = {"AAA": day([
            (9, 0, 10_000, 10_050, 9_950, 10_000, 1_000_000),
            (9, 1, 10_100, 10_200, 10_050, 10_150, 800_000),
            (9, 2, 10_150, 10_250, 10_100, 10_200, 800_000),
        ])}
        eng = IntradayBacktestEngineV2(_cfg())  # realism off, 단순 검증
        _, trades = eng.run(PartialExit(), data, show_progress=False)
        assert len(trades) == 2
        qtys = sorted(t.quantity for t in trades)
        assert qtys == [75, 75]                      # 150 → 절반/나머지
        assert trades[0].exit_reason == "TP1"
        assert trades[1].exit_reason == "final"
