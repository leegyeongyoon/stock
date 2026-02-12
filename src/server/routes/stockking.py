"""홍인기 매매법 대시보드 API 라우트"""

import time as time_module
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from loguru import logger

from src.strategies.hongstyle.hongstyle_engine import (
    get_hongstyle_engine,
    AnalysisResult,
    TRADING_RULES,
)
from src.strategies.hongstyle.daily_chart_analyzer import DailyChartAnalyzer
from src.analysis.stock_analyzer import get_stock_analyzer


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
