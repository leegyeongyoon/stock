"""테마 분석 API 라우트"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from loguru import logger

from src.analysis.theme_analyzer import get_theme_analyzer, MarketPhase
from src.analysis.stock_analyzer import get_stock_analyzer


router = APIRouter(prefix="/api/themes", tags=["themes"])


# Response Models
class StockScoreResponse(BaseModel):
    code: str
    name: str
    theme_name: str
    total_score: float
    change_rate: float
    volume: int
    foreign_change: int
    inst_change: int
    is_leader: bool
    recommendation: str


class ThemeResponse(BaseModel):
    code: str
    name: str
    change_rate: float
    stock_count: int
    up_count: int
    down_count: int
    score: float
    momentum: str
    is_hot: bool
    volume_surge: bool
    foreign_buying: bool
    inst_buying: bool
    analysis_comment: str
    leader_stock: Optional[str]
    top_stocks: list[StockScoreResponse]


class MarketAnalysisResponse(BaseModel):
    timestamp: str
    phase: str
    phase_label: str
    market_sentiment: str
    top_sectors: list[str]
    caution_message: str
    hot_themes: list[ThemeResponse]
    recommended_stocks: list[StockScoreResponse]


class PremarketResponse(BaseModel):
    analysis_time: str
    market_phase: str
    previous_hot_themes: list[str]
    previous_rising_themes: list[str]
    top_themes: list[dict]
    news_analysis: list[dict] = []
    predicted_hot_themes: list[str] = []
    recommendation: str


class NewsAnalysisResponse(BaseModel):
    theme_name: str
    news_count: int
    hot_score: float
    sentiment: str
    key_issues: list[str]
    supply_prediction: str
    confidence: float


class SupplyFlowResponse(BaseModel):
    theme_name: str
    current_supply: str
    foreign_flow: str
    inst_flow: str
    volume_change: float
    is_surging: bool
    alert_message: str


class NewsItemResponse(BaseModel):
    title: str
    source: str
    url: str
    summary: str
    sentiment: str
    relevance_score: float


class ThemeRankingResponse(BaseModel):
    """테마 종합 순위"""
    rank: int
    theme_name: str
    theme_code: str
    total_score: float
    grade: str

    # 세부 점수
    momentum_score: float
    news_score: float
    sentiment_score: float
    supply_score: float

    # 원본 데이터
    change_rate: float
    news_count: int
    news_hot_score: float
    sentiment: str
    supply_prediction: str
    confidence: float

    # 분석
    key_issues: list[str]
    recommendation: str


class PeriodHotThemeResponse(BaseModel):
    """기간별 핫 테마"""
    rank: int
    theme_code: str
    theme_name: str
    period_days: int

    # 수익률
    change_rate: float
    avg_change_rate: float

    # 종목 정보
    stock_count: int
    up_count: int
    down_count: int
    up_ratio: float

    # 대표 종목
    top_gainers: list[dict]
    leader_stock: str

    # 분석
    momentum: str
    strength: str


class CandleResponse(BaseModel):
    time: str
    open: int
    high: int
    low: int
    close: int
    volume: int


class IndicatorsResponse(BaseModel):
    ma5: float
    ma10: float
    ma20: float
    ma60: float
    ma120: float = 0.0
    rsi14: float
    macd: float
    macd_signal: float
    macd_hist: float
    stoch_k: float = 50.0
    stoch_d: float = 50.0


class MultiDaySupplyResponse(BaseModel):
    """다일간 수급 데이터"""
    days: int
    foreign_total: int
    inst_total: int
    foreign_avg: float
    inst_avg: float
    trend: str


class VolumeAnalysisResponse(BaseModel):
    """거래량 분석"""
    today: int
    avg_5d: int
    avg_20d: int
    ratio_vs_5d: float
    ratio_vs_20d: float
    trend: str
    comment: str


class BollingerPositionResponse(BaseModel):
    """볼린저밴드 위치"""
    upper: float
    middle: float
    lower: float
    current: float
    position_pct: float
    zone: str
    comment: str


class PricePositionResponse(BaseModel):
    """가격 위치 분석"""
    current: int
    high_52w: int
    low_52w: int
    from_high_pct: float
    from_low_pct: float
    ma_20: float
    ma_60: float
    ma_120: float
    above_ma20: bool
    above_ma60: bool
    above_ma120: bool
    position_comment: str


class ValuationResponse(BaseModel):
    """밸류에이션"""
    market_cap: int
    per: float
    pbr: float
    eps: int
    bps: int
    dividend_yield: float
    comment: str


class BuySignalResponse(BaseModel):
    """매수 신호 분석"""
    score: int
    grade: str
    positives: list[str]
    negatives: list[str]
    recommendation: str
    risk_level: str


class StockDetailResponse(BaseModel):
    """종목 상세 정보 - 실전 투자 지표"""
    code: str
    name: str
    current_price: int
    change_rate: float
    change_amount: int
    volume: int
    trading_value: int
    open_price: int
    high_price: int
    low_price: int
    prev_close: int

    # 다일간 수급 분석
    supply_3d: MultiDaySupplyResponse
    supply_7d: MultiDaySupplyResponse
    supply_10d: MultiDaySupplyResponse
    supply_30d: MultiDaySupplyResponse

    # 거래량 분석
    volume_analysis: VolumeAnalysisResponse

    # 볼린저밴드 위치
    bb_position: BollingerPositionResponse

    # 가격 위치
    price_position: PricePositionResponse

    # 밸류에이션
    valuation: ValuationResponse

    # 기술적 지표
    indicators: IndicatorsResponse

    # 분봉 데이터
    candles_1m: list[CandleResponse]
    candles_5m: list[CandleResponse]

    # 매수 신호 분석
    buy_signal: BuySignalResponse

    # 종합 코멘트
    summary: str


# Phase labels
PHASE_LABELS = {
    MarketPhase.PRE_MARKET: "장전",
    MarketPhase.OPENING: "동시호가/장초반",
    MarketPhase.MORNING: "오전장",
    MarketPhase.LUNCH: "점심시간",
    MarketPhase.AFTERNOON: "오후장",
    MarketPhase.CLOSING: "장마감 동시호가",
    MarketPhase.AFTER_MARKET: "장 마감 후",
}


@router.get("/analysis", response_model=MarketAnalysisResponse)
async def get_market_analysis(refresh: bool = False):
    """
    전체 시장 테마 분석

    - **refresh**: True면 캐시 무시하고 새로 분석
    """
    try:
        analyzer = get_theme_analyzer()
        analysis = await analyzer.get_market_analysis(force_refresh=refresh)

        # 응답 변환
        hot_themes = []
        for ta in analysis.hot_themes:
            stocks = [
                StockScoreResponse(
                    code=s.code,
                    name=s.name,
                    theme_name=s.theme_name,
                    total_score=s.total_score,
                    change_rate=s.change_rate,
                    volume=s.volume,
                    foreign_change=s.foreign_change,
                    inst_change=s.inst_change,
                    is_leader=s.is_leader,
                    recommendation=s.recommendation
                )
                for s in ta.top_stocks
            ]

            hot_themes.append(ThemeResponse(
                code=ta.theme.code,
                name=ta.theme.name,
                change_rate=ta.theme.change_rate,
                stock_count=ta.theme.stock_count,
                up_count=ta.theme.up_count,
                down_count=ta.theme.down_count,
                score=ta.score,
                momentum=ta.momentum,
                is_hot=ta.is_hot,
                volume_surge=ta.volume_surge,
                foreign_buying=ta.foreign_buying,
                inst_buying=ta.inst_buying,
                analysis_comment=ta.analysis_comment,
                leader_stock=ta.theme.leader_stock,
                top_stocks=stocks
            ))

        recommended = [
            StockScoreResponse(
                code=s.code,
                name=s.name,
                theme_name=s.theme_name,
                total_score=s.total_score,
                change_rate=s.change_rate,
                volume=s.volume,
                foreign_change=s.foreign_change,
                inst_change=s.inst_change,
                is_leader=s.is_leader,
                recommendation=s.recommendation
            )
            for s in analysis.recommended_stocks
        ]

        return MarketAnalysisResponse(
            timestamp=analysis.timestamp.isoformat(),
            phase=analysis.phase.value,
            phase_label=PHASE_LABELS.get(analysis.phase, ""),
            market_sentiment=analysis.market_sentiment,
            top_sectors=analysis.top_sectors,
            caution_message=analysis.caution_message,
            hot_themes=hot_themes,
            recommended_stocks=recommended
        )

    except Exception as e:
        logger.error(f"시장 분석 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/premarket", response_model=PremarketResponse)
async def get_premarket_analysis():
    """
    장전 분석 (9시 전 예상 테마)
    """
    try:
        analyzer = get_theme_analyzer()
        result = await analyzer.get_premarket_analysis()

        return PremarketResponse(**result)

    except Exception as e:
        logger.error(f"장전 분석 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/phase")
async def get_current_phase():
    """현재 시장 상태"""
    analyzer = get_theme_analyzer()
    phase = analyzer.get_market_phase()

    return {
        "phase": phase.value,
        "label": PHASE_LABELS.get(phase, ""),
        "timestamp": datetime.now().isoformat()
    }


@router.get("/top-stocks")
async def get_top_recommended_stocks(limit: int = 10):
    """
    추천 종목 TOP N

    - **limit**: 반환할 종목 수 (기본 10)
    """
    try:
        analyzer = get_theme_analyzer()
        analysis = await analyzer.get_market_analysis()

        stocks = [
            {
                "rank": i + 1,
                "code": s.code,
                "name": s.name,
                "theme": s.theme_name,
                "score": s.total_score,
                "change_rate": s.change_rate,
                "volume": s.volume,
                "foreign_change": s.foreign_change,
                "inst_change": s.inst_change,
                "is_leader": s.is_leader,
                "recommendation": s.recommendation,
                "scores": {
                    "momentum": s.momentum_score,
                    "volume": s.volume_score,
                    "foreign": s.foreign_score,
                    "inst": s.inst_score,
                    "leader": s.leader_score
                }
            }
            for i, s in enumerate(analysis.recommended_stocks[:limit])
        ]

        return {
            "timestamp": analysis.timestamp.isoformat(),
            "phase": analysis.phase.value,
            "sentiment": analysis.market_sentiment,
            "stocks": stocks
        }

    except Exception as e:
        logger.error(f"추천 종목 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/themes")
async def get_themes_list():
    """테마 목록 조회"""
    try:
        analyzer = get_theme_analyzer()
        analysis = await analyzer.get_market_analysis()

        themes = [
            {
                "code": ta.theme.code,
                "name": ta.theme.name,
                "change_rate": ta.theme.change_rate,
                "score": ta.score,
                "momentum": ta.momentum,
                "is_hot": ta.is_hot,
                "stock_count": ta.theme.stock_count,
                "up_count": ta.theme.up_count,
                "down_count": ta.theme.down_count,
                "leader": ta.theme.leader_stock,
                "foreign_buying": ta.foreign_buying,
                "inst_buying": ta.inst_buying
            }
            for ta in analysis.hot_themes
        ]

        return {
            "timestamp": analysis.timestamp.isoformat(),
            "themes": themes
        }

    except Exception as e:
        logger.error(f"테마 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/themes/{theme_code}")
async def get_theme_detail(theme_code: str):
    """특정 테마 상세 조회 - 모든 테마에서 조회 가능"""
    try:
        analyzer = get_theme_analyzer()
        analysis = await analyzer.get_market_analysis()

        # 1. 먼저 hot_themes에서 찾기 (상세 분석 데이터 있음)
        theme_analysis = None
        for ta in analysis.hot_themes:
            if ta.theme.code == theme_code:
                theme_analysis = ta
                break

        if theme_analysis:
            # hot_themes에서 찾은 경우 - 상세 분석 데이터 반환
            return {
                "code": theme_analysis.theme.code,
                "name": theme_analysis.theme.name,
                "change_rate": theme_analysis.theme.change_rate,
                "score": theme_analysis.score,
                "momentum": theme_analysis.momentum,
                "is_hot": theme_analysis.is_hot,
                "volume_surge": theme_analysis.volume_surge,
                "foreign_buying": theme_analysis.foreign_buying,
                "inst_buying": theme_analysis.inst_buying,
                "analysis_comment": theme_analysis.analysis_comment,
                "leader": theme_analysis.theme.leader_stock,
                "stock_count": theme_analysis.theme.stock_count,
                "up_count": theme_analysis.theme.up_count,
                "down_count": theme_analysis.theme.down_count,
                "stocks": [
                    {
                        "code": s.code,
                        "name": s.name,
                        "score": s.total_score,
                        "change_rate": s.change_rate,
                        "volume": s.volume,
                        "foreign_change": s.foreign_change,
                        "inst_change": s.inst_change,
                        "is_leader": s.is_leader,
                        "recommendation": s.recommendation,
                        "scores": {
                            "momentum": s.momentum_score,
                            "volume": s.volume_score,
                            "foreign": s.foreign_score,
                            "inst": s.inst_score,
                            "leader": s.leader_score
                        }
                    }
                    for s in theme_analysis.top_stocks
                ]
            }

        # 2. hot_themes에 없으면 전체 테마 목록에서 찾기
        all_themes = await analyzer.crawler.get_theme_list()
        theme = None
        for t in all_themes:
            if t.code == theme_code:
                theme = t
                break

        if not theme:
            raise HTTPException(status_code=404, detail="테마를 찾을 수 없습니다")

        # 3. 테마 종목 조회
        theme_stocks = await analyzer.crawler.get_theme_stocks(theme_code)

        return {
            "code": theme.code,
            "name": theme.name,
            "change_rate": theme.change_rate,
            "score": 0,
            "momentum": "neutral",
            "is_hot": False,
            "volume_surge": False,
            "foreign_buying": False,
            "inst_buying": False,
            "analysis_comment": f"{theme.name} 테마 종목입니다.",
            "leader": theme.leader_stock,
            "stock_count": theme.stock_count,
            "up_count": theme.up_count,
            "down_count": theme.down_count,
            "stocks": [
                {
                    "code": s.code,
                    "name": s.name,
                    "score": 0,
                    "change_rate": s.change_rate,
                    "volume": s.volume,
                    "foreign_change": 0,
                    "inst_change": 0,
                    "is_leader": s.name == theme.leader_stock,
                    "recommendation": "hold",
                    "scores": {
                        "momentum": 0,
                        "volume": 0,
                        "foreign": 0,
                        "inst": 0,
                        "leader": 0
                    }
                }
                for s in theme_stocks
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"테마 상세 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news/{theme_name}", response_model=list[NewsItemResponse])
async def get_theme_news(theme_name: str):
    """
    테마별 뉴스 조회

    - **theme_name**: 테마명 (예: AI, 2차전지, 반도체)
    """
    try:
        analyzer = get_theme_analyzer()
        from src.analysis.news_crawler import THEME_KEYWORDS

        keywords = THEME_KEYWORDS.get(theme_name, [theme_name])
        news = await analyzer.news_crawler.get_theme_news(theme_name, keywords)

        return [
            NewsItemResponse(
                title=item.title,
                source=item.source,
                url=item.url,
                summary=item.summary,
                sentiment=item.sentiment,
                relevance_score=item.relevance_score
            )
            for item in news.news_items[:20]
        ]

    except Exception as e:
        logger.error(f"테마 뉴스 조회 실패 ({theme_name}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news-analysis", response_model=list[NewsAnalysisResponse])
async def get_news_analysis(themes: str = "AI,반도체,2차전지,로봇,바이오"):
    """
    테마별 뉴스 분석 및 수급 예측

    - **themes**: 분석할 테마 목록 (콤마 구분)
    """
    try:
        analyzer = get_theme_analyzer()
        theme_list = [t.strip() for t in themes.split(",")]

        summaries = await analyzer.analyze_news_for_themes(theme_list)

        return [
            NewsAnalysisResponse(
                theme_name=s.theme_name,
                news_count=s.news_count,
                hot_score=s.hot_score,
                sentiment=s.sentiment,
                key_issues=s.key_issues,
                supply_prediction=s.supply_prediction,
                confidence=s.prediction_confidence
            )
            for s in summaries
        ]

    except Exception as e:
        logger.error(f"뉴스 분석 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/supply/{theme_name}", response_model=SupplyFlowResponse)
async def get_theme_supply(theme_name: str):
    """
    실시간 수급 분석 (장중)

    - **theme_name**: 테마명
    """
    try:
        analyzer = get_theme_analyzer()
        supply = await analyzer.get_realtime_supply_analysis(theme_name)

        return SupplyFlowResponse(
            theme_name=supply.theme_name,
            current_supply=supply.current_supply,
            foreign_flow=supply.foreign_flow,
            inst_flow=supply.inst_flow,
            volume_change=supply.volume_change,
            is_surging=supply.is_surging,
            alert_message=supply.alert_message
        )

    except Exception as e:
        logger.error(f"수급 분석 실패 ({theme_name}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/supply-all", response_model=list[SupplyFlowResponse])
async def get_all_supply():
    """
    모든 핫 테마 수급 분석

    장중 사용 권장 (09:00 ~ 15:30)
    """
    try:
        analyzer = get_theme_analyzer()
        supplies = await analyzer.get_all_themes_supply()

        return [
            SupplyFlowResponse(
                theme_name=s.theme_name,
                current_supply=s.current_supply,
                foreign_flow=s.foreign_flow,
                inst_flow=s.inst_flow,
                volume_change=s.volume_change,
                is_surging=s.is_surging,
                alert_message=s.alert_message
            )
            for s in supplies
        ]

    except Exception as e:
        logger.error(f"전체 수급 분석 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prediction")
async def get_supply_prediction():
    """
    뉴스 기반 오늘의 수급 예측

    장전/장중 모두 사용 가능
    """
    try:
        analyzer = get_theme_analyzer()

        # 주요 테마 목록
        major_themes = ["AI", "반도체", "2차전지", "로봇", "바이오", "조선", "방산", "원전"]

        summaries = await analyzer.analyze_news_for_themes(major_themes)

        # 정렬: 핫 스코어 + 긍정 감성 우선
        sorted_summaries = sorted(
            summaries,
            key=lambda x: (
                x.hot_score,
                1 if x.sentiment in ["positive", "very_positive"] else 0
            ),
            reverse=True
        )

        return {
            "timestamp": datetime.now().isoformat(),
            "phase": analyzer.get_market_phase().value,
            "predictions": [
                {
                    "rank": i + 1,
                    "theme": s.theme_name,
                    "hot_score": s.hot_score,
                    "sentiment": s.sentiment,
                    "supply_prediction": s.supply_prediction,
                    "confidence": s.prediction_confidence,
                    "key_issues": s.key_issues
                }
                for i, s in enumerate(sorted_summaries)
            ],
            "summary": {
                "predicted_hot": [s.theme_name for s in sorted_summaries if s.hot_score > 50][:3],
                "buy_expected": [s.theme_name for s in sorted_summaries if "매수세" in s.supply_prediction][:3],
                "caution": [s.theme_name for s in sorted_summaries if "매도세" in s.supply_prediction]
            }
        }

    except Exception as e:
        logger.error(f"수급 예측 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock/{stock_code}", response_model=StockDetailResponse)
async def get_stock_detail(stock_code: str, name: str = ""):
    """
    종목 상세 분석 - 실전 투자 지표

    - **stock_code**: 종목 코드 (예: 005930)
    - **name**: 종목명 (선택)

    포함 지표:
    - 3/7/10/30일 외인/기관 수급
    - 거래량 분석 (5일/20일 평균 대비)
    - 볼린저밴드 위치 분석
    - 52주 고저가 위치
    - 밸류에이션 (PER, PBR, 시가총액)
    - 매수 신호 분석 (A~F 등급)
    """
    try:
        analyzer = get_stock_analyzer()
        detail = await analyzer.get_stock_detail(stock_code, name)

        return StockDetailResponse(
            code=detail.code,
            name=detail.name,
            current_price=detail.current_price,
            change_rate=detail.change_rate,
            change_amount=detail.change_amount,
            volume=detail.volume,
            trading_value=detail.trading_value,
            open_price=detail.open_price,
            high_price=detail.high_price,
            low_price=detail.low_price,
            prev_close=detail.prev_close,

            # 다일간 수급 분석
            supply_3d=MultiDaySupplyResponse(
                days=detail.supply_3d.days,
                foreign_total=detail.supply_3d.foreign_total,
                inst_total=detail.supply_3d.inst_total,
                foreign_avg=detail.supply_3d.foreign_avg,
                inst_avg=detail.supply_3d.inst_avg,
                trend=detail.supply_3d.trend
            ),
            supply_7d=MultiDaySupplyResponse(
                days=detail.supply_7d.days,
                foreign_total=detail.supply_7d.foreign_total,
                inst_total=detail.supply_7d.inst_total,
                foreign_avg=detail.supply_7d.foreign_avg,
                inst_avg=detail.supply_7d.inst_avg,
                trend=detail.supply_7d.trend
            ),
            supply_10d=MultiDaySupplyResponse(
                days=detail.supply_10d.days,
                foreign_total=detail.supply_10d.foreign_total,
                inst_total=detail.supply_10d.inst_total,
                foreign_avg=detail.supply_10d.foreign_avg,
                inst_avg=detail.supply_10d.inst_avg,
                trend=detail.supply_10d.trend
            ),
            supply_30d=MultiDaySupplyResponse(
                days=detail.supply_30d.days,
                foreign_total=detail.supply_30d.foreign_total,
                inst_total=detail.supply_30d.inst_total,
                foreign_avg=detail.supply_30d.foreign_avg,
                inst_avg=detail.supply_30d.inst_avg,
                trend=detail.supply_30d.trend
            ),

            # 거래량 분석
            volume_analysis=VolumeAnalysisResponse(
                today=detail.volume_analysis.today,
                avg_5d=detail.volume_analysis.avg_5d,
                avg_20d=detail.volume_analysis.avg_20d,
                ratio_vs_5d=detail.volume_analysis.ratio_vs_5d,
                ratio_vs_20d=detail.volume_analysis.ratio_vs_20d,
                trend=detail.volume_analysis.trend,
                comment=detail.volume_analysis.comment
            ),

            # 볼린저밴드 위치
            bb_position=BollingerPositionResponse(
                upper=detail.bb_position.upper,
                middle=detail.bb_position.middle,
                lower=detail.bb_position.lower,
                current=detail.bb_position.current,
                position_pct=detail.bb_position.position_pct,
                zone=detail.bb_position.zone,
                comment=detail.bb_position.comment
            ),

            # 가격 위치
            price_position=PricePositionResponse(
                current=detail.price_position.current,
                high_52w=detail.price_position.high_52w,
                low_52w=detail.price_position.low_52w,
                from_high_pct=detail.price_position.from_high_pct,
                from_low_pct=detail.price_position.from_low_pct,
                ma_20=detail.price_position.ma_20,
                ma_60=detail.price_position.ma_60,
                ma_120=detail.price_position.ma_120,
                above_ma20=detail.price_position.above_ma20,
                above_ma60=detail.price_position.above_ma60,
                above_ma120=detail.price_position.above_ma120,
                position_comment=detail.price_position.position_comment
            ),

            # 밸류에이션
            valuation=ValuationResponse(
                market_cap=detail.valuation.market_cap,
                per=detail.valuation.per,
                pbr=detail.valuation.pbr,
                eps=detail.valuation.eps,
                bps=detail.valuation.bps,
                dividend_yield=detail.valuation.dividend_yield,
                comment=detail.valuation.comment
            ),

            # 기술적 지표
            indicators=IndicatorsResponse(
                ma5=detail.indicators.ma5,
                ma10=detail.indicators.ma10,
                ma20=detail.indicators.ma20,
                ma60=detail.indicators.ma60,
                ma120=detail.indicators.ma120,
                rsi14=detail.indicators.rsi14,
                macd=detail.indicators.macd,
                macd_signal=detail.indicators.macd_signal,
                macd_hist=detail.indicators.macd_hist,
                stoch_k=detail.indicators.stoch_k,
                stoch_d=detail.indicators.stoch_d
            ),

            # 분봉 데이터
            candles_1m=[
                CandleResponse(
                    time=c.time,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    volume=c.volume
                )
                for c in detail.candles_1m[-30:]
            ],
            candles_5m=[
                CandleResponse(
                    time=c.time,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    volume=c.volume
                )
                for c in detail.candles_5m[-30:]
            ],

            # 매수 신호 분석
            buy_signal=BuySignalResponse(
                score=detail.buy_signal.score,
                grade=detail.buy_signal.grade,
                positives=detail.buy_signal.positives,
                negatives=detail.buy_signal.negatives,
                recommendation=detail.buy_signal.recommendation,
                risk_level=detail.buy_signal.risk_level
            ),

            # 종합 코멘트
            summary=detail.summary
        )

    except Exception as e:
        logger.error(f"종목 상세 조회 실패 ({stock_code}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news-detail/{theme_name}")
async def get_theme_news_detail(theme_name: str):
    """
    테마별 뉴스 상세 조회 (기사 링크 및 내용 포함)

    - **theme_name**: 테마명
    """
    try:
        analyzer = get_theme_analyzer()
        from src.analysis.news_crawler import THEME_KEYWORDS

        keywords = THEME_KEYWORDS.get(theme_name, [theme_name])
        news = await analyzer.news_crawler.get_theme_news(theme_name, keywords)

        # 뉴스 분석 요약
        summaries = await analyzer.analyze_news_for_themes([theme_name])
        summary = summaries[0] if summaries else None

        return {
            "theme_name": theme_name,
            "keywords": keywords,
            "analysis": {
                "news_count": summary.news_count if summary else 0,
                "hot_score": summary.hot_score if summary else 0,
                "sentiment": summary.sentiment if summary else "neutral",
                "supply_prediction": summary.supply_prediction if summary else "중립",
                "confidence": summary.prediction_confidence if summary else 0,
                "key_issues": summary.key_issues if summary else []
            },
            "news_items": [
                {
                    "title": item.title,
                    "source": item.source,
                    "url": item.url,
                    "summary": item.summary,
                    "sentiment": item.sentiment,
                    "relevance_score": item.relevance_score,
                    "published_at": item.published_at.isoformat() if item.published_at else None
                }
                for item in news.news_items
            ]
        }

    except Exception as e:
        logger.error(f"뉴스 상세 조회 실패 ({theme_name}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-news/{stock_code}")
async def get_stock_news(stock_code: str, name: str = "", days: int = 14):
    """
    종목별 뉴스 조회 (최근 2주)

    - **stock_code**: 종목 코드 (예: 005930)
    - **name**: 종목명 (예: 삼성전자)
    - **days**: 검색 기간 (기본 14일)
    """
    try:
        analyzer = get_theme_analyzer()

        # 종목명이 없으면 코드로 조회
        stock_name = name
        if not stock_name:
            # 간단한 종목 매핑 (추후 DB 연동 가능)
            stock_name = stock_code

        news = await analyzer.news_crawler.get_stock_news(stock_name, stock_code, days=days)

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "news_count": len(news.news_items),
            "hot_score": news.hot_score,
            "sentiment": news.sentiment_summary,
            "key_issues": news.key_issues,
            "news_items": [
                {
                    "title": item.title,
                    "source": item.source,
                    "url": item.url,
                    "summary": item.summary,
                    "sentiment": item.sentiment,
                    "relevance_score": item.relevance_score,
                    "published_at": item.published_at.isoformat() if item.published_at else None
                }
                for item in news.news_items
            ]
        }

    except Exception as e:
        logger.error(f"종목 뉴스 조회 실패 ({stock_code}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ranking", response_model=list[ThemeRankingResponse])
async def get_theme_ranking(top_n: int = 30):
    """
    테마 종합 순위 - 가격/뉴스/수급 종합 분석

    모든 테마를 다음 기준으로 순위 매김:
    - 가격 모멘텀 (30점): 등락률 기반
    - 뉴스 핫스코어 (25점): 뉴스 양과 최신성
    - 뉴스 감성 (20점): 긍정/부정 비율
    - 수급 예측 (25점): 뉴스 기반 수급 예측

    등급:
    - A (85+): 최상위 관심
    - B (70-84): 주목할 테마
    - C (55-69): 관망
    - D (40-54): 주의
    - F (0-39): 회피 권장

    - **top_n**: 분석할 테마 수 (기본 30)
    """
    try:
        analyzer = get_theme_analyzer()
        rankings = await analyzer.get_theme_ranking(top_n=top_n)

        return [
            ThemeRankingResponse(
                rank=r.rank,
                theme_name=r.theme_name,
                theme_code=r.theme_code,
                total_score=r.total_score,
                grade=r.grade,
                momentum_score=r.momentum_score,
                news_score=r.news_score,
                sentiment_score=r.sentiment_score,
                supply_score=r.supply_score,
                change_rate=r.change_rate,
                news_count=r.news_count,
                news_hot_score=r.news_hot_score,
                sentiment=r.sentiment,
                supply_prediction=r.supply_prediction,
                confidence=r.confidence,
                key_issues=r.key_issues,
                recommendation=r.recommendation
            )
            for r in rankings
        ]

    except Exception as e:
        logger.error(f"테마 순위 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hot-themes/{days}", response_model=list[PeriodHotThemeResponse])
async def get_hot_themes_by_period(days: int = 1, top_n: int = 20):
    """
    기간별 핫 테마 조회

    지정된 기간 동안의 테마 수익률을 계산하여 순위를 매김.

    - **days**: 기간 (1, 3, 7, 30일)
    - **top_n**: 상위 N개 테마 (기본 20)

    Returns:
        기간 수익률 기준 정렬된 테마 목록
    """
    if days not in [1, 3, 7, 30]:
        raise HTTPException(status_code=400, detail="days must be 1, 3, 7, or 30")

    try:
        analyzer = get_theme_analyzer()
        themes = await analyzer.get_hot_themes_by_period(days=days, top_n=top_n)

        return [
            PeriodHotThemeResponse(
                rank=t.rank,
                theme_code=t.theme_code,
                theme_name=t.theme_name,
                period_days=t.period_days,
                change_rate=t.change_rate,
                avg_change_rate=t.avg_change_rate,
                stock_count=t.stock_count,
                up_count=t.up_count,
                down_count=t.down_count,
                up_ratio=t.up_ratio,
                top_gainers=t.top_gainers,
                leader_stock=t.leader_stock,
                momentum=t.momentum,
                strength=t.strength
            )
            for t in themes
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"기간별 핫 테마 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
