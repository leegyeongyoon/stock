#!/usr/bin/env python3
"""수급(외국인/기관/개인 순매수) 수집 — KIS inquire-investor(일별 30일).

pykrx 투자자 엔드포인트가 불안정해 KIS 실전 API로 수집(신뢰성↑).
엣지 검증: 기관 순매수 → 다음날 상승 +7%p(2026-07-03). 유니버스=daily_movers 상위.
launchd(com.gylee.stock.investor)로 평일 16:05 실행. investor_trading 테이블 upsert.
"""
import asyncio
import sys
from pathlib import Path

import numpy as np

project = Path(__file__).parent.parent
sys.path.insert(0, str(project))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(project / ".env")
from sqlalchemy import text  # noqa: E402

from src.broker.kis_auth import KISAuth  # noqa: E402
from src.broker.kis_client import KISClient  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.database.repositories import InvestorTradingRepository  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)
INVESTOR_PATH = "/uapi/domestic-stock/v1/quotations/inquire-investor"


def _num(x) -> float:
    try:
        return float(str(x).replace(",", ""))
    except Exception:  # noqa: BLE001
        return 0.0


async def collect(topk: int = 150) -> None:
    if not settings.kis_app_key:
        logger.error("KIS 키 없음 — 중단")
        return
    with get_session() as s:
        codes = [r[0] for r in s.execute(text(
            "SELECT code FROM daily_movers GROUP BY code ORDER BY count(*) DESC LIMIT :k"),
            {"k": topk}).fetchall()]
    if not codes:
        logger.error("유니버스 없음(daily_movers 비어있음) — 중단")
        return
    client = KISClient(KISAuth(
        app_key=settings.kis_app_key, app_secret=settings.kis_app_secret,
        account_no=settings.kis_account_no, is_mock=settings.kis_is_mock))
    await client.start()
    total = 0
    try:
        for code in codes:
            try:
                d = await client._get(INVESTOR_PATH, "FHKST01010900",
                                      {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
                out = d.get("output", []) or []
                records = []
                for row in out:
                    dt = row.get("stck_bsop_date")
                    if not dt:
                        continue
                    frg = _num(row.get("frgn_ntby_qty")); org = _num(row.get("orgn_ntby_qty"))
                    prs = _num(row.get("prsn_ntby_qty"))
                    records.append({
                        "code": code,
                        "date": f"{dt[:4]}-{dt[4:6]}-{dt[6:]}",
                        "foreign_buy": frg if frg > 0 else 0, "foreign_sell": -frg if frg < 0 else 0,
                        "institution_buy": org if org > 0 else 0, "institution_sell": -org if org < 0 else 0,
                        "individual_buy": prs if prs > 0 else 0, "individual_sell": -prs if prs < 0 else 0,
                    })
                if records:
                    with get_session() as s:
                        total += InvestorTradingRepository(s).upsert_many(records)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"{code} 수급 실패: {e}")
            await asyncio.sleep(0.03)
    finally:
        await client.stop()
    logger.info(f"수급 수집 완료: {total}행 upsert / {len(codes)}종목")


if __name__ == "__main__":
    asyncio.run(collect())
