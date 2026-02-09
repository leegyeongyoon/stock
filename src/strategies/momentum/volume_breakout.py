"""Strategy 1: Volume Breakout (급등주 포착) - Optimized."""

from datetime import datetime

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class VolumeBreakoutStrategy(BaseStrategy):
    """
    급등주 포착 전략 (Volume Breakout) - 최적화 버전.

    원리: 거래량 급증 + 가격 돌파 + 추세 확인
    진입: 20일 평균 거래량 250% 돌파 + 전일 고가 돌파 + 상승 추세
    청산: 5% 수익 또는 -2% 손절

    최적화 포인트:
    - 거래량 기준 3.0x → 2.5x로 완화 (과열 방지)
    - 손절폭 1.5% → 2%로 확대 (휩소 방지)
    - 이익실현 3% → 5%로 상향 (수익 극대화)
    - 추세 필터 추가 (MA5 > MA20)
    - RSI 과열 제외 필터 추가 (RSI < 70)
    - 갭 상승 제한 필터 추가 (갭 < 2%)
    """

    def __init__(
        self,
        volume_surge_ratio: float = 3.2,
        volume_ma_period: int = 20,
        stop_loss: float = 0.022,
        take_profit: float = 0.045,
        require_uptrend: bool = True,
        max_rsi: float = 70,
        max_gap: float = 0.015,
    ):
        config = StrategyConfig(
            name="VolumeBreakout",
            stop_loss=stop_loss,
            take_profit=take_profit,
            params={
                "volume_surge_ratio": volume_surge_ratio,
                "volume_ma_period": volume_ma_period,
                "require_uptrend": require_uptrend,
                "max_rsi": max_rsi,
                "max_gap": max_gap,
            },
        )
        super().__init__(config)
        self.volume_surge_ratio = volume_surge_ratio
        self.volume_ma_period = volume_ma_period
        self.require_uptrend = require_uptrend
        self.max_rsi = max_rsi
        self.max_gap = max_gap

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> list[TradeSignal]:
        """Generate volume breakout signals with enhanced filters."""
        signals = []

        if len(df) < self.volume_ma_period + 5:
            return signals

        df = self.add_technical_indicators(df)

        for i in range(self.volume_ma_period + 1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            if pd.isna(row["volume_ma20"]) or row["volume_ma20"] == 0:
                continue

            volume_ratio = row["volume"] / row["volume_ma20"]
            volume_surge = volume_ratio >= self.volume_surge_ratio

            price_breakout = row["high"] > prev_row["high"]

            bullish = row["close"] > row["open"]

            not_limit_up = row.get("change", 0) < 0.29

            uptrend_ok = True
            if self.require_uptrend:
                ma5 = row.get("ma5")
                ma20 = row.get("ma20")
                if pd.notna(ma5) and pd.notna(ma20):
                    uptrend_ok = ma5 > ma20
                else:
                    uptrend_ok = False

            rsi = row.get("rsi", 50)
            rsi_ok = pd.isna(rsi) or (30 <= rsi <= self.max_rsi)

            gap = row.get("gap", 0) or 0
            gap_ok = gap < self.max_gap

            close_above_ma = row["close"] > row.get("ma20", row["close"])

            conditions_met = (
                volume_surge
                and price_breakout
                and bullish
                and not_limit_up
                and uptrend_ok
                and rsi_ok
                and gap_ok
                and close_above_ma
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = min(volume_ratio / self.volume_surge_ratio, 2.0) / 2.0
                if uptrend_ok and close_above_ma:
                    strength = min(strength + 0.1, 1.0)

                signals.append(
                    TradeSignal(
                        code=code,
                        signal_type=SignalType.BUY,
                        price=int(row["close"]),
                        date=signal_date,
                        strategy_name=self.name,
                        reason=f"Volume surge {volume_ratio:.1f}x, breakout with uptrend",
                        strength=strength,
                    )
                )

        return signals
