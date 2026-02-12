"""5가지 위험 분봉 패턴 감지 - 홍인기 매매법"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class PatternAlert:
    """패턴 감지 결과"""
    pattern_name: str      # "뉴스빵", "깊은눌림", "끼소진", "3파동", "가분수", "거래량고점"
    severity: str          # "high", "medium", "low"
    description: str
    detected_at: datetime
    confidence: float      # 0.0 ~ 1.0


class PatternDetector:
    """5가지 위험 분봉 패턴 감지"""

    # 깊은 눌림 기준: 고점 대비 50% 이상 되돌림
    DEEP_PULLBACK_RATIO = 0.5

    # 가분수 기준: 평균 거래량의 3배 이상
    TOP_HEAVY_VOL_RATIO = 3.0

    # 거래량고점: 윗꼬리 비율 50% 이상
    UPPER_SHADOW_RATIO = 0.5

    def detect_all_patterns(
        self,
        minute_bars: Optional[pd.DataFrame],
        daily_bars: Optional[pd.DataFrame] = None,
        ki_score: float = 0,
        is_leading_sector: bool = True,
        has_news_catalyst: bool = False,
    ) -> list[PatternAlert]:
        """모든 패턴 한번에 체크"""
        alerts: list[PatternAlert] = []

        # 1. 뉴스빵 체크
        result = self.detect_news_pump(is_leading_sector, has_news_catalyst)
        if result:
            alerts.append(result)

        if minute_bars is not None and not minute_bars.empty:
            # 2. 깊은 눌림
            result = self.detect_deep_pullback(minute_bars)
            if result:
                alerts.append(result)

            # 3. 끼소진
            if daily_bars is not None and not daily_bars.empty:
                current_gain = self._calc_current_gain(minute_bars)
                current_volume = self._calc_current_volume(minute_bars)
                result = self.detect_ki_exhaustion(
                    current_gain, current_volume, ki_score
                )
                if result:
                    alerts.append(result)

            # 4. 3파동
            result = self.detect_three_waves(minute_bars)
            if result:
                alerts.append(result)

            # 5. 가분수
            result = self.detect_top_heavy(minute_bars)
            if result:
                alerts.append(result)

            # 6. 거래량고점 (최대거래량 + 윗꼬리 음봉)
            result = self.detect_volume_top(minute_bars)
            if result:
                alerts.append(result)

        return alerts

    def detect_news_pump(
        self,
        is_leading_sector: bool,
        has_news_catalyst: bool,
    ) -> Optional[PatternAlert]:
        """
        뉴스빵: 비주도 섹터의 뉴스 = 위험 (5:5 확률)
        주도 섹터 + 뉴스 = OK
        비주도 섹터 + 뉴스 = 위험 신호
        """
        if not is_leading_sector and has_news_catalyst:
            return PatternAlert(
                pattern_name="뉴스빵",
                severity="high",
                description=(
                    "비주도 섹터 뉴스 상승 - 5:5 확률. "
                    "주도 섹터가 아닌 종목의 뉴스 기반 상승은 "
                    "지속력 부족할 가능성 높음"
                ),
                detected_at=datetime.now(),
                confidence=0.7,
            )
        return None

    def detect_deep_pullback(
        self, minute_bars: pd.DataFrame
    ) -> Optional[PatternAlert]:
        """
        깊은눌림: 50%+ 되돌림 = 전고점이 콘크리트벽
        장중 고점 대비 눌림 폭 계산
        """
        try:
            if len(minute_bars) < 5:
                return None

            highs = minute_bars["high"].values.astype(float)
            closes = minute_bars["close"].values.astype(float)
            opens = minute_bars["open"].values.astype(float)

            day_open = opens[0]
            day_high = np.max(highs)
            current = closes[-1]

            if day_high <= day_open:
                return None

            # 고점 대비 되돌림 비율
            rise = day_high - day_open
            pullback = day_high - current
            pullback_ratio = pullback / rise if rise > 0 else 0

            if pullback_ratio >= self.DEEP_PULLBACK_RATIO:
                return PatternAlert(
                    pattern_name="깊은눌림",
                    severity="high",
                    description=(
                        f"고점 대비 {pullback_ratio * 100:.0f}% 되돌림 "
                        f"(고점 {day_high:,.0f} → 현재 {current:,.0f}). "
                        f"전고점이 콘크리트벽 될 가능성 높음"
                    ),
                    detected_at=datetime.now(),
                    confidence=min(0.5 + pullback_ratio * 0.3, 0.9),
                )
        except Exception as e:
            logger.error(f"깊은눌림 감지 실패: {e}")

        return None

    def detect_ki_exhaustion(
        self,
        current_gain: float,
        current_volume: float,
        ki_score: float,
    ) -> Optional[PatternAlert]:
        """
        끼소진: 당일 상승폭이 과거 최대폭에 근접 + 거래량 최대 = 90% 고점
        """
        try:
            # 끼가 낮은 종목은 의미 없음
            if ki_score < 30:
                return None

            # 과거 최대 상승폭의 80% 이상 달성 + 끼 점수 60 이상
            # → 에너지 소진 가능
            if current_gain > 0 and ki_score >= 60:
                exhaustion_ratio = current_gain / (ki_score / 10)  # 끼 대비 현재 상승
                if exhaustion_ratio >= 0.8:
                    return PatternAlert(
                        pattern_name="끼소진",
                        severity="high",
                        description=(
                            f"당일 상승 +{current_gain:.1f}%로 종목 끼(최대변동성)에 근접. "
                            f"끼 점수 {ki_score:.0f}/100. "
                            f"에너지 소진 후 90% 확률로 고점"
                        ),
                        detected_at=datetime.now(),
                        confidence=min(exhaustion_ratio, 0.9),
                    )
        except Exception as e:
            logger.error(f"끼소진 감지 실패: {e}")

        return None

    def detect_three_waves(
        self, minute_bars: pd.DataFrame
    ) -> Optional[PatternAlert]:
        """
        3파동: 분봉에서 상승파 3번 감지 (피봇 고점 3개)
        3번째 파동 이후 추가 상승 확률 급감
        """
        try:
            if len(minute_bars) < 15:
                return None

            highs = minute_bars["high"].values.astype(float)
            lows = minute_bars["low"].values.astype(float)

            # 피봇 고점 찾기 (좌우 2봉 비교)
            pivot_highs: list[tuple[int, float]] = []
            for i in range(2, len(highs) - 2):
                if (highs[i] > highs[i - 1] and highs[i] > highs[i - 2]
                        and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]):
                    pivot_highs.append((i, highs[i]))

            # 상승하는 피봇 고점이 3개 이상이면 3파동
            ascending_pivots: list[tuple[int, float]] = []
            for idx, price in pivot_highs:
                if not ascending_pivots or price > ascending_pivots[-1][1]:
                    ascending_pivots.append((idx, price))

            if len(ascending_pivots) >= 3:
                # 현재가가 마지막 피봇 근처에 있는지 확인
                last_pivot_idx = ascending_pivots[-1][0]
                bars_since = len(highs) - 1 - last_pivot_idx

                if bars_since <= 10:  # 마지막 파동이 최근
                    return PatternAlert(
                        pattern_name="3파동",
                        severity="medium",
                        description=(
                            f"상승 3파동 완성 (피봇고점 {len(ascending_pivots)}개). "
                            f"3번째 파동 이후 추가 상승 확률 급감. "
                            f"파동 고점: {', '.join(f'{p:,.0f}' for _, p in ascending_pivots[-3:])}"
                        ),
                        detected_at=datetime.now(),
                        confidence=0.7,
                    )
        except Exception as e:
            logger.error(f"3파동 감지 실패: {e}")

        return None

    def detect_top_heavy(
        self, minute_bars: pd.DataFrame
    ) -> Optional[PatternAlert]:
        """
        가분수: 연속 양봉 후 압도적 거래량(평균 3배+) = 고점
        """
        try:
            if len(minute_bars) < 10:
                return None

            closes = minute_bars["close"].values.astype(float)
            opens = minute_bars["open"].values.astype(float)
            volumes = minute_bars["volume"].values.astype(float)

            # 연속 양봉 카운트 (최근부터)
            bullish_count = 0
            for i in range(len(closes) - 1, -1, -1):
                if closes[i] > opens[i]:
                    bullish_count += 1
                else:
                    break

            if bullish_count < 3:
                return None

            # 최근 봉의 거래량 vs 평균
            recent_vol = volumes[-1]
            avg_vol = np.mean(volumes[:-1]) if len(volumes) > 1 else 1

            vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 0

            if vol_ratio >= self.TOP_HEAVY_VOL_RATIO:
                return PatternAlert(
                    pattern_name="가분수",
                    severity="high",
                    description=(
                        f"연속 {bullish_count}양봉 후 거래량 {vol_ratio:.1f}배 폭발. "
                        f"가분수 패턴 - 매수세 극점 도달 가능성"
                    ),
                    detected_at=datetime.now(),
                    confidence=min(0.5 + (vol_ratio - 3) * 0.1, 0.9),
                )
        except Exception as e:
            logger.error(f"가분수 감지 실패: {e}")

        return None

    def detect_volume_top(
        self, minute_bars: pd.DataFrame
    ) -> Optional[PatternAlert]:
        """
        거래량고점: 당일 최대 거래량 봉 + 윗꼬리(상체 > 50%) + 음봉 = 매도 시그널
        """
        try:
            if len(minute_bars) < 5:
                return None

            closes = minute_bars["close"].values.astype(float)
            opens = minute_bars["open"].values.astype(float)
            highs = minute_bars["high"].values.astype(float)
            lows = minute_bars["low"].values.astype(float)
            volumes = minute_bars["volume"].values.astype(float)

            # 최대 거래량 봉 찾기
            max_vol_idx = np.argmax(volumes)

            # 최근 봉이 아니면 무시 (최근 5봉 이내)
            if max_vol_idx < len(volumes) - 5:
                return None

            idx = max_vol_idx
            body = abs(closes[idx] - opens[idx])
            candle_range = highs[idx] - lows[idx]

            if candle_range == 0:
                return None

            # 윗꼬리 계산
            real_body_top = max(opens[idx], closes[idx])
            upper_shadow = highs[idx] - real_body_top
            upper_shadow_ratio = upper_shadow / candle_range

            # 음봉 확인
            is_bearish = closes[idx] < opens[idx]

            if upper_shadow_ratio >= self.UPPER_SHADOW_RATIO and is_bearish:
                return PatternAlert(
                    pattern_name="거래량고점",
                    severity="high",
                    description=(
                        f"당일 최대거래량 봉에서 윗꼬리 음봉 발생 "
                        f"(윗꼬리 {upper_shadow_ratio * 100:.0f}%, "
                        f"거래량 {volumes[idx]:,.0f}). "
                        f"고점 매도 시그널"
                    ),
                    detected_at=datetime.now(),
                    confidence=0.8,
                )
        except Exception as e:
            logger.error(f"거래량고점 감지 실패: {e}")

        return None

    def _calc_current_gain(self, minute_bars: pd.DataFrame) -> float:
        """당일 상승률 계산"""
        if minute_bars.empty:
            return 0.0
        opens = minute_bars["open"].values.astype(float)
        closes = minute_bars["close"].values.astype(float)
        day_open = opens[0]
        current = closes[-1]
        if day_open <= 0:
            return 0.0
        return ((current - day_open) / day_open) * 100

    def _calc_current_volume(self, minute_bars: pd.DataFrame) -> float:
        """당일 누적 거래량"""
        if minute_bars.empty:
            return 0.0
        return float(minute_bars["volume"].sum())
