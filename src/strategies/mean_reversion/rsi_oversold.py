"""Strategy 4: RSI Oversold Bounce (RSI 과매도 반등) - Optimized."""

from datetime import datetime

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class RSIOversoldStrategy(BaseStrategy):
    """
    RSI 과매도 반등 전략 - 최적화 버전.

    원리: 극단적 과매도 구간에서 확인된 반등
    진입: RSI(14) < 25, 양봉 출현 + MACD 상승전환 + 거래량 증가
    청산: RSI > 45 또는 -2.5% 손절

    최적화 포인트:
    - RSI 임계값 30 → 25로 하향 (더 극단적인 과매도)
    - RSI 청산 기준 50 → 45로 하향 (조기 이익실현)
    - 손절폭 2% → 2.5%로 확대 (휩소 방지)
    - MACD 히스토그램 상승전환 확인 추가
    - 거래량 조건 0.8x → 1.0x로 상향
    - 연속 하락 후 반등 패턴 확인 강화
    """

    def __init__(
        self,
        rsi_oversold: int = 33,
        rsi_exit: int = 50,
        rsi_period: int = 14,
        stop_loss: float = 0.02,
        take_profit: float = 0.04,
        require_macd_turn: bool = True,
        min_volume_ratio: float = 1.0,
        min_down_days: int = 2,
    ):
        config = StrategyConfig(
            name="RSIOversold",
            stop_loss=stop_loss,
            take_profit=take_profit,
            max_holding_days=10,
            params={
                "rsi_oversold": rsi_oversold,
                "rsi_exit": rsi_exit,
                "rsi_period": rsi_period,
                "require_macd_turn": require_macd_turn,
                "min_volume_ratio": min_volume_ratio,
                "min_down_days": min_down_days,
            },
        )
        super().__init__(config)
        self.rsi_oversold = rsi_oversold
        self.rsi_exit = rsi_exit
        self.rsi_period = rsi_period
        self.require_macd_turn = require_macd_turn
        self.min_volume_ratio = min_volume_ratio
        self.min_down_days = min_down_days

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> list[TradeSignal]:
        """Generate RSI oversold bounce signals with enhanced filters."""
        signals = []

        if len(df) < self.rsi_period + 5:
            return signals

        df = self.add_technical_indicators(df)

        for i in range(self.rsi_period + 3, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            if pd.isna(row.get("rsi")):
                continue

            rsi_oversold = row["rsi"] < self.rsi_oversold

            rsi_bouncing = row["rsi"] > prev_row.get("rsi", 100)

            bullish = row["close"] > row["open"]

            not_new_low = row["low"] >= df.iloc[i - 3 : i]["low"].min()

            volume_ok = row.get("volume_ratio", 0) >= self.min_volume_ratio

            macd_ok = True
            if self.require_macd_turn:
                macd_hist = row.get("macd_hist")
                prev_macd_hist = prev_row.get("macd_hist")
                if pd.notna(macd_hist) and pd.notna(prev_macd_hist):
                    macd_ok = macd_hist > prev_macd_hist
                else:
                    macd_ok = True

            prior_down_days = 0
            for j in range(1, min(self.min_down_days + 2, i)):
                if df.iloc[i - j]["close"] < df.iloc[i - j]["open"]:
                    prior_down_days += 1
                else:
                    break
            downtrend_ok = prior_down_days >= self.min_down_days

            ma20 = row.get("ma20")
            not_too_far = True
            if pd.notna(ma20) and ma20 > 0:
                distance_from_ma = (row["close"] - ma20) / ma20
                not_too_far = distance_from_ma > -0.20

            conditions_met = (
                rsi_oversold
                and rsi_bouncing
                and bullish
                and not_new_low
                and volume_ok
                and macd_ok
                and downtrend_ok
                and not_too_far
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = (self.rsi_oversold - row["rsi"]) / self.rsi_oversold
                if macd_ok and volume_ok:
                    strength = min(strength + 0.1, 1.0)

                signals.append(
                    TradeSignal(
                        code=code,
                        signal_type=SignalType.BUY,
                        price=int(row["close"]),
                        date=signal_date,
                        strategy_name=self.name,
                        reason=f"RSI oversold {row['rsi']:.0f}, confirmed bounce",
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
        """Check for exit including RSI recovery."""
        should_exit, reason = super().should_exit(
            entry_price, current_price, entry_date, current_date, df
        )
        if should_exit:
            return should_exit, reason

        if not df.empty and "rsi" in df.columns:
            current_rsi = df["rsi"].iloc[-1]
            if not pd.isna(current_rsi) and current_rsi >= self.rsi_exit:
                return True, f"RSI recovered to {current_rsi:.0f}"

        return False, ""
