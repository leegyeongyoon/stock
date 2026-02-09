"""Strategy 2: Gap Up Strategy (갭 상승 매매) - Optimized."""

from datetime import datetime

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class GapUpStrategy(BaseStrategy):
    """
    갭 상승 매매 전략 - 최적화 버전.

    원리: 강한 시초가 갭상승 후 추가 상승 + 갭필 방지
    진입: 시가 > 전일 종가 * 1.03, 현재가 시가 유지
    청산: 당일 종가 또는 -1.5% 손절

    최적화 포인트:
    - 갭 크기 2% → 3%로 상향 (강한 갭만 선별)
    - 손절폭 2% → 1.5%로 축소 (데이트레이딩 특성)
    - 이익실현 4% → 3%로 하향 (현실적 목표)
    - 갭필 방지: 현재가 시가 대비 유지 조건 추가
    - 거래량 조건 강화 (전일 대비 100% 이상)
    - 최대 갭 제한 추가 (과열 방지)
    """

    def __init__(
        self,
        min_gap: float = 0.03,
        max_gap: float = 0.10,
        stop_loss: float = 0.02,
        take_profit: float = 0.03,
        min_volume_ratio: float = 1.5,
        gap_fill_threshold: float = -0.005,
    ):
        config = StrategyConfig(
            name="GapUp",
            stop_loss=stop_loss,
            take_profit=take_profit,
            max_holding_days=2,
            params={
                "min_gap": min_gap,
                "max_gap": max_gap,
                "min_volume_ratio": min_volume_ratio,
                "gap_fill_threshold": gap_fill_threshold,
            },
        )
        super().__init__(config)
        self.min_gap = min_gap
        self.max_gap = max_gap
        self.min_volume_ratio = min_volume_ratio
        self.gap_fill_threshold = gap_fill_threshold

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> list[TradeSignal]:
        """Generate gap up signals with enhanced filters."""
        signals = []

        if len(df) < 5:
            return signals

        df = self.add_technical_indicators(df)

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            if prev_row["close"] == 0:
                continue

            gap = (row["open"] - prev_row["close"]) / prev_row["close"]
            gap_up = self.min_gap <= gap <= self.max_gap

            price_rise = row["high"] > row["open"]

            bullish_close = row["close"] >= row["open"]

            volume_ok = row.get("volume_ratio", 1) >= self.min_volume_ratio

            not_reversal = row["close"] > prev_row["close"]

            close_vs_open = (row["close"] - row["open"]) / row["open"] if row["open"] > 0 else 0
            no_gap_fill = close_vs_open >= self.gap_fill_threshold

            close_vs_prev_high = row["close"] > prev_row["high"]

            low_above_prev_close = row["low"] > prev_row["close"]

            conditions_met = (
                gap_up
                and price_rise
                and bullish_close
                and volume_ok
                and not_reversal
                and no_gap_fill
                and close_vs_prev_high
                and low_above_prev_close
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = min(gap / self.min_gap, 2.0) / 2.0
                if low_above_prev_close:
                    strength = min(strength + 0.1, 1.0)

                signals.append(
                    TradeSignal(
                        code=code,
                        signal_type=SignalType.BUY,
                        price=int(row["close"]),
                        date=signal_date,
                        strategy_name=self.name,
                        reason=f"Strong gap up {gap:.1%}, sustained momentum",
                        strength=strength,
                    )
                )

        return signals
