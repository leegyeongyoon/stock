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
        }

        if not engine.hongstyle_runner:
            return ConvictionRankingResponse(
                ranking=[],
                top_n=5,
                max_positions=2,
                high_alloc_pct=0.50,
                low_alloc_pct=0.30,
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
            ranking=[], top_n=5, max_positions=2,
            high_alloc_pct=0.50, low_alloc_pct=0.30,
            algorithm={},
        )


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
