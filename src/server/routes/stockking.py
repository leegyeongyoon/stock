"""홍인기 매매법 대시보드 + 자동매매 트레이딩 API 라우트"""

import time as time_module
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from loguru import logger
from sqlalchemy import text

from src.strategies.hongstyle.hongstyle_engine import (
    get_hongstyle_engine,
    AnalysisResult,
    TRADING_RULES,
)
from src.strategies.hongstyle.daily_chart_analyzer import DailyChartAnalyzer
from src.analysis.stock_analyzer import get_stock_analyzer
from src.engine.hongstyle_runner import HongStyleRunner
from src.server.dependencies import get_engine
from src.database.connection import get_session


router = APIRouter(prefix="/api/stockking", tags=["stockking"])


# --- Cache ---
_cache: dict = {}
_cache_time: float = 0
CACHE_TTL = 30  # seconds


async def _get_cached_analysis() -> AnalysisResult:
    global _cache, _cache_time
    now = time_module.time()
    if now - _cache_time < CACHE_TTL and _cache:
        return _cache
    engine = get_hongstyle_engine()
    result = await engine.run_analysis()
    _cache = result
    _cache_time = now
    return result


# --- Response Models ---


class LeadingSectorResponse(BaseModel):
    sector_name: str
    total_trading_value: int
    stock_count: int
    avg_change_rate: float
    leader_stock: Optional[str] = None
    leader_code: Optional[str] = None
    is_primary: bool = False


class LeaderStockResponse(BaseModel):
    code: str
    name: str
    sector: str
    trading_value: int
    change_rate: float
    daily_position: str
    ki_score: float
    grade: str
    is_leader: bool
    patterns: list[str]


class SignalResponse(BaseModel):
    stock_code: str
    stock_name: str
    signal_type: str
    method: str
    confidence: float
    reason: str
    timestamp: str


class PatternAlertResponse(BaseModel):
    stock_code: str
    stock_name: str
    pattern_name: str
    severity: str
    description: str
    confidence: float
    detected_at: str


class DPlusCandidateResponse(BaseModel):
    code: str
    name: str
    d_day: int
    prev_change_rate: float
    prev_trading_value: int
    daily_position: str
    reason: str


class DailyPositionResponse(BaseModel):
    code: str
    name: str
    position_type: str
    resistance_levels: list[float]
    support_levels: list[float]
    ki_score: float
    description: str


class RuleStatusResponse(BaseModel):
    id: int
    rule: str
    category: str
    status: str
    note: str


class RulesResponse(BaseModel):
    rules: list[RuleStatusResponse]
    summary: dict


class MarketConditionResponse(BaseModel):
    phase: str
    phase_label: str
    condition: str
    is_caution_day: bool
    caution_reason: str
    sector_concentration: float
    timestamp: str


class DashboardResponse(BaseModel):
    timestamp: str
    market_condition: dict
    leading_sectors: list[dict]
    leader_stocks: list[dict]
    signals: list[dict]
    pattern_alerts: list[dict]
    d_plus_candidates: list[dict]
    rules_status: dict
    is_caution_day: bool


# --- Endpoints ---


@router.get("/dashboard")
async def get_dashboard():
    """메인 대시보드 데이터"""
    try:
        engine = get_hongstyle_engine()
        data = await engine.get_dashboard_data()
        return data
    except Exception as e:
        logger.error(f"대시보드 데이터 조회 실패: {e}")
        return {
            "timestamp": datetime.now().isoformat(),
            "market_condition": {"status": "error", "message": str(e)},
            "leading_sectors": [],
            "leader_stocks": [],
            "signals": [],
            "pattern_alerts": [],
            "d_plus_candidates": [],
            "trading_rules": {},
            "is_caution_day": True,
        }


@router.get("/leading-sector", response_model=list[LeadingSectorResponse])
async def get_leading_sectors():
    """주도 섹터 분석"""
    try:
        result = await _get_cached_analysis()

        sectors = []
        for i, s in enumerate(result.leading_sectors):
            leader = s.leader_stock
            sectors.append(LeadingSectorResponse(
                sector_name=s.sector_name,
                total_trading_value=s.trading_value,
                stock_count=s.stock_count,
                avg_change_rate=s.avg_change_rate,
                leader_stock=leader.get("name", "") if leader else None,
                leader_code=leader.get("code", "") if leader else None,
                is_primary=(i == 0),
            ))

        return sectors

    except Exception as e:
        logger.error(f"주도 섹터 조회 실패: {e}")
        return []


@router.get("/leader-stocks", response_model=list[LeaderStockResponse])
async def get_leader_stocks():
    """대장주 분석"""
    try:
        result = await _get_cached_analysis()

        stocks = []
        for sa in result.stock_analyses:
            ki = sa.ki_score.score
            if ki >= 70:
                grade = "A"
            elif ki >= 50:
                grade = "B"
            elif ki >= 30:
                grade = "C"
            else:
                grade = "D"

            stocks.append(LeaderStockResponse(
                code=sa.code,
                name=sa.name,
                sector="",
                trading_value=0,
                change_rate=0,
                daily_position=sa.daily_position.position_type,
                ki_score=sa.ki_score.score,
                grade=grade,
                is_leader=sa.is_leader,
                patterns=[p.pattern_name for p in sa.patterns],
            ))

        return stocks

    except Exception as e:
        logger.error(f"대장주 조회 실패: {e}")
        return []


@router.get("/signals", response_model=list[SignalResponse])
async def get_signals():
    """현재 진입/청산 시그널"""
    try:
        result = await _get_cached_analysis()

        signals = []
        for sa in result.stock_analyses:
            sig = sa.entry_signal
            signals.append(SignalResponse(
                stock_code=sa.code,
                stock_name=sa.name,
                signal_type=sig.action,
                method=sig.method,
                confidence=sig.confidence,
                reason=sig.reason,
                timestamp=result.timestamp.isoformat(),
            ))

        return signals

    except Exception as e:
        logger.error(f"시그널 조회 실패: {e}")
        return []


@router.get("/patterns/{code}", response_model=list[PatternAlertResponse])
async def get_patterns(code: str):
    """특정 종목 위험 패턴 감지"""
    try:
        result = await _get_cached_analysis()

        alerts = []
        for sa in result.stock_analyses:
            if sa.code == code:
                for p in sa.patterns:
                    alerts.append(PatternAlertResponse(
                        stock_code=sa.code,
                        stock_name=sa.name,
                        pattern_name=p.pattern_name,
                        severity=p.severity,
                        description=p.description,
                        confidence=p.confidence,
                        detected_at=p.detected_at.isoformat(),
                    ))
                break

        # 캐시에 없으면 전체 pattern_alerts에서 검색
        if not alerts:
            for p in result.pattern_alerts:
                alerts.append(PatternAlertResponse(
                    stock_code=code,
                    stock_name="",
                    pattern_name=p.pattern_name,
                    severity=p.severity,
                    description=p.description,
                    confidence=p.confidence,
                    detected_at=p.detected_at.isoformat(),
                ))

        return alerts

    except Exception as e:
        logger.error(f"패턴 조회 실패 ({code}): {e}")
        return []


@router.get("/d-plus", response_model=list[DPlusCandidateResponse])
async def get_d_plus_candidates():
    """D+1/D+2 후보 종목"""
    try:
        result = await _get_cached_analysis()

        candidates = []
        for c in result.d_plus_candidates:
            candidates.append(DPlusCandidateResponse(
                code=c.code,
                name=c.name,
                d_day=c.d_day,
                prev_change_rate=c.change_rate,
                prev_trading_value=c.trading_value,
                daily_position="",
                reason=c.reason,
            ))

        return candidates

    except Exception as e:
        logger.error(f"D+ 후보 조회 실패: {e}")
        return []


@router.get("/daily-position/{code}", response_model=DailyPositionResponse)
async def get_daily_position(code: str, name: str = ""):
    """종목 일봉 자리 분석"""
    try:
        stock_analyzer = get_stock_analyzer()
        daily_df = await stock_analyzer.get_ohlcv(code, days=120)

        chart_analyzer = DailyChartAnalyzer()

        if daily_df is None or daily_df.empty:
            return DailyPositionResponse(
                code=code,
                name=name or code,
                position_type="해당없음",
                resistance_levels=[],
                support_levels=[],
                ki_score=0,
                description="일봉 데이터 없음",
            )

        position = chart_analyzer.classify_daily_position(daily_df)
        ki = chart_analyzer.calculate_ki(daily_df)
        resistances = chart_analyzer.get_resistance_levels(daily_df)

        return DailyPositionResponse(
            code=code,
            name=name or code,
            position_type=position.position_type,
            resistance_levels=resistances,
            support_levels=position.support_levels,
            ki_score=ki.score,
            description=position.description,
        )

    except Exception as e:
        logger.error(f"일봉 자리 분석 실패 ({code}): {e}")
        return DailyPositionResponse(
            code=code,
            name=name or code,
            position_type="해당없음",
            resistance_levels=[],
            support_levels=[],
            ki_score=0,
            description=f"분석 오류: {e}",
        )


@router.get("/rules", response_model=RulesResponse)
async def get_trading_rules():
    """21개 매매 원칙 목록 + 현재 상태"""
    try:
        result = await _get_cached_analysis()
        rules_data = result.trading_rules

        rules = []
        for r in rules_data.get("rules", []):
            rules.append(RuleStatusResponse(
                id=r.get("id", 0),
                rule=r.get("rule", ""),
                category=r.get("category", ""),
                status=r.get("status", "unchecked"),
                note=r.get("note", ""),
            ))

        return RulesResponse(
            rules=rules,
            summary=rules_data.get("summary", {}),
        )

    except Exception as e:
        logger.error(f"매매 원칙 조회 실패: {e}")
        # 원칙 목록만이라도 반환
        rules = [
            RuleStatusResponse(
                id=r["id"],
                rule=r["rule"],
                category=r["category"],
                status="unchecked",
                note="",
            )
            for r in TRADING_RULES
        ]
        return RulesResponse(
            rules=rules,
            summary={"total": len(rules), "passed": 0, "failed": 0, "unchecked": len(rules), "compliance_rate": 0},
        )


@router.get("/market-condition", response_model=MarketConditionResponse)
async def get_market_condition():
    """시장 상태"""
    try:
        result = await _get_cached_analysis()
        mc = result.market_condition

        # 섹터 집중도 계산
        sector_concentration = 0.0
        if result.leading_sectors:
            total_value = sum(s.trading_value for s in result.leading_sectors)
            if total_value > 0:
                top_value = result.leading_sectors[0].trading_value
                sector_concentration = round(top_value / total_value * 100, 1)

        # 자제일 사유
        caution_reason = ""
        if result.is_caution_day:
            caution_reason = mc.get("description", "4개 이상 섹터 분산 - 주도 섹터 불분명")

        return MarketConditionResponse(
            phase=mc.get("status", "unknown"),
            phase_label=mc.get("label", "분석 중"),
            condition=mc.get("description", ""),
            is_caution_day=result.is_caution_day,
            caution_reason=caution_reason,
            sector_concentration=sector_concentration,
            timestamp=result.timestamp.isoformat(),
        )

    except Exception as e:
        logger.error(f"시장 상태 조회 실패: {e}")
        return MarketConditionResponse(
            phase="error",
            phase_label="오류",
            condition=str(e),
            is_caution_day=True,
            caution_reason=str(e),
            sector_concentration=0,
            timestamp=datetime.now().isoformat(),
        )


# ── 홍인기 트레이딩 API ───────────────────────────────────


class HongTradingStatusResponse(BaseModel):
    enabled: bool
    state: str
    consecutive_losses: int
    is_caution_day: bool
    trades_today: int
    positions_count: int
    day_pnl: float
    last_scan_time: Optional[str] = None


class HongPositionResponse(BaseModel):
    stock_code: str
    stock_name: str
    strategy_name: str
    quantity: int
    avg_price: int
    current_price: int
    unrealized_pnl: int
    unrealized_pnl_pct: float
    partial_sold: bool
    original_quantity: int
    entry_time: str


class HongTradeResponse(BaseModel):
    type: Optional[str] = None
    stock_code: str
    stock_name: str
    strategy_name: str
    quantity: int
    price: Optional[int] = None
    entry_price: Optional[int] = None
    exit_price: Optional[int] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    exit_reason: Optional[str] = None
    confidence: Optional[float] = None
    ki_score: Optional[float] = None
    time: str


class HongEventResponse(BaseModel):
    event_type: str
    message: str
    severity: str
    timestamp: str


class TradingActionResponse(BaseModel):
    success: bool
    message: str


@router.post("/trading/start", response_model=TradingActionResponse)
async def start_hong_trading():
    """홍인기 자동매매 시작."""
    try:
        engine = get_engine()
        result = await engine.start_hongstyle()
        return TradingActionResponse(**result)
    except Exception as e:
        logger.error(f"홍인기 자동매매 시작 실패: {e}")
        return TradingActionResponse(success=False, message=str(e))


@router.post("/trading/stop", response_model=TradingActionResponse)
async def stop_hong_trading():
    """홍인기 자동매매 중지."""
    try:
        engine = get_engine()
        result = await engine.stop_hongstyle()
        return TradingActionResponse(**result)
    except Exception as e:
        logger.error(f"홍인기 자동매매 중지 실패: {e}")
        return TradingActionResponse(success=False, message=str(e))


@router.get("/trading/status", response_model=HongTradingStatusResponse)
async def get_hong_trading_status():
    """홍인기 자동매매 상태."""
    try:
        engine = get_engine()
        status = engine.get_hongstyle_status()
        return HongTradingStatusResponse(**status)
    except Exception as e:
        logger.error(f"홍인기 상태 조회 실패: {e}")
        return HongTradingStatusResponse(
            enabled=False, state="ERROR", consecutive_losses=0,
            is_caution_day=False, trades_today=0, positions_count=0,
            day_pnl=0, last_scan_time=None,
        )


@router.get("/trading/positions", response_model=list[HongPositionResponse])
async def get_hong_positions():
    """홍인기 보유종목."""
    try:
        engine = get_engine()
        if not engine.hongstyle_runner:
            return []
        return engine.hongstyle_runner.get_hong_positions()
    except Exception as e:
        logger.error(f"홍인기 포지션 조회 실패: {e}")
        return []


@router.get("/trading/trades")
async def get_hong_trades():
    """홍인기 오늘 거래 내역."""
    try:
        engine = get_engine()
        if not engine.hongstyle_runner:
            return []
        return engine.hongstyle_runner.get_hong_trades()
    except Exception as e:
        logger.error(f"홍인기 거래 내역 조회 실패: {e}")
        return []


@router.get("/trading/events", response_model=list[HongEventResponse])
async def get_hong_events():
    """홍인기 최근 이벤트 로그."""
    try:
        engine = get_engine()
        if not engine.hongstyle_runner:
            return []
        return engine.hongstyle_runner.get_events(limit=50)
    except Exception as e:
        logger.error(f"홍인기 이벤트 조회 실패: {e}")
        return []


class ConvictionItemResponse(BaseModel):
    rank: int
    stock_code: str
    stock_name: str
    score: float
    confidence: float
    ki_score: float
    is_leader: bool
    leader_bonus: float
    daily_position: str
    position_desc: str
    method: str
    action: str
    reason: str
    alloc_pct: float
    alloc_label: str
    is_buyable: bool
    is_top: bool
    patterns: list[str] = []


class ConvictionRankingResponse(BaseModel):
    ranking: list[ConvictionItemResponse]
    top_n: int
    max_positions: int
    high_alloc_pct: float
    low_alloc_pct: float
    algorithm: dict


@router.get("/trading/conviction", response_model=ConvictionRankingResponse)
async def get_conviction_ranking():
    """확신도 순위 + 알고리즘 설명."""
    try:
        engine = get_engine()

        algorithm = {
            "name": "홍인기 집중투자 알고리즘",
            "steps": [
                {
                    "step": 1,
                    "title": "핫테마 탐지",
                    "desc": "ThemeAnalyzer로 오늘 상승률 상위 핫테마 5개 선정",
                },
                {
                    "step": 2,
                    "title": "종목 분석",
                    "desc": "테마별 탑3 종목의 일봉 자리(신고가/전고점돌파/바닥반등) + 끼 점수(0~100) 분석",
                },
                {
                    "step": 3,
                    "title": "시그널 생성",
                    "desc": "SignalGenerator가 자리+끼+대장주 여부로 매수 시그널 생성 (돌파매매/눌림매매)",
                },
                {
                    "step": 4,
                    "title": "확신도 점수",
                    "desc": "score = confidence × (끼/100) × 대장주보너스(1.3x). 높을수록 좋은 종목",
                },
                {
                    "step": 5,
                    "title": "TOP 5 선정",
                    "desc": "확신도 상위 5개만 진입 대상. 나머지는 아무리 좋아도 매수하지 않음",
                },
                {
                    "step": 6,
                    "title": "집중 배분",
                    "desc": "확신(conf≥0.7 & 끼≥50) → 자산의 50%, 보통 → 30%. 최대 2종목",
                },
            ],
            "exit_rules": [
                {"rule": "손절", "desc": "-4% 도달 시 전량 매도 (원칙 준수)"},
                {"rule": "1차 익절", "desc": "+5% 도달 시 70% 분할매도"},
                {"rule": "본전컷", "desc": "분할매도 후 수익률 +0.5% 이하로 복귀 시 잔여 전량 매도"},
                {"rule": "패턴 감지", "desc": "가분수/끼소진/거래량고점 등 위험 패턴 시 즉시 전량 매도"},
                {"rule": "2연속 손절", "desc": "2번 연속 손절 시 당일 매매 종료"},
            ],
            "score_formula": "confidence × (끼점수 / 100) × 대장주보너스(1.3x)",
            "stock_selection": [
                "시가총액 5000억 이상 종목만 매매 (20일 검증: 무필터 WR42% → 5000억+ WR52%)",
                "전일 기관 순매수 50~200억 종목 우선 (20일 검증: WR 56.1%, 합계 +76.60%)",
                "거래대금 상위 20 종목에서만 매매",
                "대장주(섹터 내 거래대금·상승률 1위) 위주",
                "끼 있는 종목만 (일봉 자리 + 거래대금 + 수급)",
            ],
            "backtest_verified": {
                "period": "20 거래일 (2026-01-16 ~ 2026-02-12)",
                "best_filter": "시총 5000억+ & 전일 기관 50~200억 + 눌림(95%깊이+오전거래량)",
                "results": {
                    "전체": "207건 WR 60.4% 합계 +96.83%",
                    "돌파만": "202건 WR 60.9% 합계 +95.60%",
                    "눌림만": "5건 WR 40.0% 합계 +1.23% (기존 53건 -10.99% → 나쁜눌림 제거)",
                },
                "comparison": {
                    "무필터": "250건 WR 42.0% -151.41%",
                    "시총5000억+": "298건 WR 51.7% +14.89%",
                    "시총5000억+기관순매수>0": "309건 WR 53.1% +58.22%",
                    "시총5000억+기관50~200억": "255건 WR 56.9% +84.61%",
                    "최종(+눌림95%깊이+오전거래량)": "207건 WR 60.4% +96.83%",
                },
                "pullback_optimization": {
                    "기존(98%눌림)": "53건 WR 41.5% -10.99%",
                    "95%깊이+오전거래량(채택)": "5건 WR 40.0% +1.23%",
                    "효과": "나쁜 눌림 48건 제거 → 전체 수익 +12.22% 개선",
                },
            },
            "avoid_rules": [
                "잡주(시총 5000억 미만): 급등 후 급락 패턴, 돌파매매 시 -151% (20일)",
                "뉴스빵: 비주도 섹터 단발성 뉴스 급등",
                "끼소진: 거래량 감소 + 상승폭 축소 종목",
                "가분수: 연속양봉 + 거래량 폭발 (고점 시그널)",
                "3파동: 상승 3번 반복 후 진입 (늦은 진입)",
                "깊은눌림: 50% 이상 되돌림 종목",
                "비주도: 당일 주도 섹터가 아닌 종목",
                "갭상승 시초가 매수: 승률 26% (20일 검증)",
            ],
            "timing_rules": [
                "9:00~9:30 관망 (변동성 큰 시간, 주도 섹터 확정만)",
                "9:30~11:00 돌파 매매 골든타임",
                "11:00~13:00 점심 관망 또는 소량 눌림만",
                "13:00~14:30 오후 눌림 매매 시간대",
                "14:30~15:20 동시호가 관망, D+1 후보 선정",
            ],
            "position_sizing": [
                "한 종목 최대 30% 비중",
                "강세장 총 비중 60~70%, 약세장 20~30%",
                "분할매수: 1차 50% → 2차 30% → 3차 20%",
                "하루 손실 한도 -2% 도달 시 매매 종료",
            ],
        }

        if not engine.hongstyle_runner:
            return ConvictionRankingResponse(
                ranking=[],
                top_n=HongStyleRunner.TOP_N_ONLY,
                max_positions=HongStyleRunner.MAX_POSITIONS,
                high_alloc_pct=HongStyleRunner.HIGH_CONFIDENCE_PCT,
                low_alloc_pct=HongStyleRunner.LOW_CONFIDENCE_PCT,
                algorithm=algorithm,
            )

        runner = engine.hongstyle_runner
        ranking_data = runner.get_conviction_ranking()

        return ConvictionRankingResponse(
            ranking=[ConvictionItemResponse(**item) for item in ranking_data],
            top_n=runner.TOP_N_ONLY,
            max_positions=runner.MAX_POSITIONS,
            high_alloc_pct=runner.HIGH_CONFIDENCE_PCT,
            low_alloc_pct=runner.LOW_CONFIDENCE_PCT,
            algorithm=algorithm,
        )
    except Exception as e:
        logger.error(f"확신도 순위 조회 실패: {e}")
        return ConvictionRankingResponse(
            ranking=[],
            top_n=HongStyleRunner.TOP_N_ONLY,
            max_positions=HongStyleRunner.MAX_POSITIONS,
            high_alloc_pct=HongStyleRunner.HIGH_CONFIDENCE_PCT,
            low_alloc_pct=HongStyleRunner.LOW_CONFIDENCE_PCT,
            algorithm={},
        )


# ── 홍인기 전략 가이드 API ────────────────────────────────


STRATEGY_GUIDE_SECTIONS = [
    {
        "id": "stock_selection",
        "title": "종목 선정",
        "icon": "target",
        "rules": [
            {"importance": "핵심", "rule": "시가총액 5000억 이상 종목만 매매", "detail": "20일 백테스트 검증: 무필터 WR 42% 합계 -151% → 시총 5000억+ WR 52% 합계 +15%. 소형주(잡주)는 급등 후 급락 패턴으로 돌파매매에서 체계적으로 손실."},
            {"importance": "핵심", "rule": "전일 기관 순매수 50~200억 종목 우선", "detail": "20일 백테스트 검증: 시총5000억+기관50~200억 조합이 최강. WR 56.1% 합계 +76.60%. 기관 순매수>0만 걸어도 +58%. 기관이 사는 종목은 돌파 후 관성 유지."},
            {"importance": "핵심", "rule": "거래대금 상위 20 종목에서만 매매한다", "detail": "1분봉 기준 거래대금 20억 이상만 대상. 거래대금이 곧 유동성이며, 유동성 없는 종목은 빠져나올 수 없다."},
            {"importance": "핵심", "rule": "대장주 위주로 매매한다", "detail": "섹터 내 거래대금 1위 + 상승률 1위가 대장주. 대장주가 가장 먼저 오르고, 가장 안전하다."},
            {"importance": "핵심", "rule": "끼 있는 종목만 매매한다", "detail": "끼 = 일봉 자리(신고가/전고점돌파/바닥반등) + 거래대금 증가 + 외인/기관 수급. 셋 중 하나라도 빠지면 끼가 부족."},
            {"importance": "핵심", "rule": "일봉 4대 자리 확인 필수", "detail": "신고가(최강) > 전고점돌파 > 바닥반등 > 빈집. 일봉 자리가 나쁘면 분봉이 좋아도 매수하지 않는다."},
            {"importance": "핵심", "rule": "피해야 할 종목 7가지", "detail": "잡주(시총5000억미만) / 뉴스빵(비주도섹터) / 끼소진(거래량감소) / 가분수(과열) / 3파동(늦은진입) / 깊은눌림(50%+) / 비주도섹터"},
        ],
    },
    {
        "id": "trading_methods",
        "title": "매매 기법",
        "icon": "zap",
        "rules": [
            {"importance": "핵심", "rule": "돌파 매매 (시총5000억+기관50~200억)", "detail": "전고점을 거래량 동반하며 돌파할 때 진입. 20일 검증: 시총5000억+기관50~200억 조건 시 돌파 WR 59.3% 합계 +84.32%. 오전 9:30~11시가 최적."},
            {"importance": "핵심", "rule": "눌림 매매 (95%깊이+오전거래량 필터)", "detail": "95%깊이(5%하락 이상) + 오전거래량 중간값 이상 조건 적용. 기존 53건 WR41.5% -10.99% → 5건 WR40% +1.23%. 나쁜 눌림 48건을 제거하여 전체 수익 +84.61% → +96.83% (+12.22%). 눌림 자체가 수익원이 아니라, 나쁜 눌림 차단이 핵심."},
            {"importance": "중요", "rule": "상따(상한가 따라잡기)", "detail": "주도주가 상한가 근접할 때 소량으로 진입. 상한가 직전 호가창에 매수 잔량이 쌓이는지 확인. 리스크 높으므로 소량만."},
            {"importance": "핵심", "rule": "갭상승 시초가 매수 금지", "detail": "20일 백테스트 결과: 갭상승 2%+ 종목 시초가 매수 시 승률 26%, 평균 -1.83%. 갭이 클수록 손실 커짐. 갭하락 반등매매가 통계적으로 유리."},
            {"importance": "중요", "rule": "D+1 매매 (눌림만)", "detail": "전일 상한가·급등 종목의 다음날, 갭상승을 추격하지 않고 눌림 시 전일종가 지지 확인 후 진입. 전일 상한가 다음날 시초가→종가 평균 -4.22%."},
            {"importance": "참고", "rule": "D+2 매매", "detail": "2일 연속 강세 종목 3일차 시초 진입. 2일 연속 양봉 + 거래량 유지 확인 필수. 3일차부터 위험도 증가."},
            {"importance": "핵심", "rule": "분할매수 체계", "detail": "1차 50%(시그널 확인) → 2차 30%(방향 확인) → 3차 20%(추세 확인). 한 번에 올인하지 않는다."},
        ],
    },
    {
        "id": "time_strategy",
        "title": "시간대 전략",
        "icon": "clock",
        "rules": [
            {"importance": "핵심", "rule": "장전 루틴 (8:30~9:00)", "detail": "전일 복기 + 관심종목 5~10개 + 야간선물/미국장 확인 + 전일 기관 순매수 50~200억 종목 리스트업. 기관수급이 돌파매매 승률의 핵심 필터."},
            {"importance": "핵심", "rule": "9:00~9:30 관망", "detail": "변동성이 가장 큰 시간대. 이 시간에 매매하면 손실 확률 70%. 주도 섹터 확정(거래대금 모니터링)만 진행한다."},
            {"importance": "핵심", "rule": "9:30~11:00 돌파 매매 (골든타임)", "detail": "하루 수익의 70%가 이 시간대에서 나온다. 주도 섹터 대장주의 전고점 돌파를 노린다. 최고의 매매 시간."},
            {"importance": "중요", "rule": "11:00~13:00 점심 관망", "detail": "거래량 급감 시간대. 매매하더라도 소량 눌림 매매만. 이 시간에 큰 비중을 실으면 오후에 고통받는다."},
            {"importance": "핵심", "rule": "13:00~14:30 오후 눌림 매매", "detail": "오전 강세 종목이 눌림을 준 후 재상승하는 구간. 오전 돌파 종목의 눌림 자리를 노린다."},
            {"importance": "중요", "rule": "14:30~15:20 동시호가·마감", "detail": "신규 진입보다 D+1 후보 종목 선정에 집중. 마감 동시호가 매수는 리스크가 크므로 소량만."},
        ],
    },
    {
        "id": "risk_management",
        "title": "리스크 관리",
        "icon": "shield",
        "rules": [
            {"importance": "핵심", "rule": "손절: 전저점 이탈 또는 -4%", "detail": "손절은 선택이 아니라 의무. 전저점 이탈 시 추세 전환 시그널이므로 반드시 매도. -4%는 절대 손절선."},
            {"importance": "핵심", "rule": "1차 익절(70%): +3~5%", "detail": "수익 구간에서 70%를 먼저 확보. 남은 30%로 추가 상승을 노린다. 익절 없이 홀딩하면 수익이 증발한다."},
            {"importance": "핵심", "rule": "2차 본전컷(30%): 원가 복귀 시", "detail": "분할 매도 후 남은 30%가 원가 근처로 돌아오면 전량 매도. 수익을 줬다 뺏기지 않는 원칙."},
            {"importance": "핵심", "rule": "한 종목 최대 30% 비중", "detail": "아무리 확신이 있어도 30% 초과 금지. 한 종목 집중은 한 번의 손절로 큰 손실을 초래한다."},
            {"importance": "핵심", "rule": "하루 손실 한도 -2%", "detail": "-2% 도달 시 당일 매매 즉시 종료. 손실이 커지면 판단력이 흐려지고 보복 매매로 이어진다."},
            {"importance": "핵심", "rule": "2연속 손절 시 당일 중단", "detail": "2번 연속 손절은 시장과 맞지 않다는 시그널. 더 매매하면 손실만 커진다."},
            {"importance": "중요", "rule": "강세장/약세장 비중 조절", "detail": "강세장(코스닥 20일선 위): 총 비중 60~70%. 약세장(20일선 아래): 20~30%. 시장을 이기려 하지 않는다."},
            {"importance": "핵심", "rule": "물타기 절대 금지", "detail": "손절 후 같은 종목 재진입은 새로운 시그널이 있을 때만. 물타기는 손실을 키우는 가장 빠른 방법."},
            {"importance": "중요", "rule": "월 수익 30% 인출", "detail": "수익의 30%는 반드시 인출. 증거금이 커지면 비중 감각이 무뎌지고 큰 손실로 이어진다."},
        ],
    },
    {
        "id": "minute_patterns",
        "title": "분봉 패턴 거르기",
        "icon": "eye-off",
        "rules": [
            {"importance": "핵심", "rule": "뉴스빵 패턴", "detail": "비주도 섹터에서 단발성 뉴스로 급등하는 종목. 뉴스 나온 직후 고점을 찍고 하락하는 경우가 대부분. 주도 섹터가 아니면 절대 매수 금지."},
            {"importance": "핵심", "rule": "깊은 눌림 (50%+ 되돌림)", "detail": "상승분의 50% 이상을 되돌린 종목은 추세가 약하다는 뜻. 30% 이내 눌림만 건강한 눌림으로 판단."},
            {"importance": "핵심", "rule": "끼 소진 패턴", "detail": "거래량이 점점 줄고, 상승폭도 줄어드는 종목. 더 이상 새로운 매수세가 들어오지 않는다는 뜻. 이런 종목은 언제든 급락 가능."},
            {"importance": "핵심", "rule": "3파동 완성", "detail": "상승 → 눌림 → 상승 → 눌림 → 상승 (3번째 상승) 이후에는 진입하지 않는다. 이미 충분히 올랐으므로 하락 전환 가능성 높다."},
            {"importance": "핵심", "rule": "가분수 패턴", "detail": "연속 양봉(3개 이상) + 거래량 폭발(평소 5배 이상). 과열 시그널이므로 보유 중이면 즉시 매도. 신규 진입 금지."},
            {"importance": "핵심", "rule": "최대거래량 윗꼬리 음봉", "detail": "당일 최대거래량 봉이 윗꼬리 긴 음봉이면 매도세가 강하다는 뜻. 보유 중이면 매도, 미보유면 진입 금지."},
            {"importance": "중요", "rule": "거래량 없는 허매수", "detail": "가격은 오르는데 거래량이 평소보다 적은 경우. 실질적 매수세가 아닌 허매수이므로 곧 하락 전환된다."},
        ],
    },
    {
        "id": "market_judgment",
        "title": "시장 판단",
        "icon": "bar-chart",
        "rules": [
            {"importance": "핵심", "rule": "주도 섹터 1~2개만 매매", "detail": "하루에 진짜 돈이 되는 섹터는 1~2개. 여러 섹터를 동시에 매매하면 집중력이 분산되고 수익률이 떨어진다."},
            {"importance": "핵심", "rule": "4~5개 섹터 분산 시 관망", "detail": "시장 자금이 여러 섹터로 분산되면 어떤 섹터도 확실하게 움직이지 않는다. 이런 날은 매매 자제."},
            {"importance": "핵심", "rule": "코스닥 20일선 체크", "detail": "코스닥 지수가 20일 이동평균선 아래면 약세장. 비중을 20~30%로 줄이고, 손절을 더 빠르게 한다."},
            {"importance": "중요", "rule": "코스닥 거래대금 기준", "detail": "5조 이하: 거래 부진 → 관망 / 7조: 보통 → 선별 매매 / 10조 이상: 활발 → 적극 매매. 거래대금이 유동성의 척도."},
            {"importance": "참고", "rule": "프로그램 매매 흐름", "detail": "프로그램 순매수가 지속되면 지수 상승 동력. 순매도 전환 시 하락 주의. 장중 프로그램 매매 현황 수시 확인."},
            {"importance": "중요", "rule": "야간선물 확인", "detail": "야간선물 -1% 이상 하락 시 장 초반 하락 가능성 높음. 이때는 9시 매매를 피하고 9:30 이후 추세 확인 후 진입."},
        ],
    },
    {
        "id": "psychology",
        "title": "심리/습관",
        "icon": "brain",
        "rules": [
            {"importance": "핵심", "rule": "매일 복기 (오답노트)", "detail": "장 마감 후 30분간 오늘 매매를 복기. 진입 근거, 청산 근거, 실수를 기록. 같은 실수를 반복하지 않는 유일한 방법."},
            {"importance": "핵심", "rule": "손익 가리기", "detail": "매매 중 평가손익을 보지 않는다. 평가손익을 보면 감정이 개입되어 원칙대로 매매할 수 없다. 차트와 원칙만 보고 매매."},
            {"importance": "핵심", "rule": "보복 매매 금지", "detail": "손절 후 바로 다시 매수하는 것은 보복 매매. 감정이 앞서면 판단력이 0이 된다. 손절 후 최소 30분 쉬고 새 시그널을 기다린다."},
            {"importance": "중요", "rule": "확신 없으면 쉰다", "detail": "매매 안 하는 것도 실력. 애매한 자리에서 진입하면 100번 중 60번은 손실. 확실한 자리만 매매해도 충분히 수익."},
            {"importance": "중요", "rule": "장 마감 후 복기 루틴", "detail": "15:30~16:00 복기 시간 고정. ① 오늘 매매 건수 ② 승률 ③ 최고/최악 매매 ④ 원칙 위반 여부 ⑤ 내일 관심종목 정리."},
        ],
    },
]


@router.get("/trading/strategy-guide")
async def get_strategy_guide():
    """홍인기 전략 가이드 - 7개 섹션 상세 매매 원칙."""
    return STRATEGY_GUIDE_SECTIONS


# ── 홍인기 성과 대시보드 API ──────────────────────────────


def _decimal_to_float(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


@router.get("/trading/performance")
async def get_hong_performance():
    """홍인기 전략 일별/주별 성과 + 요약 통계."""
    try:
        with get_session() as session:
            rows = session.execute(text("""
                SELECT
                    DATE(traded_at) AS trade_date,
                    SUM(pnl) AS total_pnl,
                    COUNT(*) AS trade_count,
                    COUNT(CASE WHEN pnl > 0 THEN 1 END) AS win_count
                FROM live_trades
                WHERE strategy_name LIKE '홍스타일%'
                  AND side = 'SELL'
                GROUP BY DATE(traded_at)
                ORDER BY trade_date
            """)).fetchall()

        if not rows:
            return {
                "daily": [],
                "weekly": [],
                "summary": {
                    "total_pnl": 0,
                    "total_trades": 0,
                    "win_rate": 0,
                    "avg_daily_pnl": 0,
                    "best_day_pnl": 0,
                    "worst_day_pnl": 0,
                    "win_days": 0,
                    "loss_days": 0,
                    "trading_days": 0,
                    "projected_monthly": 0,
                },
            }

        # 일별 데이터
        daily = []
        cumulative = 0.0
        total_pnl = 0.0
        total_trades = 0
        total_wins = 0
        best_day = -float("inf")
        worst_day = float("inf")
        win_days = 0
        loss_days = 0

        for row in rows:
            day_pnl = _decimal_to_float(row[1])
            trade_count = int(row[2])
            win_count = int(row[3])
            cumulative += day_pnl
            total_pnl += day_pnl
            total_trades += trade_count
            total_wins += win_count

            if day_pnl > best_day:
                best_day = day_pnl
            if day_pnl < worst_day:
                worst_day = day_pnl
            if day_pnl > 0:
                win_days += 1
            elif day_pnl < 0:
                loss_days += 1

            daily.append({
                "date": str(row[0]),
                "pnl": round(day_pnl),
                "cumulative": round(cumulative),
                "trades": trade_count,
                "wins": win_count,
                "win_rate": round(win_count / trade_count * 100, 1) if trade_count > 0 else 0,
            })

        # 주별 데이터
        weekly_map: dict[str, dict] = defaultdict(
            lambda: {"pnl": 0.0, "trades": 0, "wins": 0}
        )
        for d in daily:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            week_start = dt - timedelta(days=dt.weekday())
            week_key = week_start.strftime("%Y-%m-%d")
            weekly_map[week_key]["pnl"] += d["pnl"]
            weekly_map[week_key]["trades"] += d["trades"]
            weekly_map[week_key]["wins"] += d["wins"]

        weekly = []
        for week_key in sorted(weekly_map.keys()):
            w = weekly_map[week_key]
            weekly.append({
                "week_start": week_key,
                "pnl": round(w["pnl"]),
                "trades": w["trades"],
                "wins": w["wins"],
                "win_rate": round(w["wins"] / w["trades"] * 100, 1) if w["trades"] > 0 else 0,
            })

        trading_days = len(daily)
        avg_daily_pnl = total_pnl / trading_days if trading_days > 0 else 0
        win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0

        summary = {
            "total_pnl": round(total_pnl),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 1),
            "avg_daily_pnl": round(avg_daily_pnl),
            "best_day_pnl": round(best_day) if best_day != -float("inf") else 0,
            "worst_day_pnl": round(worst_day) if worst_day != float("inf") else 0,
            "win_days": win_days,
            "loss_days": loss_days,
            "trading_days": trading_days,
            "projected_monthly": round(avg_daily_pnl * 22),
        }

        return {"daily": daily, "weekly": weekly, "summary": summary}

    except Exception as e:
        logger.error(f"홍인기 성과 조회 실패: {e}")
        return {
            "daily": [],
            "weekly": [],
            "summary": {
                "total_pnl": 0,
                "total_trades": 0,
                "win_rate": 0,
                "avg_daily_pnl": 0,
                "best_day_pnl": 0,
                "worst_day_pnl": 0,
                "win_days": 0,
                "loss_days": 0,
                "trading_days": 0,
                "projected_monthly": 0,
            },
        }
