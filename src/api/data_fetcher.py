"""Data fetcher using pykrx for Korean stock market data."""

from datetime import date, datetime, timedelta
import time
from typing import Optional

import pandas as pd
from pykrx import stock as pykrx_stock
from tqdm import tqdm

from src.config.constants import Market
from src.database.connection import get_session
from src.database.repositories import StockRepository, OHLCVRepository, InvestorTradingRepository
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DataFetcher:
    """Fetches stock data from KRX using pykrx."""

    def __init__(self, delay: float = 0.5):
        """
        Initialize DataFetcher.

        Args:
            delay: Delay between API calls in seconds to avoid rate limiting.
        """
        self.delay = delay

    def _to_str_date(self, d: date) -> str:
        """Convert date to string format for pykrx."""
        return d.strftime("%Y%m%d")

    def get_kospi_tickers(self, target_date: Optional[date] = None) -> list[str]:
        """Get all KOSPI stock codes."""
        if target_date is None:
            target_date = date.today()
        return pykrx_stock.get_market_ticker_list(
            self._to_str_date(target_date), market="KOSPI"
        )

    def get_kosdaq_tickers(self, target_date: Optional[date] = None) -> list[str]:
        """Get all KOSDAQ stock codes."""
        if target_date is None:
            target_date = date.today()
        return pykrx_stock.get_market_ticker_list(
            self._to_str_date(target_date), market="KOSDAQ"
        )

    def get_all_tickers(self, target_date: Optional[date] = None) -> dict[str, list[str]]:
        """Get all KOSPI and KOSDAQ stock codes."""
        return {
            Market.KOSPI: self.get_kospi_tickers(target_date),
            Market.KOSDAQ: self.get_kosdaq_tickers(target_date),
        }

    def get_stock_name(self, ticker: str) -> str:
        """Get stock name by ticker."""
        return pykrx_stock.get_market_ticker_name(ticker)

    def get_ohlcv(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Get OHLCV data for a stock.

        Returns DataFrame with columns: open, high, low, close, volume, value, change_rate
        """
        try:
            df = pykrx_stock.get_market_ohlcv(
                self._to_str_date(start_date),
                self._to_str_date(end_date),
                ticker,
            )

            if df.empty:
                return pd.DataFrame()

            # Rename columns to English
            df = df.rename(
                columns={
                    "시가": "open",
                    "고가": "high",
                    "저가": "low",
                    "종가": "close",
                    "거래량": "volume",
                    "거래대금": "value",
                    "등락률": "change_rate",
                }
            )

            # Ensure numeric types
            for col in ["open", "high", "low", "close", "volume", "value"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

            if "change_rate" in df.columns:
                df["change_rate"] = pd.to_numeric(df["change_rate"], errors="coerce")

            return df

        except Exception as e:
            logger.error(f"Error fetching OHLCV for {ticker}: {e}")
            return pd.DataFrame()

    def get_investor_trading(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Get investor trading data (기관, 외인, 개인).

        Returns DataFrame with buy/sell volumes by investor type.
        """
        try:
            df = pykrx_stock.get_market_trading_volume_by_investor(
                self._to_str_date(start_date),
                self._to_str_date(end_date),
                ticker,
            )

            if df.empty:
                return pd.DataFrame()

            # Rename and select relevant columns
            result = pd.DataFrame(index=df.index)

            # 기관 합계
            if "기관합계" in df.columns:
                # Get buy/sell from different structure
                pass

            # For now, get net trading which is what pykrx primarily returns
            if "기관합계" in df.columns:
                result["institution_net"] = df["기관합계"]
            if "외국인합계" in df.columns:
                result["foreign_net"] = df["외국인합계"]
            if "개인" in df.columns:
                result["individual_net"] = df["개인"]

            return result

        except Exception as e:
            logger.error(f"Error fetching investor trading for {ticker}: {e}")
            return pd.DataFrame()

    def get_market_cap(self, ticker: str, target_date: date) -> Optional[int]:
        """Get market capitalization for a stock."""
        try:
            df = pykrx_stock.get_market_cap(
                self._to_str_date(target_date),
                self._to_str_date(target_date),
                ticker,
            )
            if not df.empty and "시가총액" in df.columns:
                return int(df["시가총액"].iloc[0])
            return None
        except Exception:
            return None

    def fetch_and_save_stocks(self, target_date: Optional[date] = None) -> int:
        """Fetch all stocks and save to database."""
        if target_date is None:
            target_date = date.today()

        logger.info("Fetching stock list...")
        tickers = self.get_all_tickers(target_date)

        stocks = []
        for market, codes in tickers.items():
            logger.info(f"Processing {market}: {len(codes)} stocks")
            for code in tqdm(codes, desc=f"Fetching {market} stocks"):
                name = self.get_stock_name(code)
                stocks.append({
                    "code": code,
                    "name": name,
                    "market": market,
                    "is_active": True,
                })
                time.sleep(0.1)  # Small delay

        with get_session() as session:
            repo = StockRepository(session)
            count = repo.upsert_many(stocks)
            logger.info(f"Saved {count} stocks to database")

        return len(stocks)

    def fetch_and_save_ohlcv(
        self,
        codes: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        market: Optional[str] = None,
    ) -> int:
        """
        Fetch OHLCV data for stocks and save to database.

        Args:
            codes: List of stock codes. If None, fetch all from database.
            start_date: Start date. Default is 3 years ago.
            end_date: End date. Default is today.
            market: Filter by market (KOSPI/KOSDAQ).
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=365 * 3)

        with get_session() as session:
            if codes is None:
                stock_repo = StockRepository(session)
                codes = stock_repo.get_codes(market=market)

            logger.info(f"Fetching OHLCV for {len(codes)} stocks from {start_date} to {end_date}")

            ohlcv_repo = OHLCVRepository(session)
            total_records = 0

            for code in tqdm(codes, desc="Fetching OHLCV"):
                df = self.get_ohlcv(code, start_date, end_date)

                if df.empty:
                    continue

                records = []
                for idx, row in df.iterrows():
                    record_date = idx.date() if isinstance(idx, datetime) else idx
                    records.append({
                        "code": code,
                        "date": record_date,
                        "open": int(row["open"]),
                        "high": int(row["high"]),
                        "low": int(row["low"]),
                        "close": int(row["close"]),
                        "volume": int(row["volume"]),
                        "value": int(row.get("value", 0)),
                        "change_rate": row.get("change_rate"),
                    })

                if records:
                    count = ohlcv_repo.upsert_many(records)
                    total_records += count

                time.sleep(self.delay)

            logger.info(f"Saved {total_records} OHLCV records to database")

        return total_records

    def fetch_and_save_investor_trading(
        self,
        codes: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> int:
        """Fetch investor trading data and save to database."""
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=365)

        with get_session() as session:
            if codes is None:
                stock_repo = StockRepository(session)
                codes = stock_repo.get_codes()

            logger.info(f"Fetching investor trading for {len(codes)} stocks")

            investor_repo = InvestorTradingRepository(session)
            total_records = 0

            for code in tqdm(codes, desc="Fetching investor trading"):
                df = self.get_investor_trading(code, start_date, end_date)

                if df.empty:
                    continue

                records = []
                for idx, row in df.iterrows():
                    record_date = idx.date() if isinstance(idx, datetime) else idx
                    records.append({
                        "code": code,
                        "date": record_date,
                        "institution_buy": row.get("institution_net", 0) if row.get("institution_net", 0) > 0 else 0,
                        "institution_sell": abs(row.get("institution_net", 0)) if row.get("institution_net", 0) < 0 else 0,
                        "foreign_buy": row.get("foreign_net", 0) if row.get("foreign_net", 0) > 0 else 0,
                        "foreign_sell": abs(row.get("foreign_net", 0)) if row.get("foreign_net", 0) < 0 else 0,
                        "individual_buy": row.get("individual_net", 0) if row.get("individual_net", 0) > 0 else 0,
                        "individual_sell": abs(row.get("individual_net", 0)) if row.get("individual_net", 0) < 0 else 0,
                    })

                if records:
                    count = investor_repo.upsert_many(records)
                    total_records += count

                time.sleep(self.delay)

            logger.info(f"Saved {total_records} investor trading records")

        return total_records

    def update_all_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, int]:
        """Update all data (stocks, OHLCV, investor trading)."""
        results = {}

        # 1. Update stock list
        results["stocks"] = self.fetch_and_save_stocks()

        # 2. Update OHLCV
        results["ohlcv"] = self.fetch_and_save_ohlcv(
            start_date=start_date,
            end_date=end_date,
        )

        # 3. Update investor trading
        results["investor_trading"] = self.fetch_and_save_investor_trading(
            start_date=start_date,
            end_date=end_date,
        )

        return results
