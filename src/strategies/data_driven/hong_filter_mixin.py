"""홍인기 필터 믹스인 - 6개 데이터드리븐 전략 공용.

홍인기 전략의 핵심 요소:
  1. 시총 필터 (대형주)
  2. 기관 순매수 필터
  3. 끼점수 필터
  4. 일봉자리 필터 (신고가/전고점돌파/빈집)
  5. 전일 거래대금 필터
  6. 당일 누적 거래대금 필터

사용법:
  class MyStrategy(HongFilterMixin, IntradayStrategy):
      HONG_MIN_CAP_BIL = 5000
      ...
"""


class HongFilterMixin:
    """홍인기 요소 필터 믹스인. 각 전략에서 파라미터를 오버라이드 가능."""

    # === 설정 가능한 파라미터 (GPT가 최적화) ===
    HONG_ENABLED: bool = True
    HONG_MIN_CAP_BIL: float = 5000          # 시총 5000억+
    HONG_MIN_INST_BIL: float = 50           # 기관 순매수 50억+
    HONG_MAX_INST_BIL: float = 200          # 기관 순매수 200억 이하
    HONG_MIN_KI_SCORE: float = 20           # 끼 20+
    HONG_PREFERRED_POSITIONS: set = {"신고가", "전고점돌파", "빈집"}
    HONG_MIN_DAILY_VALUE: int = 5_000_000_000    # 전일 거래대금 50억+
    MIN_INTRADAY_CUM_VALUE: int = 1_000_000_000  # 당일 누적 거래대금 10억+

    def passes_hong_filter(self) -> tuple[bool, str]:
        """일별 컨텍스트 기반 홍인기 필터.

        Returns:
            (True, "pass") if passes, (False, reason_str) if filtered out.
            (True, "no_context") if context unavailable (skip filter).
        """
        if not self.HONG_ENABLED:
            return True, "disabled"

        ctx = self.get_daily_context()
        if ctx is None:
            return True, "no_context"

        # 1. 시총
        if ctx.market_cap_bil < self.HONG_MIN_CAP_BIL:
            return False, f"cap={ctx.market_cap_bil:.0f}"

        # 2. 기관 순매수 범위 (데이터 없으면 스킵)
        if ctx.inst_net_buy_bil is not None:
            if not (self.HONG_MIN_INST_BIL <= ctx.inst_net_buy_bil <= self.HONG_MAX_INST_BIL):
                return False, f"inst={ctx.inst_net_buy_bil:.0f}"

        # 3. 끼점수
        if ctx.ki_score < self.HONG_MIN_KI_SCORE:
            return False, f"ki={ctx.ki_score:.0f}"

        # 4. 일봉자리
        if ctx.daily_position_type not in self.HONG_PREFERRED_POSITIONS:
            return False, f"pos={ctx.daily_position_type}"

        # 5. 전일 거래대금
        if ctx.daily_trading_value < self.HONG_MIN_DAILY_VALUE:
            return False, f"value={ctx.daily_trading_value}"

        return True, "pass"

    def passes_intraday_value_filter(self, bar_idx: int, indicators: dict) -> bool:
        """당일 누적 거래대금 필터."""
        if not self.HONG_ENABLED:
            return True

        cum_value = indicators.get("cum_trading_value")
        if cum_value is None:
            return True

        return cum_value[bar_idx] >= self.MIN_INTRADAY_CUM_VALUE

    def hong_confidence_boost(self) -> float:
        """끼점수 + 일봉자리 기반 확신도 부스트.

        Returns:
            1.0 (기본) ~ 1.5 (최고)
        """
        ctx = self.get_daily_context()
        if ctx is None:
            return 1.0

        boost = 1.0

        # 끼점수 부스트
        if ctx.ki_score >= 70:
            boost += 0.2
        elif ctx.ki_score >= 50:
            boost += 0.1

        # 일봉자리 부스트
        if ctx.daily_position_type == "신고가":
            boost += 0.2
        elif ctx.daily_position_type == "전고점돌파":
            boost += 0.15
        elif ctx.daily_position_type == "빈집":
            boost += 0.1

        return min(boost, 1.5)
