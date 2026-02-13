"""경윤 수정 매매법 API 라우트.

홍인기 전략에 3개 필터(시총/기관/눌림)를 추가한 별도 전략.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter
from loguru import logger
from sqlalchemy import text

from src.server.dependencies import get_engine
from src.database.connection import get_session

router = APIRouter(prefix="/api/gylee", tags=["gylee"])


# ── 트레이딩 제어 ──────────────────────────────────────


@router.post("/trading/start")
async def start_gylee_trading():
    """경윤 자동매매 시작."""
    try:
        engine = get_engine()
        result = await engine.start_gylee()
        return result
    except Exception as e:
        logger.error(f"경윤 자동매매 시작 실패: {e}")
        return {"success": False, "message": str(e)}


@router.post("/trading/stop")
async def stop_gylee_trading():
    """경윤 자동매매 중지."""
    try:
        engine = get_engine()
        result = await engine.stop_gylee()
        return result
    except Exception as e:
        logger.error(f"경윤 자동매매 중지 실패: {e}")
        return {"success": False, "message": str(e)}


@router.get("/trading/status")
async def get_gylee_trading_status():
    """경윤 자동매매 상태."""
    try:
        engine = get_engine()
        return engine.get_gylee_status()
    except Exception as e:
        logger.error(f"경윤 상태 조회 실패: {e}")
        return {"enabled": False, "state": "ERROR"}


@router.get("/trading/positions")
async def get_gylee_positions():
    """경윤 보유종목."""
    try:
        engine = get_engine()
        if not engine.gylee_runner:
            return []
        return engine.gylee_runner.get_hong_positions()
    except Exception as e:
        logger.error(f"경윤 포지션 조회 실패: {e}")
        return []


@router.get("/trading/trades")
async def get_gylee_trades():
    """경윤 오늘 거래 내역."""
    try:
        engine = get_engine()
        if not engine.gylee_runner:
            return []
        return engine.gylee_runner.get_hong_trades()
    except Exception as e:
        logger.error(f"경윤 거래 내역 조회 실패: {e}")
        return []


@router.get("/trading/events")
async def get_gylee_events():
    """경윤 최근 이벤트 로그."""
    try:
        engine = get_engine()
        if not engine.gylee_runner:
            return []
        return engine.gylee_runner.get_events(limit=50)
    except Exception as e:
        logger.error(f"경윤 이벤트 조회 실패: {e}")
        return []


@router.get("/trading/conviction")
async def get_gylee_conviction():
    """확신도 순위 + 필터 정보."""
    try:
        engine = get_engine()

        algorithm = {
            "name": "경윤 수정 매매법 (홍인기 + 3필터)",
            "steps": [
                {"step": 1, "title": "홍인기 분석", "desc": "주도 섹터/대장주/끼 점수 분석 (기존 동일)"},
                {"step": 2, "title": "시총 필터", "desc": "시가총액 5,000억 이상만 통과 (소형주 제거)"},
                {"step": 3, "title": "기관 필터", "desc": "전일 기관 순매수 50~200억 종목만 통과"},
                {"step": 4, "title": "눌림 필터", "desc": "95%깊이 + 오전거래량 조건 (나쁜 눌림 제거)"},
                {"step": 5, "title": "확신도 점수", "desc": "필터 통과 종목만 확신도 순위 매기기"},
                {"step": 6, "title": "집중 배분", "desc": "TOP 5 중 최대 2종목, 50%/30% 배분"},
            ],
            "filters": [
                {"name": "시총 5000억+", "effect": "WR 42%→52%, 합계 -151%→+15%"},
                {"name": "기관 50~200억", "effect": "WR 52%→57%, 합계 +15%→+85%"},
                {"name": "눌림 95%깊이", "effect": "53건→5건, 전체 +12% 개선"},
            ],
            "backtest": {
                "period": "20 거래일 (2026-01-16 ~ 2026-02-12)",
                "result": "207건 WR 60.4% 합계 +96.83%",
            },
        }

        if not engine.gylee_runner:
            return {
                "ranking": [],
                "top_n": 5,
                "max_positions": 2,
                "high_alloc_pct": 0.50,
                "low_alloc_pct": 0.30,
                "algorithm": algorithm,
            }

        runner = engine.gylee_runner
        ranking_data = runner.get_conviction_ranking()

        return {
            "ranking": ranking_data,
            "top_n": runner.TOP_N_ONLY,
            "max_positions": runner.MAX_POSITIONS,
            "high_alloc_pct": runner.HIGH_CONFIDENCE_PCT,
            "low_alloc_pct": runner.LOW_CONFIDENCE_PCT,
            "algorithm": algorithm,
        }
    except Exception as e:
        logger.error(f"경윤 확신도 순위 조회 실패: {e}")
        return {
            "ranking": [], "top_n": 5, "max_positions": 2,
            "high_alloc_pct": 0.50, "low_alloc_pct": 0.30,
            "algorithm": {},
        }


# ── 필터 현황 ──────────────────────────────────────────


@router.get("/trading/filters")
async def get_gylee_filters():
    """3개 필터 현황 (통과율, 데이터 날짜)."""
    try:
        engine = get_engine()
        if not engine.gylee_runner:
            return {"filters": [], "data_date": None}
        return engine.gylee_runner.get_filter_stats()
    except Exception as e:
        logger.error(f"경윤 필터 현황 조회 실패: {e}")
        return {"filters": [], "data_date": None, "error": str(e)}


# ── 성과 ──────────────────────────────────────────────


def _decimal_to_float(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


@router.get("/trading/performance")
async def get_gylee_performance():
    """경윤 전략 일별/주별 성과 + 요약 통계."""
    try:
        with get_session() as session:
            rows = session.execute(text("""
                SELECT
                    DATE(traded_at) AS trade_date,
                    SUM(pnl) AS total_pnl,
                    COUNT(*) AS trade_count,
                    COUNT(CASE WHEN pnl > 0 THEN 1 END) AS win_count
                FROM live_trades
                WHERE strategy_name LIKE '경윤%'
                  AND side = 'SELL'
                GROUP BY DATE(traded_at)
                ORDER BY trade_date
            """)).fetchall()

        if not rows:
            return {
                "daily": [],
                "weekly": [],
                "summary": {
                    "total_pnl": 0, "total_trades": 0, "win_rate": 0,
                    "avg_daily_pnl": 0, "best_day_pnl": 0, "worst_day_pnl": 0,
                    "win_days": 0, "loss_days": 0, "trading_days": 0,
                    "projected_monthly": 0,
                },
            }

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
        logger.error(f"경윤 성과 조회 실패: {e}")
        return {
            "daily": [], "weekly": [],
            "summary": {
                "total_pnl": 0, "total_trades": 0, "win_rate": 0,
                "avg_daily_pnl": 0, "best_day_pnl": 0, "worst_day_pnl": 0,
                "win_days": 0, "loss_days": 0, "trading_days": 0,
                "projected_monthly": 0,
            },
        }


# ── 전략 가이드 ──────────────────────────────────────────


GYLEE_STRATEGY_GUIDE = [
    {
        "id": "filter_system",
        "title": "3대 필터 시스템",
        "icon": "filter",
        "rules": [
            {
                "importance": "핵심",
                "rule": "시가총액 5,000억 이상 필터",
                "detail": "20일 검증: 무필터 WR 42% -151% → 시총5000억+ WR 52% +15%. 소형주는 돌파 후 급락 패턴. 시총 5000억 이상만 체계적으로 수익.",
            },
            {
                "importance": "핵심",
                "rule": "전일 기관 순매수 50~200억 필터",
                "detail": "20일 검증: 시총5000억+기관50~200억 = WR 57% +85%. 기관이 매수한 종목은 돌파 후 관성 유지. 200억 초과는 이미 과열.",
            },
            {
                "importance": "핵심",
                "rule": "눌림 95%깊이 + 오전거래량 필터",
                "detail": "기존 53건 WR41.5% -11% → 5건 WR40% +1.2%. 나쁜 눌림 48건 제거로 전체 수익 +12% 개선. 눌림매매는 거의 차단하고 돌파매매에 집중.",
            },
        ],
    },
    {
        "id": "backtest_results",
        "title": "20일 백테스트 검증 결과",
        "icon": "bar-chart",
        "rules": [
            {
                "importance": "핵심",
                "rule": "최종 성과: 207건 WR 60.4% +96.83%",
                "detail": "무필터(250건 WR42% -151%) → 시총5000억+(298건 WR52% +15%) → +기관50~200억(255건 WR57% +85%) → +눌림필터(207건 WR60% +97%)",
            },
            {
                "importance": "핵심",
                "rule": "돌파매매: 202건 WR 60.9% +95.60%",
                "detail": "전체 수익의 98.7%가 돌파매매에서 발생. 눌림매매는 5건 WR40% +1.23%로 비중 미미.",
            },
            {
                "importance": "중요",
                "rule": "필터별 단계적 개선 확인",
                "detail": "각 필터가 독립적으로 승률을 올림. 시총 필터만으로 +10%p, 기관 필터 추가로 +5%p, 눌림 필터 추가로 +3%p.",
            },
        ],
    },
    {
        "id": "vs_original",
        "title": "원본 홍인기 전략 vs 경윤 수정",
        "icon": "git-compare",
        "rules": [
            {
                "importance": "핵심",
                "rule": "원본: 필터 없음 → WR 42%, -151%",
                "detail": "홍인기 매매법의 분석/시그널 로직은 우수하지만, 소형주와 기관 미매수 종목 포함으로 전체 성과 저하.",
            },
            {
                "importance": "핵심",
                "rule": "수정: 3필터 적용 → WR 60.4%, +96.83%",
                "detail": "동일한 분석 로직에 3개 필터만 추가하여 승률 +18%p, 수익 +248% 개선. 진입 종목 수는 줄지만 질적 개선.",
            },
            {
                "importance": "중요",
                "rule": "공유 요소: SL/TP, 확신도, 포지션 사이징",
                "detail": "손절 -4%, 익절 +5%(70%), 본전컷, 2연속손절 중단 등 리스크 관리는 동일. 변경된 건 진입 필터만.",
            },
        ],
    },
]


@router.get("/strategy-guide")
async def get_gylee_strategy_guide():
    """경윤 전략 가이드."""
    return GYLEE_STRATEGY_GUIDE


# ── DD 전략 (데이터드리븐 전략1+3) ─────────────────────


@router.post("/dd/start")
async def start_dd_trading():
    """DD 전략 자동매매 시작."""
    try:
        engine = get_engine()
        result = await engine.start_dd()
        return result
    except Exception as e:
        logger.error(f"DD 전략 시작 실패: {e}")
        return {"success": False, "message": str(e)}


@router.post("/dd/stop")
async def stop_dd_trading():
    """DD 전략 자동매매 중지."""
    try:
        engine = get_engine()
        result = await engine.stop_dd()
        return result
    except Exception as e:
        logger.error(f"DD 전략 중지 실패: {e}")
        return {"success": False, "message": str(e)}


@router.get("/dd/status")
async def get_dd_status():
    """DD 전략 상태."""
    try:
        engine = get_engine()
        return engine.get_dd_status()
    except Exception as e:
        logger.error(f"DD 상태 조회 실패: {e}")
        return {"enabled": False}


@router.get("/dd/events")
async def get_dd_events():
    """DD 전략 이벤트 로그."""
    try:
        engine = get_engine()
        if not engine.dd_runner:
            return []
        return engine.dd_runner.get_events(limit=50)
    except Exception as e:
        logger.error(f"DD 이벤트 조회 실패: {e}")
        return []


@router.get("/dd/trades")
async def get_dd_trades():
    """DD 전략 오늘 거래."""
    try:
        engine = get_engine()
        if not engine.dd_runner:
            return []
        return engine.dd_runner.get_trades()
    except Exception as e:
        logger.error(f"DD 거래 조회 실패: {e}")
        return []
