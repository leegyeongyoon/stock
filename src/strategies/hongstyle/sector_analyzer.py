"""주도 섹터/대장주 탐지 - 홍인기 매매법 기반"""

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional

from loguru import logger


@dataclass
class SectorInfo:
    """섹터 분석 결과"""
    sector_name: str
    trading_value: int          # 섹터 내 종목 거래대금 합계
    stock_count: int            # 상승 종목 수
    avg_change_rate: float      # 평균 등락률
    top_stocks: list[dict] = field(default_factory=list)  # 상위 종목 목록
    leader_stock: Optional[dict] = None  # 대장주


@dataclass
class LeaderChangeAlert:
    """대장주 교체 알림"""
    sector_name: str
    prev_leader: str
    new_leader: str
    reason: str
    detected_at: datetime


class SectorAnalyzer:
    """주도 섹터/대장주 탐지"""

    # 주도 섹터 확정 시간대: 9:20~9:50
    CONFIRMATION_START = time(9, 20)
    CONFIRMATION_END = time(9, 50)

    # 잡주 판별 기준: 1분봉 거래대금 20억 미만
    JUNK_STOCK_THRESHOLD = 2_000_000_000

    # 상승 기준: +4%
    SURGE_THRESHOLD = 4.0

    # 거래대금 상위 종목 수
    TOP_STOCK_COUNT = 50

    async def analyze_leading_sectors(
        self,
        theme_data: Optional[list] = None,
        stock_prices: Optional[list[dict]] = None,
    ) -> list[SectorInfo]:
        """
        주도 섹터 분석

        1. 거래대금 상위 50개 종목 조회
        2. 4% 이상 상승 종목 필터
        3. 종목의 테마/섹터별 그룹핑
        4. 각 섹터의 거래대금 합계, 상승종목 수 집계
        5. 상위 1~2개 섹터를 주도 섹터로 확정
        """
        try:
            if not stock_prices:
                logger.debug("종목 가격 데이터 없음 - 빈 결과 반환")
                return []

            # 거래대금 기준 정렬 후 상위 N개
            sorted_stocks = sorted(
                stock_prices,
                key=lambda x: x.get("trading_value", 0),
                reverse=True,
            )[:self.TOP_STOCK_COUNT]

            # 4% 이상 상승 종목 필터
            surging_stocks = [
                s for s in sorted_stocks
                if s.get("change_rate", 0) >= self.SURGE_THRESHOLD
            ]

            if not surging_stocks:
                logger.debug("4%+ 상승 종목 없음")
                return []

            # 테마/섹터별 그룹핑
            sector_map: dict[str, list[dict]] = {}
            for stock in surging_stocks:
                sector = stock.get("sector", "기타")
                # 테마 데이터가 있으면 테마 기준 그룹핑
                if theme_data:
                    themes = self._find_stock_themes(stock.get("code", ""), theme_data)
                    for theme_name in themes:
                        sector_map.setdefault(theme_name, []).append(stock)
                else:
                    sector_map.setdefault(sector, []).append(stock)

            # 섹터별 통계 계산
            sector_infos: list[SectorInfo] = []
            for sector_name, stocks in sector_map.items():
                total_value = sum(s.get("trading_value", 0) for s in stocks)
                avg_change = (
                    sum(s.get("change_rate", 0) for s in stocks) / len(stocks)
                    if stocks else 0
                )

                # 거래대금 순 정렬
                sorted_sector = sorted(
                    stocks,
                    key=lambda x: x.get("trading_value", 0),
                    reverse=True,
                )

                leader = sorted_sector[0] if sorted_sector else None

                sector_infos.append(SectorInfo(
                    sector_name=sector_name,
                    trading_value=total_value,
                    stock_count=len(stocks),
                    avg_change_rate=round(avg_change, 2),
                    top_stocks=sorted_sector[:5],
                    leader_stock=leader,
                ))

            # 거래대금 합계 기준 정렬
            sector_infos.sort(key=lambda x: x.trading_value, reverse=True)

            return sector_infos

        except Exception as e:
            logger.error(f"주도 섹터 분석 실패: {e}")
            return []

    def detect_leader_stocks(
        self, sector_stocks: list[dict]
    ) -> Optional[dict]:
        """
        섹터 내 대장주 선별
        기준: 거래대금 1위 + 상승률 상위
        """
        if not sector_stocks:
            return None

        # 거래대금 1위
        by_value = sorted(
            sector_stocks,
            key=lambda x: x.get("trading_value", 0),
            reverse=True,
        )

        # 상승률 1위
        by_change = sorted(
            sector_stocks,
            key=lambda x: x.get("change_rate", 0),
            reverse=True,
        )

        # 거래대금 1위 = 대장주 (기본 원칙)
        leader = by_value[0]

        # 상승률 1위가 거래대금도 상위 3위 안이면 대장주 교체 가능
        top_value_codes = {s.get("code") for s in by_value[:3]}
        if by_change[0].get("code") in top_value_codes:
            leader = by_change[0]

        return leader

    def detect_leader_change(
        self,
        prev_leader: Optional[dict],
        current_stocks: list[dict],
    ) -> Optional[LeaderChangeAlert]:
        """후발주가 대장주를 역전하는지 감지"""
        if not prev_leader or not current_stocks:
            return None

        current_leader = self.detect_leader_stocks(current_stocks)
        if not current_leader:
            return None

        prev_code = prev_leader.get("code", "")
        curr_code = current_leader.get("code", "")

        if prev_code and curr_code and prev_code != curr_code:
            return LeaderChangeAlert(
                sector_name=current_leader.get("sector", ""),
                prev_leader=prev_leader.get("name", prev_code),
                new_leader=current_leader.get("name", curr_code),
                reason=(
                    f"거래대금/상승률 역전 - "
                    f"{current_leader.get('name', '')} "
                    f"({current_leader.get('change_rate', 0):+.1f}%)"
                ),
                detected_at=datetime.now(),
            )

        return None

    def is_caution_day(self, sector_infos: list[SectorInfo]) -> bool:
        """
        매매 자제일 판단
        4~5개 섹터가 골고루 분산 → 주도 섹터 없음 → 자제일
        """
        if not sector_infos:
            return True

        # 유의미한 섹터 (종목 2개 이상)
        active_sectors = [s for s in sector_infos if s.stock_count >= 2]

        if len(active_sectors) >= 4:
            # 거래대금 1위와 4위의 비율 확인
            if len(active_sectors) >= 4:
                top_value = active_sectors[0].trading_value
                fourth_value = active_sectors[3].trading_value
                # 1위가 4위의 2배 미만이면 분산 → 자제일
                if top_value < fourth_value * 2 and fourth_value > 0:
                    return True

        return False

    def is_junk_stock(self, trading_value_1min: int) -> bool:
        """1분봉 거래대금 20억 미만 = 잡주"""
        return trading_value_1min < self.JUNK_STOCK_THRESHOLD

    def get_confirmation_time(self) -> tuple[time, time]:
        """주도 섹터 확정 시간 반환 (9:20~9:50)"""
        return self.CONFIRMATION_START, self.CONFIRMATION_END

    def is_confirmation_window(self) -> bool:
        """현재 시간이 주도 섹터 확정 시간대인지"""
        now = datetime.now().time()
        return self.CONFIRMATION_START <= now <= self.CONFIRMATION_END

    def _find_stock_themes(
        self, stock_code: str, theme_data: list
    ) -> list[str]:
        """종목이 속한 테마 목록 반환"""
        themes = []
        for theme in theme_data:
            # ThemeAnalysis 또는 dict 형태 지원
            if hasattr(theme, "theme"):
                theme_obj = theme.theme
                stock_codes = [s.code for s in getattr(theme_obj, "stocks", [])]
                if stock_code in stock_codes:
                    themes.append(theme_obj.name)
            elif isinstance(theme, dict):
                stock_codes = [
                    s.get("code", "") for s in theme.get("stocks", [])
                ]
                if stock_code in stock_codes:
                    themes.append(theme.get("name", "기타"))

        return themes if themes else ["기타"]
