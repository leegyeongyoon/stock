"""Strategy 8: 52-Week High Breakout (52주 신고가 돌파) - Optimized."""

from datetime import datetime

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class High52WeekBreakoutStrategy(BaseStrategy):
    """
    52주 신고가 돌파 전략 - 최적화 버전.

    원리: 강한 거래량 동반 신고가 돌파 + 추세 확인
    진입: 52주 신고가 + 1% 이상 돌파 + 거래량 200% + 상승 추세
    청산: 8% 수익 또는 -3% 손절

    최적화 포인트:
    - 거래량 기준 1.5x → 2.0x로 상향 (강한 돌파만)
    - 손절폭 2% → 3%로 확대 (돌파 후 재테스트 허용)
    - 이익실현 5% → 8%로 상향 (신고가 돌파 잠재력)
    - 종가가 고점 대비 1% 이상 위 조건 추가
    - 거래량 증가 추세 확인 추가
    - 상승 추세 필터 추가
    """

    def __init__(
        self,
        volume_threshold: float = 2.5,
        lookback_days: int = 252,
        stop_loss: float = 0.025,
        take_profit: float = 0.08,
        min_breakout_pct: float = 0.02,
        require_uptrend: bool = True,
    ):
        config = StrategyConfig(
            name="High52WeekBreakout",
            stop_loss=stop_loss,
            take_profit=take_profit,
            params={
                "volume_threshold": volume_threshold,
                "lookback_days": lookback_days,
                "min_breakout_pct": min_breakout_pct,
                "require_uptrend": require_uptrend,
            },
        )
        super().__init__(config)
        self.volume_threshold = volume_threshold
        self.lookback_days = lookback_days
        self.min_breakout_pct = min_breakout_pct
        self.require_uptrend = require_uptrend

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> list[TradeSignal]:
        """Generate 52-week high breakout signals with enhanced filters."""
        signals = []

        if len(df) < self.lookback_days:
            return signals

        df = self.add_technical_indicators(df)

        for i in range(self.lookback_days, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            lookback_start = max(0, i - self.lookback_days)
            high_52w = df.iloc[lookback_start:i]["high"].max()

            new_high = row["high"] > high_52w

            volume_surge = row.get("volume_ratio", 0) >= self.volume_threshold

            bullish = row["close"] > row["open"]

            breakout_pct = (row["close"] - high_52w) / high_52w if high_52w > 0 else 0
            clear_breakout = breakout_pct >= self.min_breakout_pct

            uptrend_ok = True
            if self.require_uptrend:
                ma20 = row.get("ma20")
                ma60 = row.get("ma60")
                if pd.notna(ma20) and pd.notna(ma60):
                    uptrend_ok = ma20 > ma60 and row["close"] > ma20
                elif pd.notna(ma20):
                    uptrend_ok = row["close"] > ma20

            volume_increasing = True
            if i >= 5:
                avg_vol_5d = df.iloc[i - 4 : i + 1]["volume"].mean()
                avg_vol_20d = df.iloc[max(0, i - 19) : i + 1]["volume"].mean()
                if avg_vol_20d > 0:
                    volume_increasing = avg_vol_5d >= avg_vol_20d * 1.2

            not_overheated = True
            rsi = row.get("rsi")
            if pd.notna(rsi):
                not_overheated = rsi < 80

            low_above_prev_close = row["low"] > prev_row["close"]

            conditions_met = (
                new_high
                and volume_surge
                and bullish
                and clear_breakout
                and uptrend_ok
                and volume_increasing
                and not_overheated
                and low_above_prev_close
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = min(row.get("volume_ratio", 1) / 2, 1.0)
                if breakout_pct > 0.02:
                    strength = min(strength + 0.15, 1.0)
                if volume_increasing:
                    strength = min(strength + 0.1, 1.0)

                signals.append(
                    TradeSignal(
                        code=code,
                        signal_type=SignalType.BUY,
                        price=int(row["close"]),
                        date=signal_date,
                        strategy_name=self.name,
                        reason=f"52w high +{breakout_pct:.1%}, vol {row.get('volume_ratio', 0):.1f}x, uptrend",
                        strength=strength,
                    )
                )

        return signals
