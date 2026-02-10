#!/usr/bin/env python3
"""거래대금 상위 1000종목의 분봉 데이터를 수집하여 DB에 저장.

Step 1: pykrx로 거래대금 상위 1000종목 선정 + 종목 정보 DB 저장
Step 2: pykrx로 일봉 1년 데이터 수집 (기본 백테스트용)
Step 3: yfinance로 5분봉 60일 데이터 수집 (단타 전략용)
"""

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

import pandas as pd
from pykrx import stock as pykrx_stock
from tqdm import tqdm

from src.database.connection import get_session, get_engine
from src.database.repositories import StockRepository, OHLCVRepository
from src.database.models import Base
from src.utils.logger import get_logger

logger = get_logger(__name__)

TARGET_STOCKS = 1000
DAILY_DAYS = 365      # 일봉 1년
INTRADAY_PERIOD = "60d"  # 분봉 60일
INTRADAY_INTERVAL = "5m"  # 5분봉


def ensure_intraday_table():
    """분봉 데이터 테이블이 없으면 생성."""
    from sqlalchemy import text
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ohlcv_intraday (
                id SERIAL PRIMARY KEY,
                code VARCHAR(20) NOT NULL,
                datetime TIMESTAMP NOT NULL,
                open INTEGER NOT NULL DEFAULT 0,
                high INTEGER NOT NULL DEFAULT 0,
                low INTEGER NOT NULL DEFAULT 0,
                close INTEGER NOT NULL DEFAULT 0,
                volume BIGINT NOT NULL DEFAULT 0,
                interval VARCHAR(10) NOT NULL DEFAULT '5m',
                UNIQUE(code, datetime, interval)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_intraday_code ON ohlcv_intraday(code)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_intraday_datetime ON ohlcv_intraday(datetime)
        """))
        conn.commit()
    logger.info("ohlcv_intraday 테이블 준비 완료")


def get_top_stocks_by_volume(target_date: date, top_n: int = TARGET_STOCKS) -> list[dict]:
    """거래대금 상위 종목을 KOSPI + KOSDAQ에서 가져온다."""
    date_str = target_date.strftime("%Y%m%d")
    all_stocks = []

    for market in ["KOSPI", "KOSDAQ"]:
        logger.info(f"{market} 종목 거래대금 조회 중...")
        try:
            cap_df = pykrx_stock.get_market_cap(date_str, market=market)
            if cap_df.empty:
                continue

            for ticker in cap_df.index:
                row = cap_df.loc[ticker]
                all_stocks.append({
                    "code": ticker,
                    "name": pykrx_stock.get_market_ticker_name(ticker),
                    "market": market,
                    "market_cap": int(row.get("시가총액", 0)),
                    "volume": int(row.get("거래량", 0)),
                    "value": int(row.get("거래대금", 0)),
                })
            time.sleep(1)
        except Exception as e:
            logger.error(f"{market} 조회 오류: {e}")

    logger.info(f"전체 종목 수: {len(all_stocks)}")
    all_stocks.sort(key=lambda x: x["value"], reverse=True)
    top_stocks = all_stocks[:top_n]

    logger.info(f"거래대금 상위 {len(top_stocks)}종목 선정 완료")
    if top_stocks:
        logger.info(f"  1위: {top_stocks[0]['name']} ({top_stocks[0]['code']})")
        logger.info(f"  {len(top_stocks)}위: {top_stocks[-1]['name']} ({top_stocks[-1]['code']})")

    return top_stocks


def save_stocks_to_db(stocks: list[dict]) -> int:
    """종목 정보를 DB에 저장."""
    with get_session() as session:
        repo = StockRepository(session)
        db_stocks = [
            {
                "code": s["code"],
                "name": s["name"],
                "market": s["market"],
                "market_cap": s["market_cap"],
                "is_active": True,
            }
            for s in stocks
        ]
        count = repo.upsert_many(db_stocks)
        logger.info(f"DB에 {count}개 종목 저장 완료")
        return count


def fetch_daily_ohlcv(codes: list[str], start_date: date, end_date: date) -> int:
    """일봉 OHLCV 데이터 수집 (pykrx)."""
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    total_records = 0
    success = 0

    with get_session() as session:
        ohlcv_repo = OHLCVRepository(session)

        for code in tqdm(codes, desc="일봉 수집"):
            try:
                df = pykrx_stock.get_market_ohlcv(start_str, end_str, code)
                if df.empty:
                    time.sleep(0.2)
                    continue

                records = []
                for idx, row in df.iterrows():
                    record_date = idx.date() if hasattr(idx, 'date') else idx
                    records.append({
                        "code": code,
                        "date": record_date,
                        "open": int(row.get("시가", 0)),
                        "high": int(row.get("고가", 0)),
                        "low": int(row.get("저가", 0)),
                        "close": int(row.get("종가", 0)),
                        "volume": int(row.get("거래량", 0)),
                        "value": int(row.get("거래대금", 0)),
                        "change_rate": float(row.get("등락률", 0)),
                    })

                if records:
                    count = ohlcv_repo.upsert_many(records)
                    total_records += count
                    success += 1

                if success % 100 == 0 and success > 0:
                    logger.info(f"  일봉 진행: {success}/{len(codes)}, {total_records:,}건")

            except Exception as e:
                logger.warning(f"  {code} 일봉 실패: {e}")

            time.sleep(0.3)

    logger.info(f"일봉 수집 완료: {success}종목, {total_records:,}건")
    return total_records


def fetch_intraday_ohlcv(codes: list[str], interval: str = "5m", period: str = "60d") -> int:
    """분봉 OHLCV 데이터 수집 (yfinance)."""
    import yfinance as yf
    from sqlalchemy import text

    total_records = 0
    success = 0
    fail = 0
    engine = get_engine()

    for code in tqdm(codes, desc="분봉 수집"):
        yahoo_ticker = f"{code}.KS"
        try:
            stock = yf.Ticker(yahoo_ticker)
            df = stock.history(period=period, interval=interval)

            if df.empty:
                # KOSDAQ 종목은 .KQ
                yahoo_ticker = f"{code}.KQ"
                stock = yf.Ticker(yahoo_ticker)
                df = stock.history(period=period, interval=interval)

            if df.empty:
                fail += 1
                time.sleep(0.2)
                continue

            # 컬럼 정리
            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            df = df[["open", "high", "low", "close", "volume"]].copy()

            # 타임존 변환
            if df.index.tz is not None:
                df.index = df.index.tz_convert("Asia/Seoul").tz_localize(None)

            # DB 저장 (bulk insert)
            records = []
            for idx, row in df.iterrows():
                records.append({
                    "code": code,
                    "datetime": idx,
                    "open": int(row["open"]),
                    "high": int(row["high"]),
                    "low": int(row["low"]),
                    "close": int(row["close"]),
                    "volume": int(row["volume"]),
                    "interval": interval,
                })

            if records:
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO ohlcv_intraday (code, datetime, open, high, low, close, volume, interval)
                        VALUES (:code, :datetime, :open, :high, :low, :close, :volume, :interval)
                        ON CONFLICT (code, datetime, interval) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume
                    """), records)
                    conn.commit()
                total_records += len(records)
                success += 1

            if success % 50 == 0 and success > 0:
                logger.info(f"  분봉 진행: {success}/{len(codes)}, {total_records:,}건")

        except Exception as e:
            logger.warning(f"  {code} 분봉 실패: {e}")
            fail += 1

        time.sleep(0.3)

    logger.info(f"분봉 수집 완료: 성공 {success}, 실패 {fail}, 총 {total_records:,}건")
    return total_records


def main():
    """메인 실행 함수."""
    # pykrx는 실제 거래일 데이터만 제공하므로 최신 영업일 사용
    # 오늘이 미래 날짜이거나 데이터가 없으면 2025-01-31 기준으로 조회
    end_date = date.today()
    # pykrx 데이터 존재 여부 확인
    from pykrx import stock as _pykrx
    test_tickers = _pykrx.get_market_ticker_list(end_date.strftime("%Y%m%d"), market="KOSPI")
    if not test_tickers:
        # 최근 데이터가 있는 날짜로 폴백
        for fallback_days in range(0, 365):
            fallback = date(2025, 1, 31) - timedelta(days=fallback_days)
            test_tickers = _pykrx.get_market_ticker_list(fallback.strftime("%Y%m%d"), market="KOSPI")
            if test_tickers:
                end_date = fallback
                logger.info(f"pykrx 데이터 기준일: {end_date}")
                break
    start_date = end_date - timedelta(days=DAILY_DAYS)

    logger.info("=" * 70)
    logger.info(f"거래대금 상위 {TARGET_STOCKS}종목 데이터 수집")
    logger.info(f"  일봉: {start_date} ~ {end_date} ({DAILY_DAYS}일)")
    logger.info(f"  분봉: {INTRADAY_INTERVAL} x {INTRADAY_PERIOD}")
    logger.info("=" * 70)

    # 0. 분봉 테이블 생성
    ensure_intraday_table()

    # 1. 거래대금 상위 종목 조회
    logger.info("\n[1/4] 거래대금 상위 종목 조회...")
    top_stocks = get_top_stocks_by_volume(end_date, TARGET_STOCKS)
    if not top_stocks:
        logger.error("종목 조회 실패")
        return

    # 2. 종목 정보 DB 저장
    logger.info("\n[2/4] 종목 정보 DB 저장...")
    save_stocks_to_db(top_stocks)

    codes = [s["code"] for s in top_stocks]

    # 3. 일봉 수집
    logger.info(f"\n[3/4] 일봉 데이터 수집 ({len(codes)}종목, 약 {len(codes)*0.3/60:.0f}분)...")
    daily_total = fetch_daily_ohlcv(codes, start_date, end_date)

    # 4. 분봉 수집
    logger.info(f"\n[4/4] 분봉 데이터 수집 ({len(codes)}종목, 약 {len(codes)*0.3/60:.0f}분)...")
    intraday_total = fetch_intraday_ohlcv(codes, INTRADAY_INTERVAL, INTRADAY_PERIOD)

    # 결과
    logger.info("\n" + "=" * 70)
    logger.info("전체 수집 완료!")
    logger.info(f"  종목 수: {len(codes)}")
    logger.info(f"  일봉: {daily_total:,}건")
    logger.info(f"  분봉: {intraday_total:,}건")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
