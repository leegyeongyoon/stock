"""Strategy 3: VWAP Reversion (VWAP 회귀 전략) - Optimized."""

from datetime import datetime

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class VWAPReversionStrategy(BaseStrategy):
    """
    VWAP 회귀 전략 - 최적화 버전.

    원리: 극단적 VWAP 이탈 + 확인된 반등
    진입: VWAP 대비 -3% 이탈 + RSI 25 이하 + 연속 하락 후 양봉
    청산: VWAP+0.5% 도달 또는 -1.5% 손절

    최적화 포인트:
    - 이탈 기준 2% → 3%로 확대 (더 극단적인 이탈)
    - 손절폭 1% → 1.5%로 확대 (추가 이탈 대응)
    - 이익실현 2% → 2.5%로 상향 (VWAP 초과 상승)
    - RSI 25 이하 극단적 과매도 조건 추가
    - 연속 2일 이상 음봉 후 양봉 확인
    - 거래량 증가 동반 반등 확인
    """

    def __init__(
        self,
        deviation_threshold: float = 0.03,
        stop_loss: float = 0.015,
        take_profit: float = 0.025,
        max_rsi: float = 30,
        min_down_days: int = 2,
        min_volume_ratio: float = 0.8,
    ):
        config = StrategyConfig(
            name="VWAPReversion",
            stop_loss=stop_loss,
            take_profit=take_profit,
            max_holding_days=3,
            params={
                "deviation_threshold": deviation_threshold,
                "max_rsi": max_rsi,
                "min_down_days": min_down_days,
                "min_volume_ratio": min_volume_ratio,
            },
        )
        super().__init__(config)
        self.deviation_threshold = deviation_threshold
        self.max_rsi = max_rsi
        self.min_down_days = min_down_days
        self.min_volume_ratio = min_volume_ratio

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> list[TradeSignal]:
        """Generate VWAP reversion signals with enhanced filters."""
        signals = []

        if len(df) < 20:
            return signals

        df = self.add_technical_indicators(df)

        df["vwap"] = self.calculate_vwap(df)

        for i in range(20, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            if pd.isna(row["vwap"]) or row["vwap"] == 0:
                continue

            deviation = (row["close"] - row["vwap"]) / row["vwap"]

            below_vwap = deviation <= -self.deviation_threshold

            bullish = row["close"] > row["open"]

            higher_low = row["low"] > prev_row["low"]

            reversal_sign = bullish and higher_low

            rsi = row.get("rsi", 50)
            rsi_oversold = pd.isna(rsi) or rsi <= self.max_rsi

            prior_down_days = 0
            for j in range(1, min(self.min_down_days + 2, i)):
                if df.iloc[i - j]["close"] < df.iloc[i - j]["open"]:
                    prior_down_days += 1
                else:
                    break
            downtrend_before = prior_down_days >= self.min_down_days

            volume_ok = row.get("volume_ratio", 0) >= self.min_volume_ratio

            volume_increasing = True
            if i >= 3:
                today_vol = row["volume"]
                prev_vol = prev_row["volume"]
                if prev_vol > 0:
                    volume_increasing = today_vol >= prev_vol * 0.8

            stoch_k = row.get("stoch_k", 50)
            stoch_oversold = pd.isna(stoch_k) or stoch_k < 30

            not_falling_knife = True
            change_today = row.get("change", 0) or 0
            not_falling_knife = change_today > -0.05

            conditions_met = (
                below_vwap
                and reversal_sign
                and rsi_oversold
                and downtrend_before
                and volume_ok
                and volume_increasing
                and stoch_oversold
                and not_falling_knife
            )

            if conditions_met:
                signal_date = df.index[i]
                if isinstance(signal_date, pd.Timestamp):
                    signal_date = signal_date.to_pydatetime()

                strength = min(abs(deviation) / self.deviation_threshold, 2.0) / 2.0
                if rsi_oversold and stoch_oversold:
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
                        reason=f"VWAP -{abs(deviation):.1%}, RSI {rsi:.0f}, confirmed reversal",
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
        """Check for exit including VWAP reach with buffer."""
        should_exit, reason = super().should_exit(
            entry_price, current_price, entry_date, current_date, df
        )
        if should_exit:
            return should_exit, reason

        if not df.empty:
            df_with_vwap = df.copy()
            df_with_vwap["vwap"] = self.calculate_vwap(df_with_vwap)
            current_vwap = df_with_vwap["vwap"].iloc[-1]

            if pd.notna(current_vwap):
                target_price = current_vwap * 1.005
                if current_price >= target_price:
                    return True, "VWAP+0.5% reached"

        return False, ""
