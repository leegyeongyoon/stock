#!/usr/bin/env python3
"""2026-02-13 ~ 03-17 기간 데이터 추가 수집.

Strategy:
- 분봉: yf.download() 배치 API (100종목씩)
- 일봉: pykrx (빠름)
"""

import sys
import time
import os
from datetime import date
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

os.environ["PYTHONWARNINGS"] = "ignore"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf
from pykrx import stock as pykrx_stock
from sqlalchemy import text
from tqdm import tqdm

from src.database.connection import get_session, get_engine
from src.database.repositories import OHLCVRepository
from src.utils.logger import get_logger

logger = get_logger(__name__)

BATCH_SIZE = 20  # yf.download 배치 크기


def get_remaining_codes() -> list[tuple[str, str]]:
    """아직 2/13 이후 데이터가 없는 종목 코드 + 마켓."""
    engine = get_engine()
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT DISTINCT code FROM ohlcv_intraday WHERE datetime::date >= '2026-02-13'"
        ))
        done = set(row[0] for row in r)

        r = conn.execute(text("""
            SELECT DISTINCT i.code, COALESCE(s.market, 'KOSPI') as market
            FROM ohlcv_intraday i
            LEFT JOIN stocks s ON i.code = s.code
            ORDER BY i.code
        """))
        all_codes = [(row[0], row[1]) for row in r]

    remaining = [(c, m) for c, m in all_codes if c not in done]
    logger.info(f"전체 {len(all_codes)}종목, 이미 수집 {len(done)}종목, 남은 {len(remaining)}종목")
    return remaining


def make_yahoo_ticker(code: str, market: str) -> str:
    return f"{code}.{'KQ' if market == 'KOSDAQ' else 'KS'}"


def fetch_intraday_batch(codes_markets: list[tuple[str, str]]) -> int:
    """yf.download 배치로 분봉 수집."""
    engine = get_engine()
    total_records = 0
    total_success = 0

    # 코드 → 티커 매핑
    ticker_to_code = {}
    for code, market in codes_markets:
        yt = make_yahoo_ticker(code, market)
        ticker_to_code[yt] = code

    tickers = list(ticker_to_code.keys())
    num_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
    logger.info(f"분봉 수집: {len(tickers)}종목, {num_batches}배치 (배치당 {BATCH_SIZE}종목)")

    for batch_idx in tqdm(range(num_batches), desc="분봉 배치"):
        batch_start = batch_idx * BATCH_SIZE
        batch_tickers = tickers[batch_start:batch_start + BATCH_SIZE]

        try:
            df = yf.download(
                batch_tickers,
                period="60d",
                interval="5m",
                group_by="ticker",
                threads=True,
                progress=False,
                timeout=30,
            )

            if df is None or df.empty:
                continue

            # 타임존 변환
            if df.index.tz is not None:
                df.index = df.index.tz_convert("Asia/Seoul").tz_localize(None)

            # 2026-02-12 이후만
            cutoff = pd.Timestamp("2026-02-12")
            df = df[df.index > cutoff]

            if df.empty:
                continue

            batch_records = []
            for yt in batch_tickers:
                code = ticker_to_code[yt]
                try:
                    if len(batch_tickers) == 1:
                        stock_df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                    else:
                        stock_df = df[yt][["Open", "High", "Low", "Close", "Volume"]].copy()

                    stock_df = stock_df.dropna(subset=["Close"])
                    if stock_df.empty:
                        continue

                    total_success += 1
                    for idx, row in stock_df.iterrows():
                        c = row["Close"]
                        if pd.isna(c) or c == 0:
                            continue
                        batch_records.append({
                            "code": code,
                            "datetime": idx,
                            "open": int(row["Open"]),
                            "high": int(row["High"]),
                            "low": int(row["Low"]),
                            "close": int(c),
                            "volume": int(row["Volume"]),
                            "interval": "5m",
                        })
                except Exception:
                    pass

            if batch_records:
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
                    """), batch_records)
                    conn.commit()
                total_records += len(batch_records)

            if (batch_idx + 1) % 5 == 0:
                logger.info(f"  진행: {batch_idx+1}/{num_batches} 배치, 성공 {total_success}종목, {total_records:,}건")

        except Exception as e:
            logger.warning(f"  배치 {batch_idx} 실패: {e}")

        time.sleep(2)  # 배치 간 딜레이

    logger.info(f"분봉 수집 완료: 성공 {total_success}종목, 신규 {total_records:,}건")
    return total_records


def fetch_daily_update(codes: list[str], start_date: date, end_date: date) -> int:
    """pykrx로 일봉 데이터 추가 수집."""
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
                    time.sleep(0.05)
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

                if success % 200 == 0 and success > 0:
                    logger.info(f"  일봉 진행: {success}/{len(codes)}, {total_records:,}건")

            except Exception as e:
                logger.warning(f"  {code} 일봉 실패: {e}")

            time.sleep(0.1)

    logger.info(f"일봉 수집 완료: {success}종목, {total_records:,}건")
    return total_records


def main():
    logger.info("=" * 70)
    logger.info("2026-02-13 ~ 03-17 누락 데이터 수집")
    logger.info("=" * 70)

    # 1. 남은 종목
    codes_markets = get_remaining_codes()
    engine = get_engine()
    with engine.connect() as conn:
        r = conn.execute(text("SELECT DISTINCT code FROM ohlcv_intraday ORDER BY code"))
        all_codes = [row[0] for row in r]

    if codes_markets:
        logger.info(f"\n[1/2] 분봉 데이터 수집 ({len(codes_markets)}종목, 배치당 {BATCH_SIZE})...")
        intraday_total = fetch_intraday_batch(codes_markets)
    else:
        logger.info("분봉 수집 완료 - 추가 수집 불필요")
        intraday_total = 0

    logger.info(f"\n[2/2] 일봉 데이터 수집 ({len(all_codes)}종목)...")
    daily_total = fetch_daily_update(
        all_codes,
        start_date=date(2026, 2, 10),
        end_date=date(2026, 3, 17),
    )

    # 결과
    with engine.connect() as conn:
        r1 = conn.execute(text(
            "SELECT MIN(datetime::date), MAX(datetime::date), COUNT(*), COUNT(DISTINCT code) FROM ohlcv_intraday"
        )).fetchone()
        r2 = conn.execute(text(
            "SELECT MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT code) FROM ohlcv_daily"
        )).fetchone()
        r3 = conn.execute(text(
            "SELECT COUNT(*), COUNT(DISTINCT code) FROM ohlcv_intraday WHERE datetime::date >= '2026-02-13'"
        )).fetchone()

    logger.info("\n" + "=" * 70)
    logger.info("수집 완료!")
    logger.info(f"  분봉 신규: {intraday_total:,}건")
    logger.info(f"  일봉 신규: {daily_total:,}건")
    logger.info(f"  분봉 전체: {r1[0]} ~ {r1[1]} ({r1[2]:,}건, {r1[3]}종목)")
    logger.info(f"  일봉 전체: {r2[0]} ~ {r2[1]} ({r2[2]:,}건, {r2[3]}종목)")
    logger.info(f"  2/13 이후 분봉: {r3[0]:,}건 ({r3[1]}종목)")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
