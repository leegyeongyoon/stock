"""Strategy 10: Sector Rotation (섹터 로테이션) - Optimized."""

from datetime import datetime
from typing import Optional

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class SectorRotationStrategy(BaseStrategy):
    """
    섹터 로테이션 전략 - 최적화 버전.

    원리: 강한 모멘텀 종목의 후발 진입 + 추세 확인
    진입: 20일 수익률 8%+ & 5일 후발 & 거래량 증가
    청산: 모멘텀 붕괴 또는 -3% 손절

    최적화 포인트:
    - 리더 게인 기준 5% → 8%로 상향 (더 강한 선도 종목)
    - 래그 기준 2% → 3%로 상향 (명확한 후발주)
    - 손절폭 2% → 3%로 확대 (로테이션 시간 허용)
    - RSI 40-60 범위 조건 (중립 구간에서 시작)
    - 거래량 증가 추세 조건 추가
    """

    def __init__(
        self,
        leader_gain_threshold: float = 0.09,
        lag_threshold: float = 0.03,
        stop_loss: float = 0.05,
        take_profit: float = 0.08,
        min_rsi: float = 30,
        max_rsi: float = 70,
        min_volume_ratio: float = 1.5,
    ):
        config = StrategyConfig(
            name="SectorRotation",
            stop_loss=stop_loss,
            take_profit=take_profit,
            params={
                "leader_gain_threshold": leader_gain_threshold,
                "lag_threshold": lag_threshold,
                "min_rsi": min_rsi,
                "max_rsi": max_rsi,
                "min_volume_ratio": min_volume_ratio,
            },
        )
        super().__init__(config)
        self.leader_gain_threshold = leader_gain_threshold
        self.lag_threshold = lag_threshold
        self.min_rsi = min_rsi
        self.max_rsi = max_rsi
        self.min_volume_ratio = min_volume_ratio

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
        sector_data: Optional[dict[str, pd.DataFrame]] = None,
    ) -> list[TradeSignal]:
        """Generate sector rotation signals with enhanced filters."""
        signals = []

        if len(df) < 30:
            return signals

        df = self.add_technical_indicators(df)

        for i in range(25, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            change_5d = row.get("change_5d", 0) or 0
            change_10d = row.get("change_5d", 0) * 2 if row.get("change_5d") else 0
            change_20d = row.get("change_20d", 0) or 0

            strong_long_term = change_20d >= self.leader_gain_threshold

            is_lagging = change_5d < change_20d * 0.25

            daily_change = row.get("change", 0) or 0
            catching_up = daily_change > 0.01 and row["close"] > row["open"]

            volume_increase = row.get("volume_ratio", 0) >= self.min_volume_ratio

            ma20 = row.get("ma20")
            above_ma = pd.isna(ma20) or row["close"] > ma20

            rsi = row.get("rsi", 50)
            rsi_ok = pd.isna(rsi) or (self.min_rsi <= rsi <= self.max_rsi)

            volume_trend_up = True
            if i >= 10:
                avg_vol_5d = df.iloc[i - 4 : i + 1]["volume"].mean()
                avg_vol_10d = df.iloc[i - 9 : i + 1]["volume"].mean()
                if avg_vol_10d > 0:
                    volume_trend_up = avg_vol_5d >= avg_vol_10d * 0.9

            macd_hist = row.get("macd_hist")
            prev_macd_hist = prev_row.get("macd_hist")
            macd_improving = True
            if pd.notna(macd_hist) and pd.notna(prev_macd_hist):
                macd_improving = macd_hist > prev_macd_hist

            not_too_extended = change_5d < 0.10

            conditions_met = (
                strong_long_term
                and is_lagging
                and catching_up
                and volume_increase
                and above_ma
                and rsi_ok
                and volume_trend_up
                and macd_improving
                and not_too_extended
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = 0.6
                if change_20d > 0.10:
                    strength = min(strength + 0.1, 0.8)
                if volume_increase and row.get("volume_ratio", 0) > 1.5:
                    strength = min(strength + 0.1, 0.9)

                signals.append(
                    TradeSignal(
                        code=code,
                        signal_type=SignalType.BUY,
                        price=int(row["close"]),
                        date=signal_date,
                        strategy_name=self.name,
                        reason=f"Rotation: 20d +{change_20d:.1%}, catching up +{daily_change:.1%}",
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
        """Check for exit including momentum breakdown."""
        should_exit, reason = super().should_exit(
            entry_price, current_price, entry_date, current_date, df
        )
        if should_exit:
            return should_exit, reason

        if len(df) >= 5:
            df_copy = self.add_technical_indicators(df.copy())
            change_5d = df_copy["change_5d"].iloc[-1]

            if change_5d is not None and change_5d < -0.04:
                return True, f"Momentum breakdown: 5d {change_5d:.1%}"

            ma10 = df_copy.get("ma10", pd.Series()).iloc[-1] if "ma10" in df_copy else None
            if pd.notna(ma10) and df_copy["close"].iloc[-1] < ma10:
                prev_close = df_copy["close"].iloc[-2]
                prev_ma10 = df_copy.get("ma10", pd.Series()).iloc[-2] if "ma10" in df_copy else None
                if pd.notna(prev_ma10) and prev_close < prev_ma10:
                    return True, "Price below MA10 for 2 days"

        return False, ""
