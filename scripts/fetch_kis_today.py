#!/usr/bin/env python3
"""오늘 장 1분봉을 KIS에서 받아 캐시 저장 (진짜 거래량). mine_intraday_patterns_yf로 분석.

yfinance 거래량이 망가져 vol_ratio 엣지가 0이었다. KIS 진짜 거래량으로 살아나는지 본다.
모의서버는 간헐적 500/rate-limit → 재시도 + 종목간 딜레이. /tmp/kis_today_1m.pkl 저장.
"""

import asyncio
import pickle
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.broker.kis_auth import KISAuth  # noqa: E402
from src.broker.kis_client import KISClient  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.database.connection import get_session  # noqa: E402

OUT = Path("/tmp/kis_today_1m.pkl")


ETF_KEYWORDS = ("TIGER", "KODEX", "RISE", "PLUS", "ARIRANG", "KBSTAR", "SOL", "ACE",
                "HANARO", "ETN", "레버리지", "인버스", "선물", "합성", "국채", "채권",
                "TR ", "액티브", "ETF", "Q5", "Q6", "TIMEFOLIO")


def _is_real_stock(code: str, name: str) -> bool:
    if not code or len(code) != 6:
        return False
    if any(k in (name or "") for k in ETF_KEYWORDS):
        return False
    return True


async def _movers_universe(client, n_codes: int) -> list[str]:
    """거래량 순위(증가율/거래대금)에서 실제 종목 선별 + KOSDAQ 보강."""
    codes: list[str] = []
    seen = set()
    for blng in ("surge", "value", "volume"):
        try:
            rank = await client.get_volume_rank(market="KOSDAQ", blng=blng, top_n=40)
        except Exception:  # noqa: BLE001
            continue
        for r in rank:
            if _is_real_stock(r["code"], r["name"]) and r["code"] not in seen:
                seen.add(r["code"]); codes.append(r["code"])
    # KOSDAQ 보강
    if len(codes) < n_codes:
        with get_session() as s:
            for (c,) in s.execute(text(
                "SELECT code FROM stocks WHERE market='KOSDAQ' ORDER BY code"
            )).fetchall():
                if c not in seen:
                    seen.add(c); codes.append(c)
                if len(codes) >= n_codes:
                    break
    return codes[:n_codes]


async def main(n_codes: int):
    auth = KISAuth(app_key=settings.kis_app_key, app_secret=settings.kis_app_secret,
                   account_no=settings.kis_account_no, is_mock=settings.kis_is_mock)
    client = KISClient(auth)
    await client.start()
    codes = await _movers_universe(client, n_codes)
    print(f"유니버스 {len(codes)}종목 (거래량순위 movers + KOSDAQ 보강)")
    today = date.today()
    data = {}
    try:
        for i, code in enumerate(codes):
            try:
                bars = await client.get_intraday_full_day(code, time_unit="1")
                bars = [b for b in bars if b.datetime.date() == today and b.volume >= 0]
                if len(bars) > 60:
                    df = pd.DataFrame([{"open": b.open, "high": b.high, "low": b.low,
                                        "close": b.close, "volume": b.volume} for b in bars],
                                      index=pd.DatetimeIndex([b.datetime for b in bars]))
                    df = df[(df["close"] > 0)]
                    if len(df) > 60:
                        data[code] = df
                print(f"  [{i+1}/{len(codes)}] {code}: {len(data.get(code, []))}봉")
            except Exception as e:  # noqa: BLE001
                print(f"  [{i+1}/{len(codes)}] {code} 실패: {repr(e)[:60]}")
            await asyncio.sleep(0.5)
    finally:
        await client.stop()
    if data:
        OUT.write_bytes(pickle.dumps(data))
        tot = sum(len(d) for d in data.values())
        vol = sum(int(d["volume"].sum()) for d in data.values())
        print(f"저장: {len(data)}종목 / {tot}봉 / 총거래량 {vol:,} → {OUT}")
        # DB 적재 (누적 학습용 — auto_optimize가 여러 날을 모아 학습)
        try:
            from src.database.repositories import OHLCVIntradayRepository
            records = []
            for code, df in data.items():
                for ts, row in df.iterrows():
                    records.append({
                        "code": code, "datetime": ts.to_pydatetime(),
                        "open": int(row["open"]), "high": int(row["high"]),
                        "low": int(row["low"]), "close": int(row["close"]),
                        "volume": int(row["volume"]), "interval": "1m",
                    })
            with get_session() as s:
                n = OHLCVIntradayRepository(s).upsert_many(records)
            print(f"DB 적재: {n}봉 (ohlcv_intraday 1m, 누적)")
        except Exception as e:  # noqa: BLE001
            print(f"DB 적재 실패(파일은 저장됨): {repr(e)[:100]}")
    else:
        print("수집 0 — 모의서버 시세 제한 추정")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    asyncio.run(main(n))
