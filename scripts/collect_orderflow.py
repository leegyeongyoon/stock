#!/usr/bin/env python3
"""장중 호가/체결강도 전진 수집 — OHLC 봉에 없는 '오를 놈' 신호.

그날 movers 유니버스를 장중 폴링하며 체결강도(cttr)·호가잔량비를 DB에 적재한다.
이 데이터가 쌓이면 mine_orderflow 로 "체결강도/잔량비가 상승 지속을 예측하나"를 검증.

네트워크 + KIS 키 필요(시세 조회, 모의/실전 무관). 장중에 실행:
    python scripts/collect_orderflow.py                 # 오늘 movers, 장중 폴링
    python scripts/collect_orderflow.py --codes 005930,000660 --minutes 30
    python scripts/collect_orderflow.py --interval 10 --book   # 10단계 호가도 저장
"""

import argparse
import asyncio
import sys
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(project_root / ".env")

from src.broker.kis_auth import KISAuth  # noqa: E402
from src.broker.kis_client import KISClient  # noqa: E402
from src.broker.kis_constants import WS_MAX_SUBSCRIPTIONS  # noqa: E402
from src.broker.kis_websocket import KISWebSocket  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.database.connection import get_session  # noqa: E402
from src.database.repositories import DailyMoversRepository, OrderFlowSnapshotRepository  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

MARKET_CLOSE = dtime(15, 30)


def _record(of, now: datetime, book: bool, strength: float | None = None) -> dict:
    ratio = (of.total_bid_qty / of.total_ask_qty) if of.total_ask_qty else None
    # 체결강도: REST 호가엔 없음 → WS(H0STCNT0)에서 받은 최신값 우선, 없으면 of값
    es = strength if strength is not None else (of.exec_strength or None)
    return {
        "code": of.code, "captured_at": now, "current_price": of.current_price,
        "exec_strength": Decimal(str(es)) if es else None,
        "total_bid_qty": of.total_bid_qty, "total_ask_qty": of.total_ask_qty,
        "bid_ask_ratio": Decimal(str(round(ratio, 4))) if ratio is not None else None,
        "volume": of.volume,
        "book": ({"asks": of.asks, "bids": of.bids} if book and of.asks else None),
    }


async def collect(codes: list[str], interval: int, minutes: int, book: bool, topk: int = 40) -> None:
    if not settings.kis_app_key:
        logger.error("KIS API 키 없음(.env) — 중단")
        return
    auth = KISAuth(
        app_key=settings.kis_app_key, app_secret=settings.kis_app_secret,
        account_no=settings.kis_account_no, is_mock=settings.kis_is_mock,
    )
    client = KISClient(auth)
    await client.start()
    # 유니버스 없으면 KIS 거래량순위로 자동 선정 (pykrx 의존 제거)
    if not codes:
        try:
            rank = await client.get_volume_rank(market="KOSDAQ", blng="surge", top_n=topk)
            codes = [r["code"] for r in rank if r.get("code") and len(r["code"]) == 6]
            logger.info(f"KIS 거래량순위로 유니버스 {len(codes)}종목 선정")
        except Exception as e:  # noqa: BLE001
            logger.error(f"유니버스 확보 실패: {e}")
            codes = []
    if not codes:
        logger.error("유니버스 없음 — 중단")
        await client.stop()
        return
    logger.info(f"호가/체결강도 수집 시작: {len(codes)}종목, {interval}초 간격")

    # WS 체결강도(H0STCNT0) — additive: 실패해도 REST 스냅샷은 그대로 저장(exec_strength=null).
    # REST 호가 API엔 체결강도가 없어 WS 실시간 체결에서만 받을 수 있다.
    latest_strength: dict[str, tuple[float, float]] = {}  # code -> (체결강도, monotonic ts)

    def _on_tick(t) -> None:
        if t.exec_strength:
            latest_strength[t.code] = (t.exec_strength, time.monotonic())

    def _fresh_strength(code: str, max_age: float = 120.0) -> float | None:
        # 신선도 가드: WS 끊겨 값이 오래되면(>max_age) 묵힌 값으로 오염시키지 않는다.
        v = latest_strength.get(code)
        return v[0] if v and (time.monotonic() - v[1]) <= max_age else None

    ws = None
    try:
        approval = await client.get_ws_approval_key()
        ws = KISWebSocket(
            app_key=settings.kis_app_key, app_secret=settings.kis_app_secret,
            approval_key=approval, is_mock=settings.kis_is_mock, on_tick=_on_tick,
        )
        await ws.start(approval)
        for code in codes[:WS_MAX_SUBSCRIPTIONS]:
            await ws.subscribe_trade(code)
            await asyncio.sleep(0.05)
        logger.info(f"WS 체결강도 구독: {min(len(codes), WS_MAX_SUBSCRIPTIONS)}종목")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"WS 체결강도 비활성(REST만 수집): {e}")
        ws = None

    deadline = None
    if minutes:
        deadline = datetime.now().timestamp() + minutes * 60
    cycles = total = 0
    try:
        while True:
            now = datetime.now()
            if now.time() >= MARKET_CLOSE:
                logger.info("장 마감 — 수집 종료")
                break
            if deadline and now.timestamp() >= deadline:
                break
            records = []
            for code in codes:
                try:
                    of = await client.get_orderbook(code) if book else await client.get_orderflow(code)
                    records.append(_record(of, datetime.now(), book, _fresh_strength(code)))
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"{code} orderflow 실패: {e}")
            if records:
                with get_session() as s:
                    total += OrderFlowSnapshotRepository(s).insert_many(records)
            cycles += 1
            if cycles % 10 == 0:
                logger.info(f"  {cycles}사이클 / 누적 {total}스냅샷")
            await asyncio.sleep(interval)
    finally:
        if ws is not None:
            try:
                await ws.stop()
            except Exception:  # noqa: BLE001
                pass
        await client.stop()
    es_codes = len({c for c in codes if _fresh_strength(c, max_age=1e9) is not None})
    logger.info(f"수집 완료: {cycles}사이클 / {total}스냅샷 (체결강도 수신 {es_codes}종목)")


def main() -> int:
    p = argparse.ArgumentParser(description="장중 호가/체결강도 수집")
    p.add_argument("--codes", help="콤마구분 종목코드(미지정시 오늘 movers)")
    p.add_argument("--interval", type=int, default=10, help="폴링 간격(초)")
    p.add_argument("--minutes", type=int, default=0, help="최대 수집 시간(분, 0=장마감까지)")
    p.add_argument("--book", action="store_true", help="10단계 호가도 저장")
    p.add_argument("--topk", type=int, default=40, help="유니버스 자동선정 시 종목수")
    args = p.parse_args()

    codes: list[str] = []
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        try:
            with get_session() as s:
                # 거래대금 상위 topk만 — get_universe는 그날 전 종목 반환(KRX 연동 후 수천)이라
                # 그대로 쓰면 10초폴링·WS40 상한과 안 맞고 사이클이 안 끝난다.
                codes = DailyMoversRepository(s).get_universe(date.today())[: args.topk]
                logger.info(f"DailyMovers 거래대금 상위 {len(codes)}종목 유니버스")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"DailyMovers 조회 실패({e}) — KIS 거래량순위로 대체")
    # codes 비어있으면 collect() 안에서 KIS 거래량순위로 자동 선정
    asyncio.run(collect(codes, args.interval, args.minutes, args.book, args.topk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
