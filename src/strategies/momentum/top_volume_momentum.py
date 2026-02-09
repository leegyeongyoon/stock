"""Strategy 7: Top Volume Momentum (거래대금 상위 모멘텀) - Optimized."""

from datetime import datetime

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class TopVolumeMomentumStrategy(BaseStrategy):
    """
    거래대금 상위 모멘텀 전략 - 최적화 버전.

    원리: 초기 모멘텀 포착 + 추세 추종
    진입: 2일 연속 상승 + RSI 50-70 + 거래량 증가
    청산: MA5 이탈 또는 -3% 손절

    최적화 포인트:
    - 연속 상승일 3일 → 2일로 완화 (더 이른 진입)
    - 손절폭 2% → 3%로 확대 (모멘텀 변동성 대응)
    - 이익실현 5% → 7%로 상향 (강한 모멘텀 기대)
    - RSI 50-70 범위 조건 추가 (초기 모멘텀 포착)
    - 청산 조건: 음봉 2개 → MA5 이탈로 변경
    """

    def __init__(
        self,
        consecutive_up_days: int = 1,
        stop_loss: float = 0.03,
        take_profit: float = 0.065,
        min_volume_ratio: float = 1.6,
        min_rsi: float = 40,
        max_rsi: float = 68,
    ):
        config = StrategyConfig(
            name="TopVolumeMomentum",
            stop_loss=stop_loss,
            take_profit=take_profit,
            params={
                "consecutive_up_days": consecutive_up_days,
                "min_volume_ratio": min_volume_ratio,
                "min_rsi": min_rsi,
                "max_rsi": max_rsi,
            },
        )
        super().__init__(config)
        self.consecutive_up_days = consecutive_up_days
        self.min_volume_ratio = min_volume_ratio
        self.min_rsi = min_rsi
        self.max_rsi = max_rsi

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> list[TradeSignal]:
        """Generate top volume momentum signals with enhanced filters."""
        signals = []

        if len(df) < self.consecutive_up_days + 10:
            return signals

        df = self.add_technical_indicators(df)

        for i in range(self.consecutive_up_days + 5, len(df)):
            consecutive_up = True
            total_gain = 0

            for j in range(self.consecutive_up_days):
                idx = i - j
                if df.iloc[idx]["close"] <= df.iloc[idx - 1]["close"]:
                    consecutive_up = False
                    break
                daily_gain = (df.iloc[idx]["close"] - df.iloc[idx - 1]["close"]) / df.iloc[idx - 1]["close"]
                total_gain += daily_gain

            if not consecutive_up:
                continue

            row = df.iloc[i]

            high_volume = row.get("volume_ratio", 0) >= self.min_volume_ratio

            ma10 = row.get("ma10")
            ma20 = row.get("ma20")
            trend_up = True
            if pd.notna(ma10) and pd.notna(ma20):
                trend_up = ma10 > ma20
            above_ma = row["close"] > row.get("ma20", row["close"])

            rsi = row.get("rsi", 60)
            rsi_ok = pd.isna(rsi) or (self.min_rsi <= rsi <= self.max_rsi)

            positive_momentum = row.get("change_5d", 0) > 0

            volume_increasing = True
            if i >= 3:
                avg_vol_3d = df.iloc[i - 2 : i + 1]["volume"].mean()
                avg_vol_prev_3d = df.iloc[i - 5 : i - 2]["volume"].mean()
                if avg_vol_prev_3d > 0:
                    volume_increasing = avg_vol_3d > avg_vol_prev_3d * 0.8

            conditions_met = (
                consecutive_up
                and high_volume
                and above_ma
                and trend_up
                and positive_momentum
                and rsi_ok
                and volume_increasing
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = 0.7
                if total_gain > 0.05:
                    strength = min(strength + 0.15, 1.0)
                if high_volume and row.get("volume_ratio", 0) > 2.0:
                    strength = min(strength + 0.1, 1.0)

                signals.append(
                    TradeSignal(
                        code=code,
                        signal_type=SignalType.BUY,
                        price=int(row["close"]),
                        date=signal_date,
                        strategy_name=self.name,
                        reason=f"{self.consecutive_up_days}d up +{total_gain:.1%}, RSI {rsi:.0f}",
                        strength=strength,
                    )
                )

        return signals

    def should_exit(
        self,
        entry_price: int,
        current_price: int,
        entry_date: datetime,
        current_date: datetime,
        df: pd.DataFrame,
    ) -> tuple[bool, str]:
        """Check for exit including MA5 breakdown."""
        should_exit, reason = super().should_exit(
            entry_price, current_price, entry_date, current_date, df
        )
        if should_exit:
            return should_exit, reason

        if len(df) >= 2:
            df_with_ma = self.add_technical_indicators(df.copy())
            current_close = df_with_ma["close"].iloc[-1]
            ma5 = df_with_ma.get("ma5", pd.Series()).iloc[-1] if "ma5" in df_with_ma else None

            if pd.notna(ma5) and current_close < ma5:
                prev_close = df_with_ma["close"].iloc[-2]
                prev_ma5 = df_with_ma.get("ma5", pd.Series()).iloc[-2] if "ma5" in df_with_ma else None

                if pd.notna(prev_ma5) and prev_close < prev_ma5:
                    return True, "Price below MA5 for 2 days"

        return False, ""
