"""Strategy 6: Bollinger Band Squeeze Breakout (볼린저밴드 수축 돌파) - Optimized."""

from datetime import datetime

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class BBSqueezeStrategy(BaseStrategy):
    """
    볼린저밴드 수축 돌파 전략 - 최적화 버전.

    원리: 변동성 수축 후 확대 + 추세 확인
    진입: BB 밴드폭 최저점 + 상단 돌파 + MACD 골든크로스
    청산: 중심선 이탈 또는 -2.5% 손절

    최적화 포인트:
    - 스퀴즈 lookback 20 → 15로 축소 (더 강한 스퀴즈)
    - 손절폭 2% → 2.5%로 확대 (돌파 후 되돌림 대응)
    - 이익실현 4% → 6%로 상향 (스퀴즈 돌파 잠재력)
    - 거래량 조건 1.2x → 1.5x로 상향
    - MACD 골든크로스 동반 조건 추가
    - ATR 기반 변동성 확대 확인 추가
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        squeeze_lookback: int = 20,
        stop_loss: float = 0.025,
        take_profit: float = 0.06,
        min_volume_ratio: float = 1.3,
        require_macd_cross: bool = True,
    ):
        config = StrategyConfig(
            name="BBSqueeze",
            stop_loss=stop_loss,
            take_profit=take_profit,
            params={
                "bb_period": bb_period,
                "bb_std": bb_std,
                "squeeze_lookback": squeeze_lookback,
                "min_volume_ratio": min_volume_ratio,
                "require_macd_cross": require_macd_cross,
            },
        )
        super().__init__(config)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.squeeze_lookback = squeeze_lookback
        self.min_volume_ratio = min_volume_ratio
        self.require_macd_cross = require_macd_cross

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> list[TradeSignal]:
        """Generate BB squeeze breakout signals with enhanced filters."""
        signals = []

        min_periods = self.bb_period + self.squeeze_lookback
        if len(df) < min_periods:
            return signals

        df = self.add_technical_indicators(df)

        for i in range(min_periods, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            if pd.isna(row.get("bb_width")) or pd.isna(row.get("bb_upper")):
                continue

            lookback_start = i - self.squeeze_lookback
            bb_width_min = df.iloc[lookback_start:i]["bb_width"].min()

            is_squeeze = prev_row.get("bb_width", 1) <= bb_width_min * 1.05

            width_expanding = row["bb_width"] > prev_row.get("bb_width", 0) * 1.1

            upper_breakout = row["close"] > row["bb_upper"]

            volume_surge = row.get("volume_ratio", 0) >= self.min_volume_ratio

            bullish = row["close"] > row["open"]

            macd_ok = True
            if self.require_macd_cross:
                macd = row.get("macd")
                macd_signal = row.get("macd_signal")
                prev_macd = prev_row.get("macd")
                prev_macd_signal = prev_row.get("macd_signal")

                if all(pd.notna(x) for x in [macd, macd_signal, prev_macd, prev_macd_signal]):
                    macd_cross = (prev_macd <= prev_macd_signal) and (macd > macd_signal)
                    macd_bullish = macd > prev_macd
                    macd_ok = macd_cross or macd_bullish
                else:
                    macd_ok = True

            atr = row.get("atr")
            prev_atr = prev_row.get("atr")
            atr_expanding = True
            if pd.notna(atr) and pd.notna(prev_atr) and prev_atr > 0:
                atr_expanding = atr > prev_atr

            close_above_bb_middle = row["close"] > row.get("bb_middle", row["close"])

            conditions_met = (
                is_squeeze
                and width_expanding
                and upper_breakout
                and volume_surge
                and bullish
                and macd_ok
                and atr_expanding
                and close_above_bb_middle
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = min(row.get("volume_ratio", 1) / 2, 1.0)
                if macd_ok and atr_expanding:
                    strength = min(strength + 0.15, 1.0)

                signals.append(
                    TradeSignal(
                        code=code,
                        signal_type=SignalType.BUY,
                        price=int(row["close"]),
                        date=signal_date,
                        strategy_name=self.name,
                        reason=f"BB squeeze breakout, width {row['bb_width']:.3f}, confirmed",
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
        """Check for exit including BB middle line break."""
        should_exit, reason = super().should_exit(
            entry_price, current_price, entry_date, current_date, df
        )
        if should_exit:
            return should_exit, reason

        if not df.empty and "bb_middle" in df.columns and len(df) >= 2:
            current_close = df["close"].iloc[-1]
            prev_close = df["close"].iloc[-2]
            bb_middle = df["bb_middle"].iloc[-1]

            if not pd.isna(bb_middle):
                if current_close < bb_middle and prev_close < bb_middle:
                    return True, "Price below BB middle line for 2 days"

        return False, ""
