"""테마 분석 서비스 - 홍인기 스타일 분석 + 뉴스 기반 수급 예측"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from typing import Optional
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
from pykrx import stock as pykrx_stock

from src.analysis.theme_crawler import NaverThemeCrawler, Theme, ThemeStock
from src.analysis.news_crawler import NewsCrawler, ThemeNews, THEME_KEYWORDS


class MarketPhase(Enum):
    """시장 상태"""
    PRE_MARKET = "pre_market"      # 장전 (~ 08:59)
    OPENING = "opening"             # 동시호가/장초반 (09:00 ~ 09:30)
    MORNING = "morning"             # 오전장 (09:30 ~ 11:30)
    LUNCH = "lunch"                 # 점심시간 (11:30 ~ 13:00)
    AFTERNOON = "afternoon"         # 오후장 (13:00 ~ 15:20)
    CLOSING = "closing"             # 장마감 동시호가 (15:20 ~ 15:30)
    AFTER_MARKET = "after_market"   # 장후 (15:30 ~)


@dataclass
class StockScore:
    """종목 점수"""
    code: str
    name: str
    theme_name: str
    total_score: float  # 총점 (100점 만점)

    # 세부 점수
    momentum_score: float      # 모멘텀 (등락률) 점수
    volume_score: float        # 거래량 점수
    foreign_score: float       # 외인 수급 점수
    inst_score: float          # 기관 수급 점수
    leader_score: float        # 대장주 점수

    # 원본 데이터
    change_rate: float
    volume: int
    foreign_change: int
    inst_change: int
    is_leader: bool

    recommendation: str = ""   # 추천 코멘트


@dataclass
class ThemeAnalysis:
    """테마 분석 결과"""
    theme: Theme
    score: float  # 테마 점수
    momentum: str  # 상승/하락/횡보

    # 홍인기 스타일 분석
    is_hot: bool  # 핫 테마 여부
    volume_surge: bool  # 거래량 급증 여부
    foreign_buying: bool  # 외인 순매수
    inst_buying: bool  # 기관 순매수

    top_stocks: list[StockScore] = field(default_factory=list)
    analysis_comment: str = ""


@dataclass
class ThemeNewsSummary:
    """테마 뉴스 요약"""
    theme_name: str
    news_count: int
    hot_score: float
    sentiment: str
    key_issues: list[str]
    supply_prediction: str  # 수급 예측 (매수세 예상/매도세 예상/중립)
    prediction_confidence: float  # 예측 신뢰도 (0~100)


@dataclass
class SupplyFlowAnalysis:
    """수급 흐름 분석"""
    theme_name: str
    current_supply: str  # 매수세/매도세/중립
    foreign_flow: str    # 외인 동향
    inst_flow: str       # 기관 동향
    volume_change: float  # 거래량 변화율 (%)
    is_surging: bool     # 급등 중인지
    alert_message: str   # 알림 메시지


@dataclass
class MarketAnalysis:
    """전체 시장 분석"""
    timestamp: datetime
    phase: MarketPhase

    # 상위 테마
    hot_themes: list[ThemeAnalysis]

    # 추천 종목
    recommended_stocks: list[StockScore]

    # 시장 요약
    market_sentiment: str  # 강세/약세/혼조
    top_sectors: list[str]  # 상위 섹터
    caution_message: str = ""  # 주의사항

    # 뉴스 기반 분석
    theme_news: list[ThemeNewsSummary] = field(default_factory=list)
    predicted_hot_themes: list[str] = field(default_factory=list)  # 뉴스 기반 예상 핫 테마


@dataclass
class ThemeRanking:
    """테마 종합 순위"""
    rank: int
    theme_name: str
    theme_code: str

    # 종합 점수 (100점 만점)
    total_score: float

    # 세부 점수
    momentum_score: float       # 가격 모멘텀 점수 (30점)
    news_score: float           # 뉴스 핫스코어 (25점)
    sentiment_score: float      # 뉴스 감성 점수 (20점)
    supply_score: float         # 수급 점수 (25점)

    # 원본 데이터
    change_rate: float          # 테마 등락률
    news_count: int             # 뉴스 건수
    news_hot_score: float       # 뉴스 핫스코어
    sentiment: str              # 감성 (positive/negative/neutral)
    supply_prediction: str      # 수급 예측
    confidence: float           # 예측 신뢰도

    # 분석
    key_issues: list[str] = field(default_factory=list)  # 주요 이슈
    recommendation: str = ""    # 투자 의견
    grade: str = ""             # 등급 (A/B/C/D/F)


@dataclass
class PeriodHotTheme:
    """기간별 핫 테마"""
    rank: int
    theme_code: str
    theme_name: str
    period_days: int            # 기간 (1, 3, 7, 30)

    # 수익률
    change_rate: float          # 기간 수익률
    avg_change_rate: float      # 종목 평균 수익률

    # 종목 정보
    stock_count: int            # 테마 종목 수
    up_count: int               # 상승 종목 수
    down_count: int             # 하락 종목 수
    up_ratio: float             # 상승 비율 (%)

    # 대표 종목
    top_gainers: list[dict] = field(default_factory=list)  # 상승 상위 종목
    leader_stock: str = ""      # 대장주

    # 분석
    momentum: str = ""          # 상승/하락/횡보
    strength: str = ""          # 강세/약세/보합


class ThemeAnalyzer:
    """테마 분석 서비스"""

    def __init__(self):
        self.crawler = NaverThemeCrawler()
        self.news_crawler = NewsCrawler()
        self._cache: Optional[MarketAnalysis] = None
        self._cache_time: Optional[datetime] = None
        self._cache_duration = timedelta(minutes=5)  # 5분 캐시
        self._news_cache: dict[str, ThemeNews] = {}
        self._news_cache_time: Optional[datetime] = None
        self._news_cache_duration = timedelta(minutes=10)  # 뉴스 10분 캐시

        # ranking 캐시
        self._ranking_cache: Optional[list[ThemeRanking]] = None
        self._ranking_cache_time: Optional[datetime] = None
        self._ranking_cache_duration = timedelta(minutes=5)

        # period hot themes 캐시
        self._period_cache: dict[int, list[PeriodHotTheme]] = {}
        self._period_cache_time: dict[int, datetime] = {}
        self._period_cache_duration = timedelta(minutes=5)

    async def close(self):
        await self.crawler.close()
        await self.news_crawler.close()

    def get_market_phase(self) -> MarketPhase:
        """현재 시장 상태 반환"""
        now = datetime.now().time()

        if now < time(9, 0):
            return MarketPhase.PRE_MARKET
        elif now < time(9, 30):
            return MarketPhase.OPENING
        elif now < time(11, 30):
            return MarketPhase.MORNING
        elif now < time(13, 0):
            return MarketPhase.LUNCH
        elif now < time(15, 20):
            return MarketPhase.AFTERNOON
        elif now < time(15, 30):
            return MarketPhase.CLOSING
        else:
            return MarketPhase.AFTER_MARKET

    def calculate_stock_score(
        self,
        stock: ThemeStock,
        theme: Theme,
        is_leader: bool = False
    ) -> StockScore:
        """종목 점수 계산 (홍인기 기준)"""

        # 1. 모멘텀 점수 (30점) - 등락률
        momentum = min(max(stock.change_rate * 3, -30), 30)

        # 2. 거래량 점수 (20점) - 상대적 거래량
        vol_score = 0
        if stock.volume > 1000000:
            vol_score = 20
        elif stock.volume > 500000:
            vol_score = 15
        elif stock.volume > 100000:
            vol_score = 10
        elif stock.volume > 50000:
            vol_score = 5

        # 3. 외인 수급 점수 (20점)
        foreign_score = 0
        if stock.foreign_change > 100000:
            foreign_score = 20
        elif stock.foreign_change > 50000:
            foreign_score = 15
        elif stock.foreign_change > 10000:
            foreign_score = 10
        elif stock.foreign_change > 0:
            foreign_score = 5
        elif stock.foreign_change < -50000:
            foreign_score = -10

        # 4. 기관 수급 점수 (15점)
        inst_score = 0
        if stock.inst_change > 100000:
            inst_score = 15
        elif stock.inst_change > 50000:
            inst_score = 12
        elif stock.inst_change > 10000:
            inst_score = 8
        elif stock.inst_change > 0:
            inst_score = 4
        elif stock.inst_change < -50000:
            inst_score = -8

        # 5. 대장주 점수 (15점)
        leader_score = 15 if is_leader else 0

        total = momentum + vol_score + foreign_score + inst_score + leader_score
        total = max(0, min(100, total))  # 0~100 범위

        # 추천 코멘트 생성
        recommendation = self._generate_recommendation(
            stock, total, is_leader,
            stock.foreign_change > 0, stock.inst_change > 0
        )

        return StockScore(
            code=stock.code,
            name=stock.name,
            theme_name=theme.name,
            total_score=total,
            momentum_score=momentum,
            volume_score=vol_score,
            foreign_score=foreign_score,
            inst_score=inst_score,
            leader_score=leader_score,
            change_rate=stock.change_rate,
            volume=stock.volume,
            foreign_change=stock.foreign_change,
            inst_change=stock.inst_change,
            is_leader=is_leader,
            recommendation=recommendation
        )

    def _generate_recommendation(
        self,
        stock: ThemeStock,
        score: float,
        is_leader: bool,
        foreign_buying: bool,
        inst_buying: bool
    ) -> str:
        """추천 코멘트 생성"""
        comments = []

        if is_leader:
            comments.append("🏆 테마 대장주")

        if score >= 70:
            comments.append("⭐ 강력 관심")
        elif score >= 50:
            comments.append("👀 관심 종목")

        if foreign_buying and inst_buying:
            comments.append("💰 외인+기관 동반 순매수")
        elif foreign_buying:
            comments.append("🌍 외인 순매수")
        elif inst_buying:
            comments.append("🏛 기관 순매수")

        if stock.change_rate > 10:
            comments.append("🚀 급등 중 (추격매수 주의)")
        elif stock.change_rate > 5:
            comments.append("📈 강세")

        if stock.volume > 1000000:
            comments.append("🔥 거래 폭발")

        return " | ".join(comments) if comments else "⏳ 관망"

    def analyze_theme(self, theme: Theme) -> ThemeAnalysis:
        """테마 분석"""

        # 테마 점수 계산
        score = 0
        if theme.change_rate > 3:
            score += 30
        elif theme.change_rate > 1:
            score += 20
        elif theme.change_rate > 0:
            score += 10

        if theme.up_count > theme.down_count:
            score += 20

        total_foreign = sum(s.foreign_change for s in theme.stocks)
        total_inst = sum(s.inst_change for s in theme.stocks)

        if total_foreign > 0:
            score += 25
        if total_inst > 0:
            score += 25

        # 모멘텀 판단
        if theme.change_rate > 2:
            momentum = "강세"
        elif theme.change_rate > 0:
            momentum = "상승"
        elif theme.change_rate > -2:
            momentum = "혼조"
        else:
            momentum = "약세"

        # 종목별 점수 계산
        stock_scores = []
        for stock in theme.stocks:
            is_leader = theme.leader_stock == stock.name
            stock_score = self.calculate_stock_score(stock, theme, is_leader)
            stock_scores.append(stock_score)

        # 점수순 정렬
        stock_scores.sort(key=lambda x: x.total_score, reverse=True)

        # 분석 코멘트
        comment_parts = []
        if theme.change_rate > 3:
            comment_parts.append(f"🔥 오늘의 핫 테마! (+{theme.change_rate:.1f}%)")
        if total_foreign > 100000:
            comment_parts.append("외인 대규모 순매수")
        if total_inst > 100000:
            comment_parts.append("기관 대규모 순매수")
        if theme.up_count >= theme.stock_count * 0.8:
            comment_parts.append("대부분 종목 상승")

        analysis_comment = " | ".join(comment_parts) if comment_parts else "보통"

        return ThemeAnalysis(
            theme=theme,
            score=score,
            momentum=momentum,
            is_hot=theme.change_rate > 3,
            volume_surge=theme.total_volume > 10000000,
            foreign_buying=total_foreign > 0,
            inst_buying=total_inst > 0,
            top_stocks=stock_scores[:5],
            analysis_comment=analysis_comment
        )

    async def get_market_analysis(self, force_refresh: bool = False) -> MarketAnalysis:
        """전체 시장 분석"""

        # 캐시 확인
        now = datetime.now()
        if (not force_refresh
            and self._cache
            and self._cache_time
            and now - self._cache_time < self._cache_duration):
            return self._cache

        logger.info("시장 분석 시작...")

        # 테마 데이터 수집
        themes = await self.crawler.get_top_themes_with_details(top_n=10)

        # 테마별 분석
        theme_analyses = [self.analyze_theme(t) for t in themes]
        theme_analyses.sort(key=lambda x: x.score, reverse=True)

        # 상위 추천 종목 선정
        all_stocks = []
        for ta in theme_analyses:
            all_stocks.extend(ta.top_stocks)
        all_stocks.sort(key=lambda x: x.total_score, reverse=True)
        recommended = all_stocks[:10]

        # 시장 센티먼트 판단
        avg_change = sum(t.theme.change_rate for t in theme_analyses) / len(theme_analyses) if theme_analyses else 0
        if avg_change > 2:
            sentiment = "강세"
        elif avg_change > 0:
            sentiment = "상승"
        elif avg_change > -2:
            sentiment = "혼조"
        else:
            sentiment = "약세"

        # 상위 섹터
        top_sectors = [ta.theme.name for ta in theme_analyses[:5]]

        # 주의사항
        phase = self.get_market_phase()
        caution = self._get_caution_message(phase, sentiment)

        analysis = MarketAnalysis(
            timestamp=now,
            phase=phase,
            hot_themes=theme_analyses[:5],
            recommended_stocks=recommended,
            market_sentiment=sentiment,
            top_sectors=top_sectors,
            caution_message=caution
        )

        # 캐시 저장
        self._cache = analysis
        self._cache_time = now

        logger.info(f"시장 분석 완료: {len(theme_analyses)}개 테마, {len(recommended)}개 추천")

        return analysis

    def _get_caution_message(self, phase: MarketPhase, sentiment: str) -> str:
        """시간대별 주의사항 (홍인기 조언 기반)"""

        messages = {
            MarketPhase.PRE_MARKET: (
                "📌 장전 분석 시간입니다.\n"
                "• 전일 미국증시, 선물 확인\n"
                "• 주요 뉴스 체크\n"
                "• 예상 테마 준비"
            ),
            MarketPhase.OPENING: (
                "⚡ 동시호가/장초반입니다.\n"
                "• 수급 쏠림 주의\n"
                "• 빠른 판단 필요\n"
                "• 무리한 추격매수 금지"
            ),
            MarketPhase.MORNING: (
                "📈 오전장입니다.\n"
                "• 돌파 매매 적합\n"
                "• 주도주 확인 후 진입\n"
                "• 비중 관리 철저히"
            ),
            MarketPhase.LUNCH: (
                "🍽 점심시간입니다.\n"
                "• 거래량 감소 구간\n"
                "• 신규 진입 자제\n"
                "• 오후장 대비"
            ),
            MarketPhase.AFTERNOON: (
                "📉 오후장입니다.\n"
                "• 눌림 매매 적합\n"
                "• 후발주 주의\n"
                "• 손절 원칙 준수"
            ),
            MarketPhase.CLOSING: (
                "🔔 장마감 동시호가입니다.\n"
                "• 신규 진입 금지\n"
                "• 내일 전략 수립"
            ),
            MarketPhase.AFTER_MARKET: (
                "🌙 장 마감 후입니다.\n"
                "• 오늘 매매 복기\n"
                "• 내일 테마 분석"
            )
        }

        base_msg = messages.get(phase, "")

        if sentiment == "강세":
            base_msg += "\n\n💪 시장 강세 - 적극 대응 가능"
        elif sentiment == "약세":
            base_msg += "\n\n⚠️ 시장 약세 - 보수적 대응 권장"

        return base_msg

    async def get_premarket_analysis(self) -> dict:
        """장전 분석 (9시 전)"""
        logger.info("장전 분석 시작...")

        # 전일 테마 데이터
        themes = await self.crawler.get_theme_list()

        # 상위 테마
        sorted_themes = sorted(themes, key=lambda x: x.change_rate, reverse=True)[:10]

        # 섹터 분류
        hot_themes = [t.name for t in sorted_themes if t.change_rate > 3]
        rising_themes = [t.name for t in sorted_themes if 0 < t.change_rate <= 3]

        # 뉴스 기반 예측 (병렬 처리)
        news_predictions = await self.analyze_news_for_themes(
            [t.name for t in sorted_themes[:5]]
        )

        # 뉴스 기반 예상 핫 테마
        predicted_hot = [
            p.theme_name for p in news_predictions
            if p.hot_score > 50 and p.sentiment in ["positive", "very_positive"]
        ]

        return {
            "analysis_time": datetime.now().isoformat(),
            "market_phase": MarketPhase.PRE_MARKET.value,
            "previous_hot_themes": hot_themes,
            "previous_rising_themes": rising_themes,
            "top_themes": [
                {"name": t.name, "change_rate": t.change_rate}
                for t in sorted_themes
            ],
            "news_analysis": [
                {
                    "theme": p.theme_name,
                    "news_count": p.news_count,
                    "hot_score": p.hot_score,
                    "sentiment": p.sentiment,
                    "key_issues": p.key_issues,
                    "supply_prediction": p.supply_prediction,
                    "confidence": p.prediction_confidence
                }
                for p in news_predictions
            ],
            "predicted_hot_themes": predicted_hot,
            "recommendation": (
                "🌅 장전 분석\n\n"
                f"📌 전일 핫 테마: {', '.join(hot_themes[:3]) if hot_themes else '없음'}\n"
                f"📈 상승 테마: {', '.join(rising_themes[:3]) if rising_themes else '없음'}\n"
                f"🔮 뉴스 기반 예상: {', '.join(predicted_hot[:3]) if predicted_hot else '분석 중'}\n\n"
                "💡 체크리스트:\n"
                "• 미국 증시 확인\n"
                "• 선물 동향 확인\n"
                "• 주요 뉴스/공시 확인\n"
                "• 전일 강세 테마 연속성 판단"
            )
        }

    async def analyze_news_for_themes(
        self,
        theme_names: list[str]
    ) -> list[ThemeNewsSummary]:
        """테마별 뉴스 분석 및 수급 예측"""
        summaries = []

        # 캐시 확인
        now = datetime.now()
        if (self._news_cache_time and
            now - self._news_cache_time < self._news_cache_duration):
            # 캐시된 데이터 사용
            for name in theme_names:
                if name in self._news_cache:
                    news = self._news_cache[name]
                    summaries.append(self._create_news_summary(news))
            if summaries:
                return summaries

        # 뉴스 크롤링 (병렬)
        tasks = []
        for name in theme_names:
            keywords = THEME_KEYWORDS.get(name, [name])
            tasks.append(self.news_crawler.get_theme_news(name, keywords))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 캐시 업데이트
        self._news_cache_time = now

        for name, result in zip(theme_names, results):
            if isinstance(result, Exception):
                logger.error(f"뉴스 분석 실패 ({name}): {result}")
                continue

            self._news_cache[name] = result
            summaries.append(self._create_news_summary(result))

        return summaries

    def _create_news_summary(self, news: ThemeNews) -> ThemeNewsSummary:
        """뉴스 분석 결과를 요약으로 변환"""
        # 수급 예측
        supply_prediction, confidence = self._predict_supply_from_news(news)

        return ThemeNewsSummary(
            theme_name=news.theme_name,
            news_count=len(news.news_items),
            hot_score=news.hot_score,
            sentiment=news.sentiment_summary,
            key_issues=news.key_issues[:3],
            supply_prediction=supply_prediction,
            prediction_confidence=confidence
        )

    def _predict_supply_from_news(self, news: ThemeNews) -> tuple[str, float]:
        """뉴스 기반 수급 예측"""
        # 기본 신뢰도
        confidence = 30.0

        # 뉴스 양에 따른 신뢰도 증가
        if len(news.news_items) >= 10:
            confidence += 20
        elif len(news.news_items) >= 5:
            confidence += 10

        # 핫 스코어 반영
        confidence += min(news.hot_score / 5, 20)

        # 감성 기반 예측
        if news.sentiment_summary == "very_positive":
            return "매수세 예상 (강)", min(confidence + 20, 90)
        elif news.sentiment_summary == "positive":
            return "매수세 예상", min(confidence + 10, 80)
        elif news.sentiment_summary == "very_negative":
            return "매도세 예상 (강)", min(confidence + 20, 90)
        elif news.sentiment_summary == "negative":
            return "매도세 예상", min(confidence + 10, 80)

        return "중립", confidence

    async def get_realtime_supply_analysis(
        self,
        theme_name: str
    ) -> SupplyFlowAnalysis:
        """실시간 수급 분석 (장중)"""
        # 테마 실시간 데이터 조회
        themes = await self.crawler.get_theme_list()
        target_theme = None

        for t in themes:
            if t.name == theme_name or theme_name in t.name:
                target_theme = t
                break

        if not target_theme:
            return SupplyFlowAnalysis(
                theme_name=theme_name,
                current_supply="알 수 없음",
                foreign_flow="알 수 없음",
                inst_flow="알 수 없음",
                volume_change=0.0,
                is_surging=False,
                alert_message="테마를 찾을 수 없습니다"
            )

        # 상세 종목 데이터
        stocks = await self.crawler.get_theme_stocks(target_theme.code)

        # 외인/기관 흐름 계산
        total_foreign = 0
        total_inst = 0

        for stock in stocks[:5]:
            investor = await self.crawler.get_investor_trends(stock.code)
            total_foreign += investor.get('foreign_change', 0)
            total_inst += investor.get('inst_change', 0)
            await asyncio.sleep(0.2)

        # 수급 판단
        if total_foreign > 100000:
            foreign_flow = "외인 대규모 순매수 🌍"
        elif total_foreign > 0:
            foreign_flow = "외인 순매수"
        elif total_foreign < -100000:
            foreign_flow = "외인 대규모 순매도 ⚠️"
        elif total_foreign < 0:
            foreign_flow = "외인 순매도"
        else:
            foreign_flow = "외인 중립"

        if total_inst > 100000:
            inst_flow = "기관 대규모 순매수 🏛"
        elif total_inst > 0:
            inst_flow = "기관 순매수"
        elif total_inst < -100000:
            inst_flow = "기관 대규모 순매도 ⚠️"
        elif total_inst < 0:
            inst_flow = "기관 순매도"
        else:
            inst_flow = "기관 중립"

        # 종합 수급
        if total_foreign > 0 and total_inst > 0:
            current_supply = "매수세 집중 🔥"
            is_surging = True
        elif total_foreign > 0 or total_inst > 0:
            current_supply = "매수세 우위"
            is_surging = False
        elif total_foreign < 0 and total_inst < 0:
            current_supply = "매도세 집중 ⚠️"
            is_surging = False
        elif total_foreign < 0 or total_inst < 0:
            current_supply = "매도세 우위"
            is_surging = False
        else:
            current_supply = "중립"
            is_surging = False

        # 알림 메시지
        alert = self._generate_supply_alert(
            theme_name, current_supply, target_theme.change_rate,
            total_foreign, total_inst
        )

        return SupplyFlowAnalysis(
            theme_name=theme_name,
            current_supply=current_supply,
            foreign_flow=foreign_flow,
            inst_flow=inst_flow,
            volume_change=target_theme.change_rate,
            is_surging=is_surging,
            alert_message=alert
        )

    def _generate_supply_alert(
        self,
        theme_name: str,
        supply: str,
        change_rate: float,
        foreign: int,
        inst: int
    ) -> str:
        """수급 알림 메시지 생성"""
        msgs = [f"📊 {theme_name} 실시간 수급"]

        if "집중" in supply and change_rate > 3:
            msgs.append(f"🚨 주목! 수급 + 주가 동시 상승 ({change_rate:+.1f}%)")
        elif "매수세" in supply:
            msgs.append(f"💰 매수세 진입 중")
        elif "매도세" in supply:
            msgs.append(f"⚠️ 매도세 주의")

        if foreign > 100000:
            msgs.append(f"🌍 외인 대규모 매집 ({foreign:+,}주)")
        if inst > 100000:
            msgs.append(f"🏛 기관 대규모 매집 ({inst:+,}주)")

        return "\n".join(msgs)

    async def get_all_themes_supply(self) -> list[SupplyFlowAnalysis]:
        """모든 핫 테마 수급 분석"""
        analysis = await self.get_market_analysis()

        supply_analyses = []
        for ta in analysis.hot_themes[:5]:
            supply = await self.get_realtime_supply_analysis(ta.theme.name)
            supply_analyses.append(supply)
            await asyncio.sleep(0.5)

        return supply_analyses

    async def get_theme_ranking(self, top_n: int = 30, force_refresh: bool = False) -> list[ThemeRanking]:
        """
        테마 종합 순위 - 가격/뉴스/수급 종합 분석

        모든 테마를 다음 기준으로 순위 매김:
        1. 가격 모멘텀 (30점) - 등락률 기반
        2. 뉴스 핫스코어 (25점) - 뉴스 양과 최신성
        3. 뉴스 감성 (20점) - 긍정/부정 비율
        4. 수급 예측 (25점) - 뉴스 기반 수급 예측
        """
        # 캐시 확인
        now = datetime.now()
        if (not force_refresh
            and self._ranking_cache
            and self._ranking_cache_time
            and now - self._ranking_cache_time < self._ranking_cache_duration):
            logger.debug("테마 순위 캐시 사용")
            return self._ranking_cache[:top_n]

        logger.info(f"테마 종합 순위 분석 시작 (top {top_n})")

        # 1. 모든 테마 조회
        themes = await self.crawler.get_theme_list()
        logger.info(f"총 {len(themes)}개 테마 조회됨")

        # 2. 상위 테마들에 대해 뉴스 분석 (병렬 처리)
        # 등락률 기준 상위 + 하위 테마 선별
        sorted_themes = sorted(themes, key=lambda x: x.change_rate, reverse=True)
        analysis_targets = sorted_themes[:top_n]  # 상위 N개

        # 뉴스 분석 대상 테마명
        theme_names = [t.name for t in analysis_targets]

        # 3. 뉴스 분석 (최대 15개씩 병렬 처리)
        news_summaries: dict[str, ThemeNewsSummary] = {}

        batch_size = 10
        for i in range(0, len(theme_names), batch_size):
            batch = theme_names[i:i+batch_size]
            summaries = await self.analyze_news_for_themes(batch)
            for s in summaries:
                news_summaries[s.theme_name] = s
            await asyncio.sleep(0.5)

        # 4. 종합 점수 계산
        rankings: list[ThemeRanking] = []

        for theme in analysis_targets:
            news = news_summaries.get(theme.name)

            # 가격 모멘텀 점수 (30점)
            if theme.change_rate >= 5:
                momentum_score = 30
            elif theme.change_rate >= 3:
                momentum_score = 25
            elif theme.change_rate >= 2:
                momentum_score = 20
            elif theme.change_rate >= 1:
                momentum_score = 15
            elif theme.change_rate >= 0:
                momentum_score = 10
            elif theme.change_rate >= -2:
                momentum_score = 5
            else:
                momentum_score = 0

            # 뉴스 관련 점수 (기본값)
            news_score = 5
            sentiment_score = 10
            supply_score = 10
            news_count = 0
            news_hot_score = 0.0
            sentiment = "neutral"
            supply_prediction = "중립"
            confidence = 30.0
            key_issues = []

            if news:
                news_count = news.news_count
                news_hot_score = news.hot_score
                sentiment = news.sentiment
                supply_prediction = news.supply_prediction
                confidence = news.prediction_confidence
                key_issues = news.key_issues

                # 뉴스 핫스코어 점수 (25점)
                if news.hot_score >= 70:
                    news_score = 25
                elif news.hot_score >= 50:
                    news_score = 20
                elif news.hot_score >= 30:
                    news_score = 15
                elif news.hot_score >= 10:
                    news_score = 10
                else:
                    news_score = 5

                # 감성 점수 (20점)
                sentiment_scores = {
                    "very_positive": 20,
                    "positive": 15,
                    "neutral": 10,
                    "negative": 5,
                    "very_negative": 0
                }
                sentiment_score = sentiment_scores.get(news.sentiment, 10)

                # 수급 예측 점수 (25점)
                if "매수세 예상 (강)" in news.supply_prediction:
                    supply_score = 25
                elif "매수세 예상" in news.supply_prediction:
                    supply_score = 20
                elif "중립" in news.supply_prediction:
                    supply_score = 12
                elif "매도세 예상" in news.supply_prediction:
                    supply_score = 5
                else:
                    supply_score = 0

            # 종합 점수
            total_score = momentum_score + news_score + sentiment_score + supply_score

            # 등급 결정
            if total_score >= 85:
                grade = "A"
            elif total_score >= 70:
                grade = "B"
            elif total_score >= 55:
                grade = "C"
            elif total_score >= 40:
                grade = "D"
            else:
                grade = "F"

            # 투자 의견 생성
            recommendation = self._generate_theme_recommendation(
                theme.name, total_score, grade, theme.change_rate,
                sentiment, supply_prediction
            )

            rankings.append(ThemeRanking(
                rank=0,  # 나중에 설정
                theme_name=theme.name,
                theme_code=theme.code,
                total_score=total_score,
                momentum_score=momentum_score,
                news_score=news_score,
                sentiment_score=sentiment_score,
                supply_score=supply_score,
                change_rate=theme.change_rate,
                news_count=news_count,
                news_hot_score=news_hot_score,
                sentiment=sentiment,
                supply_prediction=supply_prediction,
                confidence=confidence,
                key_issues=key_issues,
                recommendation=recommendation,
                grade=grade
            ))

        # 5. 순위 정렬 및 설정
        rankings.sort(key=lambda x: x.total_score, reverse=True)
        for i, r in enumerate(rankings):
            r.rank = i + 1

        # 캐시 저장
        self._ranking_cache = rankings
        self._ranking_cache_time = datetime.now()

        logger.info(f"테마 종합 순위 분석 완료: {len(rankings)}개 테마")
        return rankings[:top_n]

    def _generate_theme_recommendation(
        self,
        theme_name: str,
        score: float,
        grade: str,
        change_rate: float,
        sentiment: str,
        supply_prediction: str
    ) -> str:
        """테마 투자 의견 생성"""
        parts = []

        # 등급별 기본 의견
        if grade == "A":
            parts.append("⭐ 최상위 관심 테마")
        elif grade == "B":
            parts.append("👀 주목할 테마")
        elif grade == "C":
            parts.append("📊 관망")
        elif grade == "D":
            parts.append("⚠️ 주의")
        else:
            parts.append("🚫 회피 권장")

        # 상세 분석
        if change_rate > 5:
            parts.append("급등 중 (추격매수 주의)")
        elif change_rate > 3:
            parts.append("강세 지속")
        elif change_rate > 0:
            parts.append("상승 추세")
        elif change_rate < -3:
            parts.append("급락 중")

        if "very_positive" in sentiment:
            parts.append("뉴스 매우 긍정적")
        elif "positive" in sentiment:
            parts.append("뉴스 긍정적")
        elif "negative" in sentiment:
            parts.append("뉴스 부정적")

        if "매수세" in supply_prediction:
            parts.append("수급 양호")
        elif "매도세" in supply_prediction:
            parts.append("수급 주의")

        return " | ".join(parts)

    async def get_hot_themes_by_period(self, days: int = 1, top_n: int = 20, force_refresh: bool = False) -> list[PeriodHotTheme]:
        """
        기간별 핫 테마 조회

        Args:
            days: 기간 (1, 3, 7, 30일)
            top_n: 상위 N개 테마

        Returns:
            기간 수익률 기준 정렬된 테마 목록
        """
        # 캐시 확인
        now = datetime.now()
        if (not force_refresh
            and days in self._period_cache
            and days in self._period_cache_time
            and now - self._period_cache_time[days] < self._period_cache_duration):
            logger.debug(f"기간별 핫 테마 캐시 사용 ({days}일)")
            return self._period_cache[days][:top_n]

        logger.info(f"기간별 핫 테마 조회 시작: {days}일, 상위 {top_n}개")

        # 1. 전체 테마 목록 조회
        themes = await self.crawler.get_theme_list()
        if not themes:
            logger.warning("테마 목록이 비어있습니다")
            return []

        # 등락률 기준 상위 테마 선택 (분석 대상)
        sorted_themes = sorted(themes, key=lambda x: abs(x.change_rate), reverse=True)
        target_themes = sorted_themes[:min(top_n * 2, len(sorted_themes))]

        # 2. 날짜 계산
        end_date = date.today()
        start_date = end_date - timedelta(days=days + 5)  # 여유분 추가

        # 3. 각 테마별 기간 수익률 계산
        results: list[PeriodHotTheme] = []

        for theme in target_themes:
            try:
                period_data = await self._calculate_theme_period_return(
                    theme, days, start_date, end_date
                )
                if period_data:
                    results.append(period_data)
            except Exception as e:
                logger.warning(f"테마 {theme.name} 기간 수익률 계산 실패: {e}")
                continue

        # 4. 수익률 기준 정렬 및 순위 부여
        results.sort(key=lambda x: x.change_rate, reverse=True)
        for i, item in enumerate(results):
            item.rank = i + 1

        # 캐시 저장
        self._period_cache[days] = results
        self._period_cache_time[days] = datetime.now()

        logger.info(f"기간별 핫 테마 조회 완료: {len(results)}개 테마")
        return results[:top_n]

    async def _calculate_theme_period_return(
        self,
        theme: Theme,
        days: int,
        start_date: date,
        end_date: date
    ) -> Optional[PeriodHotTheme]:
        """테마의 기간 수익률 계산"""
        try:
            # 테마 종목 조회
            stocks = await self.crawler.get_theme_stocks(theme.code)
            if not stocks or len(stocks) < 3:
                return None

            # 종목별 기간 수익률 계산 (병렬 처리)
            stock_codes = [s.code for s in stocks[:20]]  # 상위 20개 종목만

            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=5) as executor:
                returns = await loop.run_in_executor(
                    executor,
                    self._get_stocks_period_return,
                    stock_codes, days, start_date, end_date
                )

            if not returns:
                return None

            # 통계 계산
            valid_returns = [r for r in returns if r is not None]
            if not valid_returns:
                return None

            up_count = sum(1 for r in valid_returns if r['change_rate'] > 0)
            down_count = sum(1 for r in valid_returns if r['change_rate'] < 0)
            total_count = len(valid_returns)

            avg_change = sum(r['change_rate'] for r in valid_returns) / total_count
            up_ratio = (up_count / total_count) * 100 if total_count > 0 else 0

            # 상승 상위 종목
            sorted_returns = sorted(valid_returns, key=lambda x: x['change_rate'], reverse=True)
            top_gainers = sorted_returns[:3]

            # 모멘텀 판단
            if avg_change > 5:
                momentum = "strong_up"
                strength = "강세"
            elif avg_change > 2:
                momentum = "up"
                strength = "강세"
            elif avg_change > 0:
                momentum = "slight_up"
                strength = "보합"
            elif avg_change > -2:
                momentum = "slight_down"
                strength = "보합"
            elif avg_change > -5:
                momentum = "down"
                strength = "약세"
            else:
                momentum = "strong_down"
                strength = "약세"

            return PeriodHotTheme(
                rank=0,  # 나중에 설정
                theme_code=theme.code,
                theme_name=theme.name,
                period_days=days,
                change_rate=avg_change,
                avg_change_rate=avg_change,
                stock_count=total_count,
                up_count=up_count,
                down_count=down_count,
                up_ratio=up_ratio,
                top_gainers=top_gainers,
                leader_stock=theme.leader_stock or (top_gainers[0]['name'] if top_gainers else ""),
                momentum=momentum,
                strength=strength
            )

        except Exception as e:
            logger.error(f"테마 기간 수익률 계산 실패: {theme.name}, {e}")
            return None

    def _get_stocks_period_return(
        self,
        stock_codes: list[str],
        days: int,
        start_date: date,
        end_date: date
    ) -> list[dict]:
        """종목들의 기간 수익률 조회 (동기)"""
        results = []

        for code in stock_codes:
            try:
                # OHLCV 조회
                df = pykrx_stock.get_market_ohlcv(
                    start_date.strftime("%Y%m%d"),
                    end_date.strftime("%Y%m%d"),
                    code
                )

                if df is None or df.empty or len(df) < 2:
                    continue

                # 기간 수익률 계산
                # days일 전 ~ 오늘까지
                if len(df) > days:
                    start_price = df['종가'].iloc[-(days+1)]
                    end_price = df['종가'].iloc[-1]
                else:
                    start_price = df['종가'].iloc[0]
                    end_price = df['종가'].iloc[-1]

                if start_price > 0:
                    change_rate = ((end_price - start_price) / start_price) * 100
                else:
                    change_rate = 0

                # 종목명 조회
                try:
                    name = pykrx_stock.get_market_ticker_name(code)
                except:
                    name = code

                results.append({
                    'code': code,
                    'name': name,
                    'change_rate': round(change_rate, 2),
                    'start_price': int(start_price),
                    'end_price': int(end_price)
                })

            except Exception as e:
                logger.debug(f"종목 {code} 수익률 조회 실패: {e}")
                continue

        return results


# 전역 인스턴스
_analyzer: Optional[ThemeAnalyzer] = None


def get_theme_analyzer() -> ThemeAnalyzer:
    """테마 분석기 싱글톤"""
    global _analyzer
    if _analyzer is None:
        _analyzer = ThemeAnalyzer()
    return _analyzer


async def main():
    """테스트"""
    analyzer = ThemeAnalyzer()

    try:
        print("="*60)
        print("테마 분석 대시보드 테스트")
        print("="*60)

        # 시장 분석
        analysis = await analyzer.get_market_analysis()

        print(f"\n📊 분석 시간: {analysis.timestamp}")
        print(f"📍 시장 상태: {analysis.phase.value}")
        print(f"📈 시장 센티먼트: {analysis.market_sentiment}")

        print(f"\n🔥 상위 테마:")
        for ta in analysis.hot_themes:
            print(f"  • {ta.theme.name}: {ta.momentum} ({ta.theme.change_rate:+.2f}%)")
            print(f"    {ta.analysis_comment}")

        print(f"\n⭐ 추천 종목 TOP 5:")
        for stock in analysis.recommended_stocks[:5]:
            print(f"  • [{stock.theme_name}] {stock.name} (점수: {stock.total_score:.0f})")
            print(f"    {stock.recommendation}")

        print(f"\n💬 주의사항:")
        print(analysis.caution_message)

    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
