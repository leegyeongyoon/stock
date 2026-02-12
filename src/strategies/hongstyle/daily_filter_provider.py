"""경윤 수정 매매법 - 일별 필터 제공자.

pykrx로 전일 시가총액 + 기관순매수 데이터를 1일 1회 수집하고 캐싱.
장전 08:50에 refresh() 호출 → 전일 날짜 기준 데이터 수집.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger


class DailyFilterProvider:
    """시총/기관/눌림 3개 필터 데이터 제공."""

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._data_date: Optional[str] = None
        self._last_refresh: Optional[datetime] = None
        self._refresh_count: int = 0

    @property
    def is_loaded(self) -> bool:
        return len(self._cache) > 0

    @property
    def data_date(self) -> Optional[str]:
        return self._data_date

    @property
    def stock_count(self) -> int:
        return len(self._cache)

    async def refresh(self) -> dict:
        """pykrx에서 전일 시총 + 기관순매수 수집 (동기 API → to_thread 래핑)."""
        try:
            result = await asyncio.to_thread(self._fetch_sync)
            self._last_refresh = datetime.now()
            self._refresh_count += 1
            logger.info(
                f"DailyFilterProvider 갱신 완료: "
                f"{len(self._cache)}종목, 날짜={self._data_date}"
            )
            return {
                "success": True,
                "stocks": len(self._cache),
                "date": self._data_date,
            }
        except Exception as e:
            logger.error(f"DailyFilterProvider 갱신 실패: {e}")
            return {"success": False, "error": str(e)}

    def _fetch_sync(self) -> None:
        """동기 pykrx 호출 (asyncio.to_thread에서 실행)."""
        import pandas as pd
        from pykrx import stock as pykrx_stock

        # 전일 날짜 계산 (주말/공휴일 고려)
        prev_date = self._get_prev_trading_date()
        self._data_date = prev_date

        cache: dict[str, dict] = {}

        # 1. 시가총액
        df_cap = pykrx_stock.get_market_cap_by_ticker(prev_date, market="ALL")
        if df_cap.empty:
            logger.warning(f"시가총액 데이터 없음: {prev_date}")
            return

        # 2. 기관 순매수 (KOSPI + KOSDAQ)
        inst_data = pd.Series(dtype=float)
        for market in ["KOSPI", "KOSDAQ"]:
            try:
                df_inst = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                    prev_date, prev_date, market=market, investor="기관합계"
                )
                if not df_inst.empty and "순매수거래대금" in df_inst.columns:
                    inst_data = pd.concat([inst_data, df_inst["순매수거래대금"]])
            except Exception as e:
                logger.warning(f"기관순매수 {market} 수집 실패: {e}")

        # 캐시 구성
        for code in df_cap.index:
            cap_억 = df_cap.loc[code, "시가총액"] / 1e8
            inst_억 = inst_data.get(code, 0) / 1e8 if code in inst_data.index else 0.0

            cache[code] = {
                "cap_bil": round(cap_억, 1),
                "inst_bil": round(inst_억, 1),
            }

        self._cache = cache

    @staticmethod
    def _get_prev_trading_date() -> str:
        """전일 거래일 (주말 제외)."""
        from pykrx import stock as pykrx_stock

        today = datetime.now()
        # 최근 10일 중 마지막 거래일
        start = (today - timedelta(days=10)).strftime("%Y%m%d")
        end = (today - timedelta(days=1)).strftime("%Y%m%d")

        try:
            df = pykrx_stock.get_market_ohlcv_by_date(start, end, "005930")
            if not df.empty:
                return df.index[-1].strftime("%Y%m%d")
        except Exception:
            pass

        # 폴백: 어제
        return (today - timedelta(days=1)).strftime("%Y%m%d")

    # ── 필터 메서드 ──────────────────────────────────────

    def passes_market_cap(self, code: str, min_bil: float = 5000) -> bool:
        """시가총액 5000억+ 필터."""
        info = self._cache.get(code)
        if not info:
            return False
        return info["cap_bil"] >= min_bil

    def passes_inst_filter(
        self, code: str, min_bil: float = 50, max_bil: float = 200
    ) -> bool:
        """전일 기관 순매수 50~200억 필터."""
        info = self._cache.get(code)
        if not info:
            return False
        return min_bil <= info["inst_bil"] <= max_bil

    @staticmethod
    def passes_pullback_filter(
        depth_pct: float,
        morning_vol: float,
        median_vol: float,
        min_depth: float = 5.0,
    ) -> bool:
        """눌림 필터: 95%깊이(5%+ 하락) + 오전거래량 중간값 이상.

        Args:
            depth_pct: 눌림 깊이 (%, 양수). 예: 5.0 = 5% 하락
            morning_vol: 오전 거래량
            median_vol: 최근 거래량 중간값
            min_depth: 최소 눌림 깊이 (기본 5%)
        """
        if depth_pct < min_depth:
            return False
        if morning_vol < median_vol:
            return False
        return True

    def get_stock_info(self, code: str) -> Optional[dict]:
        """종목의 시총/기관 정보 반환."""
        return self._cache.get(code)

    def get_filter_stats(self) -> dict:
        """필터별 통과율 반환 (대시보드용)."""
        if not self._cache:
            return {
                "data_date": self._data_date,
                "total_stocks": 0,
                "market_cap_pass": 0,
                "inst_filter_pass": 0,
                "both_pass": 0,
                "market_cap_rate": 0,
                "inst_filter_rate": 0,
                "both_rate": 0,
                "last_refresh": (
                    self._last_refresh.isoformat() if self._last_refresh else None
                ),
                "refresh_count": self._refresh_count,
            }

        total = len(self._cache)
        cap_pass = sum(
            1 for info in self._cache.values() if info["cap_bil"] >= 5000
        )
        inst_pass = sum(
            1
            for info in self._cache.values()
            if 50 <= info["inst_bil"] <= 200
        )
        both_pass = sum(
            1
            for info in self._cache.values()
            if info["cap_bil"] >= 5000 and 50 <= info["inst_bil"] <= 200
        )

        return {
            "data_date": self._data_date,
            "total_stocks": total,
            "market_cap_pass": cap_pass,
            "inst_filter_pass": inst_pass,
            "both_pass": both_pass,
            "market_cap_rate": round(cap_pass / total * 100, 1) if total else 0,
            "inst_filter_rate": round(inst_pass / total * 100, 1) if total else 0,
            "both_rate": round(both_pass / total * 100, 1) if total else 0,
            "last_refresh": (
                self._last_refresh.isoformat() if self._last_refresh else None
            ),
            "refresh_count": self._refresh_count,
        }


# 싱글톤
_provider: Optional[DailyFilterProvider] = None


def get_daily_filter_provider() -> DailyFilterProvider:
    global _provider
    if _provider is None:
        _provider = DailyFilterProvider()
    return _provider
