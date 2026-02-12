"""홍인기 매매법 통합 분석 엔진"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from src.analysis.theme_analyzer import get_theme_analyzer, ThemeAnalysis
from src.analysis.stock_analyzer import get_stock_analyzer

from .sector_analyzer import SectorAnalyzer, SectorInfo
from .daily_chart_analyzer import DailyChartAnalyzer, DailyPosition, KiScore
from .pattern_detector import PatternDetector, PatternAlert
from .signal_generator import (
    SignalGenerator,
    EntrySignal,
    ExitSignal,
    DPlusCandidate,
)


# 홍인기 매매 원칙 (~50개, 8개 카테고리)
TRADING_RULES = [
    # ── 종목 선정 ──
    {"id": 1, "rule": "거래대금 상위 20 종목에서만 매매한다", "category": "종목선정", "importance": "핵심"},
    {"id": 2, "rule": "대장주 위주로 매매한다 (섹터 내 거래대금·상승률 1위)", "category": "종목선정", "importance": "핵심"},
    {"id": 3, "rule": "시가총액 5000억 이상 종목만 매매한다 (20일 백테스트: WR 51.7% +14.89%)", "category": "종목선정", "importance": "핵심"},
    {"id": 4, "rule": "전일 기관 순매수 50~200억 종목 우선 (20일 백테스트: WR 56.1% +76.60%)", "category": "종목선정", "importance": "핵심"},
    {"id": 5, "rule": "끼 있는 종목만 매매한다 (일봉 자리 + 거래대금 + 수급)", "category": "종목선정", "importance": "핵심"},
    {"id": 6, "rule": "시총별 비중 조절 - 소형주 1억, 중형주 5억, 대형주 30억", "category": "종목선정", "importance": "중요"},
    {"id": 7, "rule": "피해야 할 종목 6가지: 뉴스빵/끼소진/가분수/3파동/깊은눌림/비주도", "category": "종목선정", "importance": "핵심"},
    {"id": 8, "rule": "일봉 자리를 반드시 확인한다 (신고가/전고점돌파/바닥반등/빈집)", "category": "종목선정", "importance": "핵심"},
    {"id": 9, "rule": "잡주(시총 5000억 미만 소형주) 돌파매매 금지 - 급등 후 급락 패턴", "category": "종목선정", "importance": "핵심"},

    # ── 매매 기법 ──
    {"id": 10, "rule": "돌파 매매: 전고점 돌파 시 거래량 확인 후 진입 (시총5000억+기관50~200억: WR 59.3%)", "category": "매매기법", "importance": "핵심"},
    {"id": 11, "rule": "눌림 매매: 상승 후 되돌림 시 지지선에서 진입", "category": "매매기법", "importance": "핵심"},
    {"id": 12, "rule": "상따(상한가 따라잡기): 주도주 상한가 근접 시 소량 진입", "category": "매매기법", "importance": "중요"},
    {"id": 13, "rule": "D+1 매매: 전일 상한가·급등주 다음날 눌림 시 진입 (갭상승 추격 금지)", "category": "매매기법", "importance": "중요"},
    {"id": 14, "rule": "D+2 매매: 2일 연속 강세 종목 3일차 시초 진입", "category": "매매기법", "importance": "참고"},
    {"id": 15, "rule": "분할매수: 1차 50% → 확인 후 2차 30% → 추가 20%", "category": "매매기법", "importance": "핵심"},
    {"id": 16, "rule": "갭상승 시초가 매수 금지: 승률 26%, 평균 -1.83% (20일 백테스트 검증)", "category": "매매기법", "importance": "핵심"},

    # ── 시간대 전략 ──
    {"id": 17, "rule": "장전 루틴: 8:30~9:00 전일 복기 + 당일 관심종목 + 전일 기관수급 확인", "category": "시간대전략", "importance": "핵심"},
    {"id": 18, "rule": "9:00~9:30 관망: 변동성 큰 시간대, 주도 섹터 확정만 진행", "category": "시간대전략", "importance": "핵심"},
    {"id": 19, "rule": "9:30~11:00 돌파 매매 시간대 (오전 골든타임)", "category": "시간대전략", "importance": "핵심"},
    {"id": 20, "rule": "11:00~13:00 점심시간 관망 또는 소량 눌림 매매만", "category": "시간대전략", "importance": "중요"},
    {"id": 21, "rule": "13:00~14:30 오후 눌림 매매 시간대", "category": "시간대전략", "importance": "핵심"},
    {"id": 22, "rule": "14:30~15:20 동시호가 관망 또는 D+1 후보 선정만", "category": "시간대전략", "importance": "중요"},
    {"id": 23, "rule": "돌파 매매는 반드시 오전에, 눌림 매매는 오후에 한다", "category": "시간대전략", "importance": "핵심"},

    # ── 리스크 관리 ──
    {"id": 24, "rule": "손절은 전저점 이탈 또는 -4% (절대 원칙)", "category": "리스크관리", "importance": "핵심"},
    {"id": 25, "rule": "1차 익절(70%)은 +3~5%에서 한다", "category": "리스크관리", "importance": "핵심"},
    {"id": 26, "rule": "2차 본전컷(30%)은 원가 복귀 시 전량 매도", "category": "리스크관리", "importance": "핵심"},
    {"id": 27, "rule": "비중은 최대 30%를 넘지 않는다 (한 종목 집중 금지)", "category": "리스크관리", "importance": "핵심"},
    {"id": 28, "rule": "하루 손실 한도 -2% 도달 시 당일 매매 종료", "category": "리스크관리", "importance": "핵심"},
    {"id": 29, "rule": "2연속 손절 시 당일 매매 중단", "category": "리스크관리", "importance": "핵심"},
    {"id": 30, "rule": "강세장 비중 60-70%, 약세장 비중 20-30%", "category": "리스크관리", "importance": "중요"},
    {"id": 31, "rule": "물타기 절대 금지 - 손절 후 재진입은 새 시그널 필요", "category": "리스크관리", "importance": "핵심"},
    {"id": 32, "rule": "수익 인출: 월 수익의 30%는 반드시 인출", "category": "리스크관리", "importance": "중요"},

    # ── 분봉 패턴 거르기 ──
    {"id": 33, "rule": "비주도 섹터 뉴스빵은 절대 진입하지 않는다", "category": "분봉패턴", "importance": "핵심"},
    {"id": 34, "rule": "50% 이상 깊은 눌림(되돌림)은 진입하지 않는다", "category": "분봉패턴", "importance": "핵심"},
    {"id": 35, "rule": "끼 소진 종목(거래량 감소 + 상승폭 축소)은 매매하지 않는다", "category": "분봉패턴", "importance": "핵심"},
    {"id": 36, "rule": "3파동 완성 후(상승3번 반복)에는 진입하지 않는다", "category": "분봉패턴", "importance": "핵심"},
    {"id": 37, "rule": "가분수 패턴(연속양봉+거래량폭발)은 즉시 매도한다", "category": "분봉패턴", "importance": "핵심"},
    {"id": 38, "rule": "최대거래량 윗꼬리 음봉은 매도 시그널이다", "category": "분봉패턴", "importance": "핵심"},
    {"id": 39, "rule": "거래량 없는 상승(허매수)은 진입하지 않는다", "category": "분봉패턴", "importance": "중요"},

    # ── 시장 판단 ──
    {"id": 40, "rule": "주도 섹터만 매매한다 (당일 1~2개 섹터)", "category": "시장판단", "importance": "핵심"},
    {"id": 41, "rule": "4~5개 섹터 분산 시 매매 자제 (주도주 불분명)", "category": "시장판단", "importance": "핵심"},
    {"id": 42, "rule": "코스닥 20일선 이하이면 비중 축소 (약세장)", "category": "시장판단", "importance": "핵심"},
    {"id": 43, "rule": "코스닥 거래대금 기준: 5조 이하 관망, 7조 보통, 10조+ 적극", "category": "시장판단", "importance": "중요"},
    {"id": 44, "rule": "프로그램 매매 순매수/순매도 흐름 확인", "category": "시장판단", "importance": "참고"},
    {"id": 45, "rule": "야간선물 -1% 이상 하락 시 장초반 관망", "category": "시장판단", "importance": "중요"},
    {"id": 46, "rule": "9:20~9:50에 주도 섹터를 확정한다", "category": "시장판단", "importance": "핵심"},

    # ── 심리/습관 ──
    {"id": 47, "rule": "매일 복기한다 (오답노트 작성 필수)", "category": "심리습관", "importance": "핵심"},
    {"id": 48, "rule": "손익 가리기: 평가손익 보지 않고 원칙대로 매매", "category": "심리습관", "importance": "핵심"},
    {"id": 49, "rule": "보복 매매 금지: 손절 후 즉시 재진입 하지 않는다", "category": "심리습관", "importance": "핵심"},
    {"id": 50, "rule": "확신 없으면 쉰다 - 매매 안 하는 것도 실력이다", "category": "심리습관", "importance": "중요"},
    {"id": 51, "rule": "장 마감 후 30분 복기 루틴: 진입/청산 근거 기록", "category": "심리습관", "importance": "중요"},
]


@dataclass
class StockAnalysisResult:
    """개별 종목 분석 결과"""
    code: str
    name: str
    daily_position: DailyPosition
    ki_score: KiScore
    patterns: list[PatternAlert]
    entry_signal: EntrySignal
    is_leader: bool


@dataclass
class AnalysisResult:
    """전체 분석 결과"""
    timestamp: datetime
    market_condition: dict
    leading_sectors: list[SectorInfo]
    leader_stocks: list[dict]
    stock_analyses: list[StockAnalysisResult]
    signals: list[EntrySignal]
    pattern_alerts: list[PatternAlert]
    d_plus_candidates: list[DPlusCandidate]
    trading_rules: dict
    is_caution_day: bool


class HongStyleEngine:
    """홍인기 매매법 통합 분석 엔진"""

    def __init__(self):
        self.sector_analyzer = SectorAnalyzer()
        self.daily_chart_analyzer = DailyChartAnalyzer()
        self.pattern_detector = PatternDetector()
        self.signal_generator = SignalGenerator()

    async def run_analysis(
        self,
        theme_data: Optional[list] = None,
        top_stocks: Optional[list[dict]] = None,
    ) -> AnalysisResult:
        """
        전체 분석 파이프라인:
        1. 테마 데이터 가져오기
        2. 주도 섹터 분석
        3. 대장주 선별
        4. 각 대장주의 일봉 자리 분석
        5. 위험 패턴 감지
        6. 시그널 생성
        """
        try:
            # 1. 테마 데이터 (없으면 theme_analyzer에서 가져오기)
            if theme_data is None:
                try:
                    analyzer = get_theme_analyzer()
                    market = await analyzer.get_market_analysis()
                    theme_data = market.hot_themes
                except Exception as e:
                    logger.warning(f"테마 데이터 조회 실패: {e}")
                    theme_data = []

            # 2. 주도 섹터 분석
            leading_sectors = await self.sector_analyzer.analyze_leading_sectors(
                theme_data=theme_data,
                stock_prices=top_stocks,
            )

            # 매매 자제일 판단
            is_caution = self.sector_analyzer.is_caution_day(leading_sectors)

            # 3. 대장주 선별
            leader_stocks: list[dict] = []
            for sector in leading_sectors[:2]:  # 상위 2개 섹터
                leader = self.sector_analyzer.detect_leader_stocks(
                    sector.top_stocks
                )
                if leader:
                    leader_stocks.append(leader)

            # 4~6. 각 대장주 분석 (병렬 처리)
            stock_analyses: list[StockAnalysisResult] = []
            all_patterns: list[PatternAlert] = []
            all_signals: list[EntrySignal] = []

            if leader_stocks:
                tasks = [
                    self._analyze_single_stock(stock, leader_stocks)
                    for stock in leader_stocks
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"종목 분석 실패: {result}")
                        continue
                    if result:
                        stock_analyses.append(result)
                        all_patterns.extend(result.patterns)
                        all_signals.append(result.entry_signal)

            # 시장 상태
            market_condition = self.get_market_condition(
                leading_sectors, is_caution
            )

            # 매매 원칙 체크리스트
            trading_rules = self.get_trading_rules_status(
                leading_sectors=leading_sectors,
                is_caution=is_caution,
                patterns=all_patterns,
            )

            return AnalysisResult(
                timestamp=datetime.now(),
                market_condition=market_condition,
                leading_sectors=leading_sectors,
                leader_stocks=leader_stocks,
                stock_analyses=stock_analyses,
                signals=all_signals,
                pattern_alerts=all_patterns,
                d_plus_candidates=[],
                trading_rules=trading_rules,
                is_caution_day=is_caution,
            )

        except Exception as e:
            logger.error(f"홍인기 분석 실패: {e}")
            return AnalysisResult(
                timestamp=datetime.now(),
                market_condition={"status": "error", "message": str(e)},
                leading_sectors=[],
                leader_stocks=[],
                stock_analyses=[],
                signals=[],
                pattern_alerts=[],
                d_plus_candidates=[],
                trading_rules={},
                is_caution_day=True,
            )

    async def _analyze_single_stock(
        self,
        stock: dict,
        leader_stocks: list[dict],
    ) -> Optional[StockAnalysisResult]:
        """개별 종목 분석"""
        code = stock.get("code", "")
        name = stock.get("name", code)

        try:
            # 일봉 데이터 조회
            stock_analyzer = get_stock_analyzer()
            daily_df = await stock_analyzer.get_ohlcv(code, days=120)

            if daily_df.empty:
                return None

            # 일봉 자리 분류
            daily_position = self.daily_chart_analyzer.classify_daily_position(
                daily_df
            )

            # 끼 계산
            ki_score = self.daily_chart_analyzer.calculate_ki(daily_df)

            # 대장주 여부
            is_leader = code in {s.get("code", "") for s in leader_stocks}

            # 위험 패턴 감지 (분봉 데이터 없이 일봉만으로 일부 분석)
            patterns = self.pattern_detector.detect_all_patterns(
                minute_bars=None,
                daily_bars=daily_df,
                ki_score=ki_score.score,
                is_leading_sector=True,
            )

            # 시그널 생성
            entry_signal = self.signal_generator.generate_entry_signal(
                stock_code=code,
                daily_position=daily_position,
                ki_score=ki_score,
                patterns=patterns,
                is_leader=is_leader,
            )

            return StockAnalysisResult(
                code=code,
                name=name,
                daily_position=daily_position,
                ki_score=ki_score,
                patterns=patterns,
                entry_signal=entry_signal,
                is_leader=is_leader,
            )

        except Exception as e:
            logger.error(f"종목 분석 실패 ({code}): {e}")
            return None

    async def get_dashboard_data(self) -> dict:
        """대시보드용 데이터 반환"""
        try:
            result = await self.run_analysis()

            return {
                "timestamp": result.timestamp.isoformat(),
                "market_condition": result.market_condition,
                "leading_sectors": [
                    {
                        "name": s.sector_name,
                        "trading_value": s.trading_value,
                        "stock_count": s.stock_count,
                        "avg_change_rate": s.avg_change_rate,
                        "leader": s.leader_stock,
                    }
                    for s in result.leading_sectors[:3]
                ],
                "leader_stocks": result.leader_stocks[:5],
                "signals": [
                    {
                        "code": sa.code,
                        "name": sa.name,
                        "action": sa.entry_signal.action,
                        "method": sa.entry_signal.method,
                        "confidence": sa.entry_signal.confidence,
                        "reason": sa.entry_signal.reason,
                        "daily_position": sa.daily_position.position_type,
                        "ki_score": sa.ki_score.score,
                    }
                    for sa in result.stock_analyses
                ],
                "pattern_alerts": [
                    {
                        "pattern": p.pattern_name,
                        "severity": p.severity,
                        "description": p.description,
                        "confidence": p.confidence,
                        "detected_at": p.detected_at.isoformat(),
                    }
                    for p in result.pattern_alerts
                ],
                "d_plus_candidates": [
                    {
                        "code": c.code,
                        "name": c.name,
                        "d_day": c.d_day,
                        "change_rate": c.change_rate,
                        "reason": c.reason,
                    }
                    for c in result.d_plus_candidates
                ],
                "trading_rules": result.trading_rules,
                "is_caution_day": result.is_caution_day,
            }

        except Exception as e:
            logger.error(f"대시보드 데이터 생성 실패: {e}")
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

    def get_market_condition(
        self,
        leading_sectors: list[SectorInfo],
        is_caution: bool,
    ) -> dict:
        """시장 상태 판단 (유동성/강세/약세)"""
        if is_caution:
            return {
                "status": "caution",
                "label": "매매 자제",
                "description": "주도 섹터 불분명 - 4개 이상 분산",
                "color": "yellow",
            }

        if not leading_sectors:
            return {
                "status": "unknown",
                "label": "분석 중",
                "description": "데이터 수집 중",
                "color": "gray",
            }

        top = leading_sectors[0]
        if top.stock_count >= 5 and top.avg_change_rate >= 4:
            return {
                "status": "strong",
                "label": "유동성 장세",
                "description": (
                    f"주도 섹터 [{top.sector_name}] 강세 "
                    f"({top.stock_count}종목 평균 +{top.avg_change_rate:.1f}%)"
                ),
                "color": "red",
            }

        if top.avg_change_rate >= 2:
            return {
                "status": "bullish",
                "label": "강세",
                "description": f"주도 섹터 [{top.sector_name}] 상승",
                "color": "green",
            }

        return {
            "status": "neutral",
            "label": "보통",
            "description": "뚜렷한 주도 섹터 없음",
            "color": "gray",
        }

    def get_trading_rules_status(
        self,
        leading_sectors: Optional[list[SectorInfo]] = None,
        is_caution: bool = False,
        patterns: Optional[list[PatternAlert]] = None,
    ) -> dict:
        """매매 원칙 체크리스트 상태"""
        rules_status: list[dict] = []
        patterns = patterns or []
        pattern_names = {p.pattern_name for p in patterns}

        for rule in TRADING_RULES:
            status = "unchecked"
            note = ""

            rid = rule["id"]

            if rid == 40:  # 주도 섹터만 매매
                if leading_sectors:
                    status = "pass"
                    note = f"주도 섹터: {leading_sectors[0].sector_name}"
                else:
                    status = "warning"
                    note = "주도 섹터 미확인"

            elif rid == 41:  # 섹터 분산
                if is_caution:
                    status = "fail"
                    note = "4개 이상 섹터 분산 - 매매 자제일"
                else:
                    status = "pass"

            elif rid == 33:  # 뉴스빵
                if "뉴스빵" in pattern_names:
                    status = "fail"
                    note = "비주도 섹터 뉴스 감지"
                else:
                    status = "pass"

            elif rid == 34:  # 깊은눌림
                if "깊은눌림" in pattern_names:
                    status = "fail"
                    note = "50%+ 되돌림 감지"
                else:
                    status = "pass"

            elif rid == 35:  # 끼소진
                if "끼소진" in pattern_names:
                    status = "fail"
                    note = "끼 소진 종목 감지"
                else:
                    status = "pass"

            elif rid == 36:  # 3파동
                if "3파동" in pattern_names:
                    status = "fail"
                    note = "3파동 완성 감지"
                else:
                    status = "pass"

            elif rid == 37:  # 가분수
                if "가분수" in pattern_names:
                    status = "fail"
                    note = "가분수 패턴 감지"
                else:
                    status = "pass"

            elif rid == 38:  # 거래량고점
                if "거래량고점" in pattern_names:
                    status = "fail"
                    note = "최대거래량 윗꼬리 음봉 감지"
                else:
                    status = "pass"

            elif rid == 46:  # 주도 섹터 확정 시간
                if self.sector_analyzer.is_confirmation_window():
                    status = "active"
                    note = "주도 섹터 확정 시간대 (9:20~9:50)"
                else:
                    status = "pass"

            rules_status.append({
                **rule,
                "status": status,
                "note": note,
            })

        passed = sum(1 for r in rules_status if r["status"] == "pass")
        failed = sum(1 for r in rules_status if r["status"] == "fail")
        total = len(rules_status)

        return {
            "rules": rules_status,
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "unchecked": total - passed - failed,
                "compliance_rate": round(passed / total * 100, 1) if total > 0 else 0,
            },
        }


# 싱글톤 패턴
_engine: Optional[HongStyleEngine] = None


def get_hongstyle_engine() -> HongStyleEngine:
    """홍인기 엔진 싱글톤"""
    global _engine
    if _engine is None:
        _engine = HongStyleEngine()
    return _engine
