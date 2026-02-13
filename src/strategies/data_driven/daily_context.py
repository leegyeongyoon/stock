"""일별 컨텍스트 로더 - 홍인기 필터용 일별 데이터 (시총/기관/끼/일봉자리/거래대금)

DB 테이블:
  - ohlcv_daily: value (거래대금), change_rate (등락률)
  - investor_trading: institution_buy, institution_sell (기관 순매수)
  - stocks: market_cap (시가총액)

DailyChartAnalyzer: classify_daily_position(), calculate_ki() 재사용
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Union

import pandas as pd
from sqlalchemy import text

from src.database.connection import get_backtest_engine
from src.strategies.hongstyle.daily_chart_analyzer import DailyChartAnalyzer
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class StockDailyContext:
    code: str
    trade_date: date
    market_cap_bil: float           # 시총 (억원)
    inst_net_buy_bil: Optional[float]  # 기관 순매수 (억원), None=데이터없음
    daily_trading_value: int        # 전일 거래대금 (원)
    daily_position_type: str        # "신고가"/"전고점돌파"/"빈집"/"바닥반등"/"해당없음"
    ki_score: float                 # 0-100 끼 점수
    prev_day_change_pct: float      # 전일 등락률 (%)


class DailyContextLoader:
    """백테스트용 일별 컨텍스트 벌크 로더."""

    def __init__(self):
        self._analyzer = DailyChartAnalyzer()

    def load(
        self,
        codes: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, dict[date, StockDailyContext]]:
        """일별 컨텍스트를 벌크 로드.

        Returns:
            {종목코드: {날짜: StockDailyContext}}
        """
        engine = get_backtest_engine()

        # 1) ohlcv_daily에서 시총+거래대금+등락률 벌크 로드
        daily_data = self._load_daily_ohlcv(engine, codes, start_date, end_date)

        # 2) investor_trading에서 기관순매수 벌크 로드
        inst_data = self._load_institution_data(engine, codes, start_date, end_date)

        # 3) stocks에서 시총 로드
        cap_data = self._load_market_cap(engine, codes)

        # 4) 일봉자리 + 끼점수 계산 (ohlcv_daily 기반)
        daily_bars_cache = self._load_daily_bars_for_analysis(
            engine, codes, start_date, end_date,
        )

        # 5) 조합하여 StockDailyContext 생성
        result: dict[str, dict[date, StockDailyContext]] = {}

        for code in codes:
            result[code] = {}
            code_daily = daily_data.get(code, {})
            code_inst = inst_data.get(code, {})
            code_cap = cap_data.get(code, 0.0)
            code_bars = daily_bars_cache.get(code)

            for d, row in code_daily.items():
                # 기관 순매수: 전일 기준 (None=데이터없음)
                inst_net = code_inst.get(d, None)

                # 일봉자리 + 끼점수
                position_type = "해당없음"
                ki = 0.0
                if code_bars is not None and not code_bars.empty:
                    bars_before = code_bars[code_bars.index.date <= d]
                    if len(bars_before) >= 20:
                        pos_result = self._analyzer.classify_daily_position(bars_before)
                        position_type = pos_result.position_type
                        ki_result = self._analyzer.calculate_ki(bars_before)
                        ki = ki_result.score

                ctx = StockDailyContext(
                    code=code,
                    trade_date=d,
                    market_cap_bil=code_cap,
                    inst_net_buy_bil=inst_net,
                    daily_trading_value=row.get("value", 0),
                    daily_position_type=position_type,
                    ki_score=ki,
                    prev_day_change_pct=row.get("change_rate", 0.0),
                )
                result[code][d] = ctx

        total_ctx = sum(len(v) for v in result.values())
        logger.info(f"DailyContext 로드 완료: {len(codes)}종목, {total_ctx}건")
        return result

    def _load_daily_ohlcv(
        self, engine, codes: list[str], start_date: date, end_date: date,
    ) -> dict[str, dict[date, dict]]:
        """ohlcv_daily에서 거래대금+등락률 벌크 로드.

        value 컬럼이 0이면 close*volume으로 거래대금 추정.
        """
        result: dict[str, dict[date, dict]] = {}

        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT code, date, value, change_rate, close, volume
                FROM ohlcv_daily
                WHERE code = ANY(:codes)
                  AND date BETWEEN :start AND :end
                ORDER BY code, date
            """), {
                "codes": codes,
                "start": start_date,
                "end": end_date,
            }).fetchall()

        for row in rows:
            code = row[0]
            d = row[1] if isinstance(row[1], date) else row[1].date()
            if code not in result:
                result[code] = {}
            raw_value = int(row[2]) if row[2] else 0
            # value가 0이면 close * volume으로 추정
            if raw_value == 0:
                close = float(row[4]) if row[4] else 0
                volume = float(row[5]) if row[5] else 0
                raw_value = int(close * volume)
            result[code][d] = {
                "value": raw_value,
                "change_rate": float(row[3]) if row[3] else 0.0,
            }

        return result

    def _load_institution_data(
        self, engine, codes: list[str], start_date: date, end_date: date,
    ) -> dict[str, dict[date, float]]:
        """investor_trading에서 기관 순매수 (억원) 벌크 로드."""
        result: dict[str, dict[date, float]] = {}

        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT code, date,
                       COALESCE(institution_buy, 0) - COALESCE(institution_sell, 0) AS inst_net
                FROM investor_trading
                WHERE code = ANY(:codes)
                  AND date BETWEEN :start AND :end
                ORDER BY code, date
            """), {
                "codes": codes,
                "start": start_date,
                "end": end_date,
            }).fetchall()

        for row in rows:
            code = row[0]
            d = row[1] if isinstance(row[1], date) else row[1].date()
            inst_net_bil = float(row[2]) / 1e8  # 원 → 억원
            if code not in result:
                result[code] = {}
            result[code][d] = inst_net_bil

        return result

    def _load_market_cap(
        self, engine, codes: list[str],
    ) -> dict[str, float]:
        """stocks 테이블에서 시총 (억원) 로드."""
        result: dict[str, float] = {}

        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT code, market_cap
                FROM stocks
                WHERE code = ANY(:codes)
            """), {"codes": codes}).fetchall()

        for row in rows:
            cap_bil = float(row[1]) / 1e8 if row[1] else 0.0  # 원 → 억원
            result[row[0]] = cap_bil

        return result

    def _load_daily_bars_for_analysis(
        self, engine, codes: list[str], start_date: date, end_date: date,
    ) -> dict[str, Optional[pd.DataFrame]]:
        """일봉자리/끼점수 계산을 위한 일봉 데이터 로드 (분석 기간 90일 여유)."""
        from datetime import timedelta
        extended_start = start_date - timedelta(days=120)

        result: dict[str, Optional[pd.DataFrame]] = {}

        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT code, date, open, high, low, close, volume
                FROM ohlcv_daily
                WHERE code = ANY(:codes)
                  AND date BETWEEN :start AND :end
                ORDER BY code, date
            """), {
                "codes": codes,
                "start": extended_start,
                "end": end_date,
            }).fetchall()

        if not rows:
            return result

        df = pd.DataFrame(rows, columns=["code", "date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])

        for code, grp in df.groupby("code"):
            grp = grp.set_index("date").sort_index()
            grp = grp[["open", "high", "low", "close", "volume"]].astype(float)
            result[code] = grp

        return result
