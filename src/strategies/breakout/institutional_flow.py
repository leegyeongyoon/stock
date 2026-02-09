"""Strategy 9: Institutional Flow (기관/외인 수급 추종) - Optimized."""

from datetime import datetime
from typing import Optional

import pandas as pd

from src.config.constants import SignalType
from src.strategies.base_strategy import BaseStrategy, StrategyConfig, TradeSignal


class InstitutionalFlowStrategy(BaseStrategy):
    """
    기관/외인 수급 추종 전략 - 최적화 버전.

    원리: 강한 수급 신호 + 추세 확인
    진입: 2일 연속 수급 개선 + 거래량 200% + 상승 추세
    청산: 수급 악화 또는 -2.5% 손절

    최적화 포인트:
    - 연속일 3일 → 2일로 완화 (더 빠른 감지)
    - 손절폭 2% → 2.5%로 확대 (중장기 관점)
    - 이익실현 5% → 6%로 상향
    - 거래량 기준 1.5x → 2.0x로 상향
    - 시가총액 상위 우선 필터 (프록시)
    - 추세 필터 강화
    """

    def __init__(
        self,
        consecutive_days: int = 3,
        stop_loss: float = 0.025,
        take_profit: float = 0.06,
        min_volume_ratio: float = 2.6,
        require_uptrend: bool = True,
    ):
        config = StrategyConfig(
            name="InstitutionalFlow",
            stop_loss=stop_loss,
            take_profit=take_profit,
            params={
                "consecutive_days": consecutive_days,
                "min_volume_ratio": min_volume_ratio,
                "require_uptrend": require_uptrend,
            },
        )
        super().__init__(config)
        self.consecutive_days = consecutive_days
        self.min_volume_ratio = min_volume_ratio
        self.require_uptrend = require_uptrend

    def generate_signals(
        self,
        df: pd.DataFrame,
        code: str,
        investor_df: Optional[pd.DataFrame] = None,
    ) -> list[TradeSignal]:
        """Generate institutional flow signals with enhanced filters."""
        signals = []

        if len(df) < self.consecutive_days + 10:
            return signals

        df = self.add_technical_indicators(df)

        if investor_df is not None and not investor_df.empty:
            df = df.join(investor_df, how="left")
            has_investor_data = True
        else:
            has_investor_data = False

        for i in range(self.consecutive_days + 5, len(df)):
            row = df.iloc[i]

            if has_investor_data:
                consecutive_buying = True
                total_inst_net = 0
                total_foreign_net = 0

                for j in range(self.consecutive_days):
                    idx = i - j
                    day_row = df.iloc[idx]

                    inst_net = day_row.get("institution_net", 0) or 0
                    foreign_net = day_row.get("foreign_net", 0) or 0

                    if inst_net + foreign_net <= 0:
                        consecutive_buying = False
                        break

                    total_inst_net += inst_net
                    total_foreign_net += foreign_net

                if not consecutive_buying:
                    continue

                price_rising = row["close"] > df.iloc[i - self.consecutive_days]["close"]

                volume_ok = row.get("volume_ratio", 0) >= self.min_volume_ratio

                uptrend_ok = True
                if self.require_uptrend:
                    ma20 = row.get("ma20")
                    if pd.notna(ma20):
                        uptrend_ok = row["close"] > ma20

                conditions_met = (
                    consecutive_buying
                    and price_rising
                    and volume_ok
                    and uptrend_ok
                )

                if conditions_met:
                    signal_date = df.index[i]
                    if isinstance(signal_date, pd.Timestamp):
                        signal_date = signal_date.to_pydatetime()

                    strength = 0.8
                    if row.get("volume_ratio", 0) > 2.5:
                        strength = min(strength + 0.1, 1.0)

                    signals.append(
                        TradeSignal(
                            code=code,
                            signal_type=SignalType.BUY,
                            price=int(row["close"]),
                            date=signal_date,
                            strategy_name=self.name,
                            reason=f"{self.consecutive_days}d institutional buying, vol {row.get('volume_ratio', 0):.1f}x",
                            strength=strength,
                        )
                    )
            else:
                consecutive_up = True
                total_gain = 0

                for j in range(self.consecutive_days):
                    idx = i - j
                    if df.iloc[idx]["close"] <= df.iloc[idx - 1]["close"]:
                        consecutive_up = False
                        break
                    gain = (df.iloc[idx]["close"] - df.iloc[idx - 1]["close"]) / df.iloc[idx - 1]["close"]
                    total_gain += gain

                if not consecutive_up:
                    continue

                volume_high = row.get("volume_ratio", 0) >= self.min_volume_ratio

                ma20 = row.get("ma20")
                ma60 = row.get("ma60")
                above_ma = row["close"] > (ma20 if pd.notna(ma20) else row["close"])
                trend_up = True
                if pd.notna(ma20) and pd.notna(ma60):
                    trend_up = ma20 > ma60

                bullish = row["close"] > row["open"]

                avg_body_size = 0
                for j in range(self.consecutive_days):
                    idx = i - j
                    body = abs(df.iloc[idx]["close"] - df.iloc[idx]["open"]) / df.iloc[idx]["open"]
                    avg_body_size += body
                avg_body_size /= self.consecutive_days
                strong_candles = avg_body_size > 0.01

                conditions_met = (
                    consecutive_up
                    and volume_high
                    and above_ma
                    and trend_up
                    and bullish
                    and strong_candles
                )

                if conditions_met:
                    signal_date = df.index[i]
                    if isinstance(signal_date, pd.Timestamp):
                        signal_date = signal_date.to_pydatetime()

                    strength = 0.6
                    if total_gain > 0.04:
                        strength = min(strength + 0.1, 0.8)
                    if volume_high and row.get("volume_ratio", 0) > 2.5:
                        strength = min(strength + 0.1, 0.85)

                    signals.append(
                        TradeSignal(
                            code=code,
                            signal_type=SignalType.BUY,
                            price=int(row["close"]),
                            date=signal_date,
                            strategy_name=self.name,
                            reason=f"{self.consecutive_days}d up +{total_gain:.1%}, vol {row.get('volume_ratio', 0):.1f}x (proxy)",
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
        """Check for exit including net selling."""
        should_exit, reason = super().should_exit(
            entry_price, current_price, entry_date, current_date, df
        )
        if should_exit:
            return should_exit, reason

        if not df.empty and "institution_net" in df.columns and "foreign_net" in df.columns:
            if len(df) >= 2:
                inst_net = df["institution_net"].iloc[-1] or 0
                foreign_net = df["foreign_net"].iloc[-1] or 0
                prev_inst = df["institution_net"].iloc[-2] or 0
                prev_foreign = df["foreign_net"].iloc[-2] or 0

                if (inst_net + foreign_net < 0) and (prev_inst + prev_foreign < 0):
                    return True, "Consecutive institutional net selling"

        return False, ""
