"""Intraday data fetcher using Yahoo Finance for Korean stocks."""

from datetime import datetime, timedelta
from typing import Optional, Literal
import time

import pandas as pd
import yfinance as yf
from tqdm import tqdm

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 주요 대형주/우량주 종목 (잡주 제외)
BLUE_CHIP_CODES = {
    # 시가총액 상위 대형주
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스",
    "005380": "현대차",
    "006400": "삼성SDI",
    "051910": "LG화학",
    "035420": "NAVER",
    "000270": "기아",
    "005490": "POSCO홀딩스",
    "035720": "카카오",
    "028260": "삼성물산",
    "105560": "KB금융",
    "012330": "현대모비스",
    "055550": "신한지주",
    "066570": "LG전자",
    "003670": "포스코퓨처엠",
    "096770": "SK이노베이션",
    "034730": "SK",
    "015760": "한국전력",
    "086790": "하나금융지주",
    "003550": "LG",
    "032830": "삼성생명",
    "259960": "크래프톤",
    "033780": "KT&G",
    # 중형 우량주
    "018260": "삼성에스디에스",
    "011200": "HMM",
    "034020": "두산에너빌리티",
    "010130": "고려아연",
    "009150": "삼성전기",
    "036570": "엔씨소프트",
    "003490": "대한항공",
    "010950": "S-Oil",
    "017670": "SK텔레콤",
    "030200": "KT",
    "000810": "삼성화재",
    "316140": "우리금융지주",
    "090430": "아모레퍼시픽",
    "068270": "셀트리온",
    "326030": "SK바이오팜",
}

# 거래량 상위 활발한 종목
ACTIVE_TRADING_CODES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "035720": "카카오",
    "005380": "현대차",
    "000270": "기아",
    "066570": "LG전자",
    "068270": "셀트리온",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "003670": "포스코퓨처엠",
    "011200": "HMM",
    "034020": "두산에너빌리티",
    "009150": "삼성전기",
    "012330": "현대모비스",
    "028260": "삼성물산",
    "003490": "대한항공",
    "010950": "S-Oil",
    "033780": "KT&G",
    "017670": "SK텔레콤",
}


class IntradayDataFetcher:
    """Fetches intraday (minute-level) data using Yahoo Finance."""

    def __init__(self, delay: float = 0.3):
        self.delay = delay

    def _to_yahoo_ticker(self, code: str) -> str:
        """Convert Korean stock code to Yahoo Finance ticker."""
        return f"{code}.KS"

    def get_intraday_data(
        self,
        code: str,
        interval: Literal["1m", "5m", "15m", "30m", "1h"] = "5m",
        period: str = "60d",
    ) -> pd.DataFrame:
        """
        Get intraday OHLCV data for a stock.

        Args:
            code: Korean stock code (e.g., "005930")
            interval: Data interval (1m, 5m, 15m, 30m, 1h)
            period: Data period (1d, 5d, 1mo, 60d, etc.)
                   Note: 1m data only available for last 7 days

        Returns:
            DataFrame with OHLCV data
        """
        ticker = self._to_yahoo_ticker(code)

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)

            if df.empty:
                return pd.DataFrame()

            # Rename columns to lowercase
            df = df.rename(columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })

            # Select only OHLCV columns
            df = df[["open", "high", "low", "close", "volume"]].copy()

            # Add code column
            df["code"] = code

            # Convert timezone to naive datetime
            if df.index.tz is not None:
                df.index = df.index.tz_convert("Asia/Seoul").tz_localize(None)

            return df

        except Exception as e:
            logger.error(f"Error fetching intraday data for {code}: {e}")
            return pd.DataFrame()

    def get_multiple_stocks(
        self,
        codes: list[str],
        interval: Literal["1m", "5m", "15m", "30m", "1h"] = "5m",
        period: str = "60d",
        show_progress: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """
        Get intraday data for multiple stocks.

        Returns:
            Dictionary mapping stock code to DataFrame
        """
        result = {}
        iterator = tqdm(codes, desc="Fetching intraday data") if show_progress else codes

        for code in iterator:
            df = self.get_intraday_data(code, interval, period)
            if not df.empty:
                result[code] = df
            time.sleep(self.delay)

        logger.info(f"Fetched intraday data for {len(result)}/{len(codes)} stocks")
        return result

    def get_blue_chips(
        self,
        interval: Literal["1m", "5m", "15m", "30m", "1h"] = "5m",
        period: str = "60d",
    ) -> dict[str, pd.DataFrame]:
        """Get intraday data for blue chip stocks."""
        codes = list(BLUE_CHIP_CODES.keys())
        return self.get_multiple_stocks(codes, interval, period)

    def get_active_stocks(
        self,
        interval: Literal["1m", "5m", "15m", "30m", "1h"] = "5m",
        period: str = "60d",
    ) -> dict[str, pd.DataFrame]:
        """Get intraday data for actively traded stocks."""
        codes = list(ACTIVE_TRADING_CODES.keys())
        return self.get_multiple_stocks(codes, interval, period)


def get_stock_name(code: str) -> str:
    """Get stock name by code."""
    if code in BLUE_CHIP_CODES:
        return BLUE_CHIP_CODES[code]
    if code in ACTIVE_TRADING_CODES:
        return ACTIVE_TRADING_CODES[code]
    return code
