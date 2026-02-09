"""Strategy 5: MA Golden Cross (이동평균 골든크로스) - Optimized."""

from datetime import datetime

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class MAGoldenCrossStrategy(BaseStrategy):
    """
    이동평균 골든크로스 전략 - 최적화 버전.

    원리: 안정적인 추세 전환 + 모멘텀 확인
    진입: MA(10) > MA(30) 교차 + 거래량 150% + MACD 양전환
    청산: MA(10) < MA(30) 교차 또는 -4% 손절

    최적화 포인트:
    - 단기 MA 5 → 10으로 확대 (더 안정적인 크로스)
    - 장기 MA 20 → 30으로 확대 (휩소 감소)
    - 거래량 기준 1.2x → 1.5x로 상향
    - 손절폭 3% → 4%로 확대 (추세 전략 특성)
    - MACD 양전환 동반 조건 추가
    - 크로스 후 2일 연속 종가 유지 확인
    """

    def __init__(
        self,
        short_period: int = 10,
        long_period: int = 30,
        volume_threshold: float = 1.5,
        stop_loss: float = 0.045,
        take_profit: float = 0.08,
        require_macd: bool = True,
        confirm_days: int = 1,
    ):
        config = StrategyConfig(
            name="MAGoldenCross",
            stop_loss=stop_loss,
            take_profit=take_profit,
            params={
                "short_period": short_period,
                "long_period": long_period,
                "volume_threshold": volume_threshold,
                "require_macd": require_macd,
                "confirm_days": confirm_days,
            },
        )
        super().__init__(config)
        self.short_period = short_period
        self.long_period = long_period
        self.volume_threshold = volume_threshold
        self.require_macd = require_macd
        self.confirm_days = confirm_days

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> list[TradeSignal]:
        """Generate golden cross signals with enhanced filters."""
        signals = []

        if len(df) < self.long_period + 10:
            return signals

        df = self.add_technical_indicators(df)

        ma_short_col = f"ma{self.short_period}"
        ma_long_col = f"ma{self.long_period}"

        if ma_short_col not in df.columns:
            df[ma_short_col] = df["close"].rolling(window=self.short_period).mean()
        if ma_long_col not in df.columns:
            df[ma_long_col] = df["close"].rolling(window=self.long_period).mean()

        for i in range(self.long_period + self.confirm_days + 1, len(df)):
            row = df.iloc[i]

            cross_idx = i - self.confirm_days
            cross_row = df.iloc[cross_idx]
            prev_cross_row = df.iloc[cross_idx - 1]

            ma_short = cross_row.get(ma_short_col)
            ma_long = cross_row.get(ma_long_col)
            prev_ma_short = prev_cross_row.get(ma_short_col)
            prev_ma_long = prev_cross_row.get(ma_long_col)

            if any(pd.isna(x) for x in [ma_short, ma_long, prev_ma_short, prev_ma_long]):
                continue

            golden_cross = (prev_ma_short <= prev_ma_long) and (ma_short > ma_long)

            if not golden_cross:
                continue

            confirmed = True
            for j in range(self.confirm_days):
                check_idx = cross_idx + j + 1
                if check_idx <= i:
                    check_row = df.iloc[check_idx]
                    check_ma_short = check_row.get(ma_short_col)
                    check_ma_long = check_row.get(ma_long_col)
                    if pd.notna(check_ma_short) and pd.notna(check_ma_long):
                        if check_ma_short <= check_ma_long:
                            confirmed = False
                            break

            if not confirmed:
                continue

            volume_surge = row.get("volume_ratio", 0) >= self.volume_threshold

            current_ma_short = row.get(ma_short_col)
            price_above = pd.isna(current_ma_short) or row["close"] > current_ma_short

            bullish = row["close"] > row["open"]

            macd_ok = True
            if self.require_macd:
                macd = row.get("macd")
                macd_signal = row.get("macd_signal")
                if pd.notna(macd) and pd.notna(macd_signal):
                    macd_ok = macd > macd_signal or macd > 0
                else:
                    macd_ok = True

            ma_slope_positive = True
            if pd.notna(current_ma_short):
                prev_ma_short_current = df.iloc[i - 1].get(ma_short_col)
                if pd.notna(prev_ma_short_current):
                    ma_slope_positive = current_ma_short > prev_ma_short_current

            conditions_met = (
                golden_cross
                and confirmed
                and volume_surge
                and price_above
                and bullish
                and macd_ok
                and ma_slope_positive
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = min(row.get("volume_ratio", 1) / 2, 1.0)
                if macd_ok and ma_slope_positive:
                    strength = min(strength + 0.15, 1.0)

                signals.append(
                    TradeSignal(
                        code=code,
                        signal_type=SignalType.BUY,
                        price=int(row["close"]),
                        date=signal_date,
                        strategy_name=self.name,
                        reason=f"Golden cross MA{self.short_period}/MA{self.long_period} confirmed, vol {row.get('volume_ratio', 0):.1f}x",
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
        """Check for exit including death cross."""
        should_exit, reason = super().should_exit(
            entry_price, current_price, entry_date, current_date, df
        )
        if should_exit:
            return should_exit, reason

        if len(df) >= 3:
            df_copy = df.copy()

            ma_short_col = f"ma{self.short_period}"
            ma_long_col = f"ma{self.long_period}"

            if ma_short_col not in df_copy.columns:
                df_copy[ma_short_col] = df_copy["close"].rolling(window=self.short_period).mean()
            if ma_long_col not in df_copy.columns:
                df_copy[ma_long_col] = df_copy["close"].rolling(window=self.long_period).mean()

            ma_short = df_copy[ma_short_col].iloc[-1]
            ma_long = df_copy[ma_long_col].iloc[-1]
            prev_ma_short = df_copy[ma_short_col].iloc[-2]
            prev_ma_long = df_copy[ma_long_col].iloc[-2]

            if not any(pd.isna(x) for x in [ma_short, ma_long, prev_ma_short, prev_ma_long]):
                death_cross = (prev_ma_short >= prev_ma_long) and (ma_short < ma_long)
                if death_cross:
                    return True, "Death cross detected"

                if ma_short < ma_long:
                    prev2_ma_short = df_copy[ma_short_col].iloc[-3] if len(df_copy) >= 3 else None
                    prev2_ma_long = df_copy[ma_long_col].iloc[-3] if len(df_copy) >= 3 else None
                    if pd.notna(prev2_ma_short) and pd.notna(prev2_ma_long):
                        if prev2_ma_short < prev2_ma_long:
                            return True, "MA cross breakdown confirmed"

        return False, ""
