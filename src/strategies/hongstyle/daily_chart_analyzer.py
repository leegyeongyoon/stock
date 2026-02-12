"""일봉 자리 분석 - 홍인기 4대 일봉 분류"""

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class DailyPosition:
    """일봉 자리 분류 결과"""
    position_type: str       # "전고점돌파", "신고가", "빈집", "바닥반등", "해당없음"
    confidence: float        # 0.0 ~ 1.0
    description: str
    resistance_levels: list[float] = field(default_factory=list)
    support_levels: list[float] = field(default_factory=list)


@dataclass
class KiScore:
    """종목 '끼' 점수"""
    score: float             # 0 ~ 100
    max_daily_gain: float    # 과거 90일 최대 일봉 상승폭 (%)
    max_volume_ratio: float  # 과거 90일 최대 거래량 / 평균 거래량
    description: str


class DailyChartAnalyzer:
    """일봉 자리 분석 (홍인기 4대 일봉)"""

    # 전고점돌파 분석 기간
    BREAKOUT_LOOKBACK_SHORT = 20
    BREAKOUT_LOOKBACK_LONG = 60

    # 신고가 기준
    HIGH_52W_DAYS = 252

    # 끼 계산 기간
    KI_LOOKBACK_DAYS = 90

    def classify_daily_position(
        self, daily_bars: pd.DataFrame
    ) -> DailyPosition:
        """
        4대 일봉 분류:
        1. 전고점돌파 - 최근 20~60일 고점 돌파 시도
        2. 신고가 - 52주 신고가 또는 역대 신고가
        3. 빈집 - 매물대가 얇은 구간
        4. 바닥반등 - 큰 하락 후 반등 시작
        """
        if daily_bars is None or daily_bars.empty or len(daily_bars) < 20:
            return DailyPosition(
                position_type="해당없음",
                confidence=0.0,
                description="일봉 데이터 부족",
            )

        try:
            closes = daily_bars["close"].values.astype(float)
            highs = daily_bars["high"].values.astype(float)
            lows = daily_bars["low"].values.astype(float)
            volumes = daily_bars["volume"].values.astype(float)
            current = closes[-1]

            # 1. 신고가 체크 (최우선)
            result = self._check_new_high(current, highs)
            if result:
                return result

            # 2. 전고점돌파 체크
            result = self._check_breakout(current, highs, closes)
            if result:
                return result

            # 3. 빈집 체크
            result = self._check_empty_zone(current, closes, volumes)
            if result:
                return result

            # 4. 바닥반등 체크
            result = self._check_bottom_bounce(current, closes, lows)
            if result:
                return result

            return DailyPosition(
                position_type="해당없음",
                confidence=0.3,
                description="특정 패턴에 해당하지 않는 구간",
            )

        except Exception as e:
            logger.error(f"일봉 분류 실패: {e}")
            return DailyPosition(
                position_type="해당없음",
                confidence=0.0,
                description=f"분석 오류: {e}",
            )

    def _check_new_high(
        self, current: float, highs: np.ndarray
    ) -> Optional[DailyPosition]:
        """52주 신고가 체크"""
        lookback = min(len(highs), self.HIGH_52W_DAYS)
        high_52w = np.max(highs[-lookback:])

        if current >= high_52w * 0.98:  # 신고가 또는 2% 이내
            is_ath = current >= np.max(highs)
            desc = "역대 신고가" if is_ath else "52주 신고가 근접/돌파"
            confidence = 0.9 if is_ath else 0.8

            return DailyPosition(
                position_type="신고가",
                confidence=confidence,
                description=f"{desc} (현재 {current:,.0f}, 52주고 {high_52w:,.0f})",
            )

        return None

    def _check_breakout(
        self, current: float, highs: np.ndarray, closes: np.ndarray
    ) -> Optional[DailyPosition]:
        """전고점돌파 체크 (20~60일 고점 돌파)"""
        if len(highs) < self.BREAKOUT_LOOKBACK_LONG:
            short_lookback = min(len(highs) - 1, self.BREAKOUT_LOOKBACK_SHORT)
        else:
            short_lookback = self.BREAKOUT_LOOKBACK_SHORT

        long_lookback = min(len(highs) - 1, self.BREAKOUT_LOOKBACK_LONG)

        # 최근 1일 제외한 과거 고점
        prev_high_short = np.max(highs[-(short_lookback + 1):-1])
        prev_high_long = np.max(highs[-(long_lookback + 1):-1])

        # 현재가가 과거 고점 근접/돌파
        if current >= prev_high_long * 0.97:
            confidence = 0.85 if current >= prev_high_long else 0.7
            resistance = prev_high_long

            return DailyPosition(
                position_type="전고점돌파",
                confidence=confidence,
                description=(
                    f"{'60' if long_lookback >= 40 else '20'}일 전고점 "
                    f"{'돌파' if current >= prev_high_long else '도전'} "
                    f"(전고점 {resistance:,.0f})"
                ),
                resistance_levels=[float(prev_high_long)],
            )

        if current >= prev_high_short * 0.97:
            return DailyPosition(
                position_type="전고점돌파",
                confidence=0.65,
                description=(
                    f"20일 전고점 도전 중 (전고점 {prev_high_short:,.0f})"
                ),
                resistance_levels=[float(prev_high_short)],
            )

        return None

    def _check_empty_zone(
        self, current: float, closes: np.ndarray, volumes: np.ndarray
    ) -> Optional[DailyPosition]:
        """
        빈집 체크 - 매물대가 얇은 구간
        가격-거래량 프로파일로 매물대 밀도 계산
        """
        if len(closes) < 60:
            return None

        lookback = min(len(closes), 120)
        price_data = closes[-lookback:]
        vol_data = volumes[-lookback:]

        # 가격 구간 나누기 (20개 구간)
        price_min = np.min(price_data)
        price_max = np.max(price_data)
        if price_max == price_min:
            return None

        n_bins = 20
        bins = np.linspace(price_min, price_max, n_bins + 1)
        bin_volumes = np.zeros(n_bins)

        for i in range(len(price_data)):
            bin_idx = np.searchsorted(bins[1:], price_data[i])
            bin_idx = min(bin_idx, n_bins - 1)
            bin_volumes[bin_idx] += vol_data[i]

        # 현재가 속한 구간 찾기
        current_bin = np.searchsorted(bins[1:], current)
        current_bin = min(current_bin, n_bins - 1)

        # 현재가 구간의 거래량이 하위 25% 이하면 빈집
        threshold = np.percentile(bin_volumes[bin_volumes > 0], 25)

        if bin_volumes[current_bin] <= threshold:
            return DailyPosition(
                position_type="빈집",
                confidence=0.7,
                description=(
                    f"매물대 희박 구간 (거래량 하위 25%) - "
                    f"빠른 상승 또는 하락 가능"
                ),
            )

        return None

    def _check_bottom_bounce(
        self, current: float, closes: np.ndarray, lows: np.ndarray
    ) -> Optional[DailyPosition]:
        """
        바닥반등 - 큰 하락 후 반등 시작 (MA20 위로 복귀)
        """
        if len(closes) < 60:
            return None

        lookback = min(len(closes), 120)
        recent_closes = closes[-lookback:]

        # 최근 120일 고점 대비 하락폭
        peak = np.max(recent_closes)
        trough = np.min(recent_closes[-60:])  # 최근 60일 저점
        drawdown = (trough - peak) / peak * 100

        # 20% 이상 하락 후
        if drawdown < -20:
            # MA20 계산
            ma20 = np.mean(closes[-20:])
            # 현재가가 MA20 위로 복귀
            if current > ma20 and trough < ma20:
                return DailyPosition(
                    position_type="바닥반등",
                    confidence=0.65,
                    description=(
                        f"고점 대비 {drawdown:.0f}% 하락 후 MA20 돌파 반등 "
                        f"(저점 {trough:,.0f} → 현재 {current:,.0f})"
                    ),
                    support_levels=[float(trough)],
                )

        return None

    def get_resistance_levels(
        self, daily_bars: pd.DataFrame
    ) -> list[float]:
        """
        매물대/전고점 분석
        - 가격-거래량 프로파일로 매물대 계산
        - 최근 고점들을 저항선으로
        """
        if daily_bars is None or daily_bars.empty:
            return []

        try:
            closes = daily_bars["close"].values.astype(float)
            highs = daily_bars["high"].values.astype(float)
            volumes = daily_bars["volume"].values.astype(float)
            current = closes[-1]

            resistances: list[float] = []

            # 1. 최근 피봇 고점들 (현재가 위에 있는 것만)
            for i in range(2, len(highs) - 2):
                if (highs[i] > highs[i - 1] and highs[i] > highs[i - 2]
                        and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]):
                    if highs[i] > current:
                        resistances.append(float(highs[i]))

            # 2. 가격-거래량 매물대 (거래량 상위 구간)
            lookback = min(len(closes), 120)
            price_data = closes[-lookback:]
            vol_data = volumes[-lookback:]

            n_bins = 20
            price_min = np.min(price_data)
            price_max = np.max(price_data)
            if price_max > price_min:
                bins = np.linspace(price_min, price_max, n_bins + 1)
                bin_volumes = np.zeros(n_bins)

                for i in range(len(price_data)):
                    bin_idx = np.searchsorted(bins[1:], price_data[i])
                    bin_idx = min(bin_idx, n_bins - 1)
                    bin_volumes[bin_idx] += vol_data[i]

                # 거래량 상위 30% 구간 = 매물대
                vol_threshold = np.percentile(bin_volumes[bin_volumes > 0], 70)
                for i in range(n_bins):
                    mid_price = (bins[i] + bins[i + 1]) / 2
                    if bin_volumes[i] >= vol_threshold and mid_price > current:
                        resistances.append(float(mid_price))

            # 중복 제거 및 정렬
            resistances = sorted(set(round(r, -1) for r in resistances))
            return resistances[:5]

        except Exception as e:
            logger.error(f"저항선 분석 실패: {e}")
            return []

    def calculate_ki(
        self,
        daily_bars: pd.DataFrame,
        minute_bars: Optional[pd.DataFrame] = None,
    ) -> KiScore:
        """
        종목 '끼' 계산
        - 과거 90일 내 최대 일봉 상승폭
        - 과거 90일 내 최대 거래량 배수
        - ki_score = (max_gain_normalized + volume_surge_ratio_normalized) / 2
        """
        if daily_bars is None or daily_bars.empty or len(daily_bars) < 10:
            return KiScore(
                score=0,
                max_daily_gain=0,
                max_volume_ratio=0,
                description="데이터 부족",
            )

        try:
            lookback = min(len(daily_bars), self.KI_LOOKBACK_DAYS)
            recent = daily_bars.tail(lookback)

            closes = recent["close"].values.astype(float)
            opens = recent["open"].values.astype(float)
            volumes = recent["volume"].values.astype(float)

            # 최대 일봉 상승폭 (%)
            daily_gains = ((closes - opens) / opens) * 100
            daily_gains = daily_gains[~np.isnan(daily_gains)]
            max_gain = float(np.max(daily_gains)) if len(daily_gains) > 0 else 0

            # 최대 거래량 배수
            avg_vol = np.mean(volumes) if len(volumes) > 0 else 1
            max_vol = np.max(volumes) if len(volumes) > 0 else 0
            max_vol_ratio = max_vol / avg_vol if avg_vol > 0 else 0

            # 점수 정규화 (0~100)
            # 상승폭: 10% 이상이면 만점(50), 0%면 0점
            gain_score = min(max_gain / 10.0 * 50, 50)
            gain_score = max(gain_score, 0)

            # 거래량: 5배 이상이면 만점(50), 1배면 0점
            vol_score = min((max_vol_ratio - 1) / 4.0 * 50, 50)
            vol_score = max(vol_score, 0)

            ki_score = gain_score + vol_score
            ki_score = round(min(ki_score, 100), 1)

            # 설명
            if ki_score >= 70:
                desc = f"끼 높음 - 과거 큰 변동성 (최대양봉 +{max_gain:.1f}%, 거래량 {max_vol_ratio:.1f}배)"
            elif ki_score >= 40:
                desc = f"끼 보통 - 적정 변동성 (최대양봉 +{max_gain:.1f}%)"
            else:
                desc = f"끼 낮음 - 변동성 부족 (최대양봉 +{max_gain:.1f}%)"

            return KiScore(
                score=ki_score,
                max_daily_gain=round(max_gain, 2),
                max_volume_ratio=round(max_vol_ratio, 2),
                description=desc,
            )

        except Exception as e:
            logger.error(f"끼 계산 실패: {e}")
            return KiScore(
                score=0,
                max_daily_gain=0,
                max_volume_ratio=0,
                description=f"계산 오류: {e}",
            )
