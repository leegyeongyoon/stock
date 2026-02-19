"""Analysis and reporting API routes."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query

from src.engine.strategy_runner import STRATEGY_META
from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/daily-report")
async def get_daily_report(engine: TradingEngine = Depends(get_engine)):
    """Get today's daily trading report."""
    trades = engine.get_trades_today()
    total_pnl = sum(t["pnl"] for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    win_rate = (wins / len(trades) * 100) if trades else 0

    by_strategy = {}
    for t in trades:
        sn = t["strategy_name"]
        if sn not in by_strategy:
            by_strategy[sn] = {"trades": 0, "wins": 0, "pnl": 0}
        by_strategy[sn]["trades"] += 1
        by_strategy[sn]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            by_strategy[sn]["wins"] += 1

    return {
        "total_trades": len(trades),
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "by_strategy": by_strategy,
        "trades": trades,
    }


@router.get("/by-strategy")
async def get_pnl_by_strategy(engine: TradingEngine = Depends(get_engine)):
    """전략별 수익률 집계."""
    # 오늘 실시간 데이터
    trades = engine.get_trades_today()
    # 과거 저장된 데이터
    stored = engine.trade_store.get_by_strategy()

    strategies = []
    for s_name, meta in STRATEGY_META.items():
        today_trades = [t for t in trades if t["strategy_name"] == s_name]
        hist = stored.get(s_name, {})

        total_trades = hist.get("trades", 0) + len(today_trades)
        wins = hist.get("wins", 0) + sum(1 for t in today_trades if t["pnl"] > 0)
        losses = total_trades - wins
        today_pnl = sum(t["pnl"] for t in today_trades)
        total_pnl = hist.get("total_pnl", 0) + today_pnl
        max_win = hist.get("max_win", 0)
        max_loss = hist.get("max_loss", 0)
        for t in today_trades:
            if t["pnl"] > max_win:
                max_win = t["pnl"]
            if t["pnl"] < max_loss:
                max_loss = t["pnl"]

        strategies.append({
            "strategy_name": s_name,
            "display_name": meta.get("display_name", s_name),
            "backtest_return": meta.get("backtest_return", ""),
            "backtest_wr": meta.get("backtest_wr", ""),
            "trades": total_trades,
            "wins": wins,
            "losses": losses,
            "total_pnl": int(round(total_pnl)),
            "avg_pnl": int(round(total_pnl / total_trades)) if total_trades > 0 else 0,
            "max_win": int(round(max_win)),
            "max_loss": int(round(max_loss)),
            "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
        })

    return {"strategies": strategies}


@router.get("/by-day-of-week")
async def get_pnl_by_day_of_week(engine: TradingEngine = Depends(get_engine)):
    """요일별 수익률 집계."""
    day_names = ["월", "화", "수", "목", "금"]
    stored = engine.trade_store.get_by_day_of_week()

    # 오늘 데이터 병합
    from datetime import datetime
    today_dow = datetime.now().weekday()
    if today_dow <= 4:
        today_day = day_names[today_dow]
        for t in engine.get_trades_today():
            stored[today_day]["trades"] += 1
            stored[today_day]["total_pnl"] += t["pnl"]
            if t["pnl"] > 0:
                stored[today_day]["wins"] += 1

    days = []
    for i, day in enumerate(day_names):
        d = stored.get(day, {"trades": 0, "wins": 0, "total_pnl": 0})
        days.append({
            "day": day,
            "day_index": i,
            "trades": d["trades"],
            "total_pnl": int(round(d["total_pnl"])),
            "win_rate": round(d["wins"] / d["trades"] * 100, 1) if d["trades"] > 0 else 0,
            "avg_pnl": int(round(d["total_pnl"] / d["trades"])) if d["trades"] > 0 else 0,
        })

    return {"days": days}


@router.get("/pnl-analysis")
async def get_pnl_analysis(engine: TradingEngine = Depends(get_engine)):
    """수익/손실 원인 분석."""
    trades = engine.get_trades_today()
    total_pnl = sum(t["pnl"] for t in trades)

    winning = [t for t in trades if t["pnl"] > 0]
    losing = [t for t in trades if t["pnl"] <= 0]

    # 전략별 집계
    by_strat: dict[str, float] = {}
    for t in trades:
        by_strat[t["strategy_name"]] = by_strat.get(t["strategy_name"], 0) + t["pnl"]

    best_strategy = max(by_strat, key=by_strat.get, default="없음") if by_strat else "없음"
    worst_strategy = min(by_strat, key=by_strat.get, default="없음") if by_strat else "없음"

    # 분석 문장 생성
    winning_factors = []
    losing_factors = []

    if not trades:
        summary = "오늘 아직 체결된 거래가 없습니다."
        recommendation = "장중에 전략이 동작하면 거래 분석이 표시됩니다."
    else:
        if total_pnl > 0:
            summary = f"오늘 총 {len(trades)}건 거래, +{total_pnl:,.0f}원 수익 달성"
        else:
            summary = f"오늘 총 {len(trades)}건 거래, {total_pnl:,.0f}원 손실 발생"

        if winning:
            best_trade = max(winning, key=lambda t: t["pnl"])
            meta = STRATEGY_META.get(best_trade["strategy_name"], {})
            winning_factors.append(
                f"최대 수익: {best_trade['stock_code']} +{best_trade['pnl']:,.0f}원 "
                f"({meta.get('display_name', best_trade['strategy_name'])})"
            )
            win_strategies = set(t["strategy_name"] for t in winning)
            for ws in win_strategies:
                m = STRATEGY_META.get(ws, {})
                cnt = sum(1 for t in winning if t["strategy_name"] == ws)
                winning_factors.append(f"{m.get('display_name', ws)}: {cnt}건 수익")

        if losing:
            worst_trade = min(losing, key=lambda t: t["pnl"])
            sl_exits = [t for t in losing if t.get("exit_reason") == "SL"]
            if sl_exits:
                losing_factors.append(f"손절(SL) {len(sl_exits)}건 발생")
            losing_factors.append(
                f"최대 손실: {worst_trade['stock_code']} {worst_trade['pnl']:,.0f}원"
            )
            sl_ratio = len(sl_exits) / len(losing) * 100 if losing else 0
            if sl_ratio > 70:
                losing_factors.append("SL 비율 70% 이상 - 진입 타이밍 재검토 필요")

        # 추천
        if total_pnl > 0:
            recommendation = f"{STRATEGY_META.get(best_strategy, {}).get('display_name', best_strategy)} 전략이 가장 효과적. 동일 시간대 집중 권장."
        else:
            recommendation = f"{STRATEGY_META.get(worst_strategy, {}).get('display_name', worst_strategy)} 전략 점검 필요. 조건 강화 또는 일시 중단 고려."

    best_meta = STRATEGY_META.get(best_strategy, {})
    worst_meta = STRATEGY_META.get(worst_strategy, {})

    return {
        "summary": summary,
        "winning_factors": winning_factors,
        "losing_factors": losing_factors,
        "best_strategy": best_meta.get("display_name", best_strategy),
        "worst_strategy": worst_meta.get("display_name", worst_strategy),
        "best_time_window": best_meta.get("time_window", ""),
        "recommendation": recommendation,
    }


@router.get("/trade-history")
async def get_trade_history(
    engine: TradingEngine = Depends(get_engine),
    strategy: str | None = Query(None),
    sort_by: str = Query("exit_time"),
    order: str = Query("desc"),
):
    """거래내역 전체 목록 (필터/정렬)."""

    def _normalize_time(t: str) -> str:
        """timezone suffix 제거하여 비교 키 통일."""
        if not t:
            return ""
        # +00:00, +09:00 등 timezone offset 제거
        if "+" in t and t.index("+") > 10:
            return t[: t.index("+")]
        return t

    # DB에서 모든 거래 로드 (오늘 포함)
    stored = engine.trade_store.load_all_trades()

    # 메모리의 오늘 거래 중 DB에 아직 없는 것만 추가 (중복 방지)
    stored_today_keys = set()
    today_str = date.today().isoformat()
    for t in stored:
        exit_time = t.get("exit_time", "")
        if isinstance(exit_time, str) and _normalize_time(exit_time).startswith(today_str):
            stored_today_keys.add(
                (t.get("stock_code", ""), _normalize_time(exit_time))
            )

    today = engine.get_trades_today()
    new_today = [
        t for t in today
        if (t.get("stock_code", ""), _normalize_time(t.get("exit_time", "")))
        not in stored_today_keys
    ]
    all_trades = stored + new_today

    # 필터
    if strategy:
        all_trades = [t for t in all_trades if t.get("strategy_name") == strategy]

    # 정렬
    reverse = order == "desc"
    if sort_by in ("pnl", "pnl_pct", "quantity"):
        all_trades.sort(key=lambda t: t.get(sort_by, 0), reverse=reverse)
    else:
        all_trades.sort(key=lambda t: t.get("exit_time", ""), reverse=reverse)

    return {"trades": all_trades, "total": len(all_trades)}


@router.post("/trade-history/cleanup")
async def cleanup_trade_history():
    """DB 중복 거래 제거 + '기존보유' 자동매도 거래 삭제."""
    try:
        from src.database.connection import get_session
        from src.database.models import LiveTrade
        from sqlalchemy import select, delete, func

        with get_session() as session:
            # 1. 전체 건수
            total_before = session.execute(
                select(func.count(LiveTrade.id))
            ).scalar() or 0

            # 2. "기존보유" 자동매도 거래 삭제
            existing_deleted = session.execute(
                delete(LiveTrade).where(LiveTrade.strategy_name == "기존보유")
            ).rowcount

            # 3. 중복 제거 (stock_code + traded_at 동일한 것 중 하나만 남김)
            subquery = session.execute(
                select(
                    LiveTrade.stock_code,
                    LiveTrade.traded_at,
                    func.min(LiveTrade.id).label("keep_id"),
                    func.count(LiveTrade.id).label("cnt"),
                ).group_by(
                    LiveTrade.stock_code, LiveTrade.traded_at
                ).having(func.count(LiveTrade.id) > 1)
            ).fetchall()

            dup_deleted = 0
            for row in subquery:
                result = session.execute(
                    delete(LiveTrade).where(
                        LiveTrade.stock_code == row.stock_code,
                        LiveTrade.traded_at == row.traded_at,
                        LiveTrade.id != row.keep_id,
                    )
                )
                dup_deleted += result.rowcount

            session.commit()

            total_after = session.execute(
                select(func.count(LiveTrade.id))
            ).scalar() or 0

            return {
                "success": True,
                "before": total_before,
                "after": total_after,
                "existing_deleted": existing_deleted,
                "duplicates_deleted": dup_deleted,
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


_shared_kis_client = None


async def _get_or_create_client(engine):
    """엔진 client를 우선 사용, 없으면 공유 client 1개 재사용."""
    global _shared_kis_client

    if engine.client:
        return engine.client

    from src.broker.kis_auth import KISAuth
    from src.broker.kis_client import KISClient
    from src.config.settings import settings

    if not settings.kis_app_key:
        return None

    if _shared_kis_client and _shared_kis_client._client:
        return _shared_kis_client

    auth = KISAuth(
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        account_no=settings.kis_account_no,
        is_mock=settings.kis_is_mock,
    )
    client = KISClient(auth)
    await client.start()
    _shared_kis_client = client
    return client


async def _fetch_executions_by_day(client, q_start: str, q_end: str):
    """날짜 범위의 체결내역을 일별로 개별 조회하여 병합.

    KIS 모의투자 서버는 날짜 범위 조회 시 일부 데이터만 반환하므로,
    각 영업일별로 개별 API 콜을 해서 모든 데이터를 확보한다.
    """
    from datetime import datetime, timedelta

    dt_start = datetime.strptime(q_start, "%Y%m%d")
    dt_end = datetime.strptime(q_end, "%Y%m%d")

    # 1일 조회면 그대로 호출
    if dt_start == dt_end:
        return await client.get_executions(
            start_date=q_start, end_date=q_end,
        )

    # 복수일: 각 날짜별로 개별 조회
    all_items = []
    seen_order_ids: set[str] = set()
    current = dt_start

    while current <= dt_end:
        # 주말 스킵 (토=5, 일=6)
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        day_str = current.strftime("%Y%m%d")
        try:
            day_items = await client.get_executions(
                start_date=day_str, end_date=day_str,
            )
            # 중복 제거 (order_id 기준)
            for item in day_items:
                if item.order_id and item.order_id in seen_order_ids:
                    continue
                if item.order_id:
                    seen_order_ids.add(item.order_id)
                all_items.append(item)

            logger.info(
                f"일별 조회 {day_str}: {len(day_items)}건 "
                f"(누적 {len(all_items)}건)"
            )
        except Exception as e:
            logger.warning(f"일별 조회 실패 {day_str}: {e}")

        current += timedelta(days=1)

    return all_items


@router.get("/kis-executions")
async def get_kis_executions(
    engine: TradingEngine = Depends(get_engine),
    date: str | None = Query(None, description="조회일 YYYY-MM-DD"),
    start_date: str | None = Query(None, description="시작일 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="종료일 YYYY-MM-DD"),
):
    """KIS 실제 체결내역 조회 → 매수/매도 매칭하여 종목별 수익 계산."""
    from datetime import datetime, timedelta

    if start_date and end_date:
        q_start = start_date.replace("-", "")
        q_end = end_date.replace("-", "")
    elif date:
        q_start = date.replace("-", "")
        q_end = q_start
    else:
        q_start = datetime.now().strftime("%Y%m%d")
        q_end = q_start

    client = await _get_or_create_client(engine)
    if not client:
        return {"trades": [], "open_positions": [], "error": "KIS API 키 미설정"}

    try:
        items = await _fetch_executions_by_day(client, q_start, q_end)
    except Exception as e:
        logger.error(f"KIS 체결내역 조회 실패: {e}")
        return {"trades": [], "open_positions": [], "error": str(e)}

    buy_count = sum(1 for it in items if it.side == "매수")
    sell_count = sum(1 for it in items if it.side == "매도")
    logger.info(
        f"KIS 체결내역 ({q_start}~{q_end}): 총 {len(items)}건 "
        f"(매수 {buy_count}, 매도 {sell_count})"
    )

    matched, open_buys, unmatched_sells = _match_executions(items)
    logger.info(
        f"1차 매칭: 매칭 {len(matched)}건, "
        f"미매도 {len(open_buys)}건, 미매칭매도 {len(unmatched_sells)}건"
    )

    # 2) 매칭 안 되는 매도 → 메인 조회 이전 기간에서 매수 탐색 (일별 조회)
    if unmatched_sells:
        dt_start = datetime.strptime(q_start, "%Y%m%d")
        hist_start = (dt_start - timedelta(days=30)).strftime("%Y%m%d")
        hist_end = (dt_start - timedelta(days=1)).strftime("%Y%m%d")

        need_codes = {s["stock_code"] for s in unmatched_sells}
        logger.info(
            f"과거 매수 검색: {hist_start}~{hist_end}, "
            f"필요종목={need_codes}"
        )

        try:
            hist_items = await _fetch_executions_by_day(
                client, hist_start, hist_end,
            )
            hist_buys = [
                it for it in hist_items
                if it.side == "매수" and it.stock_code in need_codes
            ]
            logger.info(
                f"과거 매수 결과: {len(hist_items)}건 중 "
                f"관련 매수 {len(hist_buys)}건"
            )
            if hist_buys:
                extra, unmatched_sells = _match_sells_with_buys(
                    unmatched_sells, hist_buys,
                )
                matched.extend(extra)
                logger.info(
                    f"과거 매칭: +{len(extra)}건, "
                    f"미매칭 {len(unmatched_sells)}건 남음"
                )
        except Exception as e:
            logger.error(f"과거 매수 검색 실패: {e}", exc_info=True)

    # 3) 그래도 매칭 안 된 매도 → 매도 정보만이라도 표시
    for sell in unmatched_sells:
        matched.append({
            "stock_code": sell["stock_code"],
            "stock_name": sell["stock_name"],
            "quantity": sell["quantity"],
            "buy_price": 0,
            "sell_price": sell["price"],
            "buy_amount": 0,
            "sell_amount": sell["price"] * sell["quantity"],
            "pnl": 0,
            "pnl_pct": 0,
            "buy_time": "",
            "sell_time": sell["order_time"],
        })

    matched.sort(key=lambda x: x["sell_time"], reverse=True)

    return {
        "trades": matched,
        "open_positions": open_buys,
        "raw_count": len(items),
        "_debug": {
            "query_range": f"{q_start}~{q_end}",
            "total_items": len(items),
            "buys": buy_count,
            "sells": sell_count,
        },
    }


def _match_executions(items):
    """매수/매도 FIFO 매칭. 반환: (matched, open_buys, unmatched_sells)."""
    from collections import defaultdict

    buys: dict[str, list] = defaultdict(list)
    sells: dict[str, list] = defaultdict(list)

    for item in items:
        entry = {
            "stock_code": item.stock_code,
            "stock_name": item.stock_name,
            "quantity": item.quantity,
            "price": item.price,
            "total_amount": item.total_amount,
            "order_time": item.order_time,
            "order_id": item.order_id,
        }
        if item.side == "매수":
            buys[item.stock_code].append(entry)
        else:
            sells[item.stock_code].append(entry)

    for code in buys:
        buys[code].sort(key=lambda x: x["order_time"])
    for code in sells:
        sells[code].sort(key=lambda x: x["order_time"])

    matched = []
    unmatched_sells = []

    for code, sell_list in sells.items():
        buy_list = buys.get(code, [])
        buy_idx = 0
        buy_remain = 0

        for sell in sell_list:
            sell_qty = sell["quantity"]

            while sell_qty > 0 and buy_idx < len(buy_list):
                buy = buy_list[buy_idx]
                avail = buy["quantity"] if buy_remain == 0 else buy_remain
                match_qty = min(avail, sell_qty)

                pnl = (sell["price"] - buy["price"]) * match_qty
                pnl_pct = (
                    (sell["price"] - buy["price"]) / buy["price"] * 100
                    if buy["price"] > 0 else 0
                )
                matched.append({
                    "stock_code": code,
                    "stock_name": sell["stock_name"] or buy["stock_name"],
                    "quantity": match_qty,
                    "buy_price": buy["price"],
                    "sell_price": sell["price"],
                    "buy_amount": buy["price"] * match_qty,
                    "sell_amount": sell["price"] * match_qty,
                    "pnl": pnl,
                    "pnl_pct": round(pnl_pct, 2),
                    "buy_time": buy["order_time"],
                    "sell_time": sell["order_time"],
                })

                sell_qty -= match_qty
                remaining = avail - match_qty
                if remaining <= 0:
                    buy_idx += 1
                    buy_remain = 0
                else:
                    buy_remain = remaining

            # 매칭 안 된 매도 잔량
            if sell_qty > 0:
                unmatched_sells.append({
                    **sell,
                    "quantity": sell_qty,
                })

        # 매칭 안 된 매수 잔량 반영
        if buy_idx < len(buy_list):
            if buy_remain > 0:
                buy_list[buy_idx] = {
                    **buy_list[buy_idx],
                    "quantity": buy_remain,
                    "total_amount": buy_list[buy_idx]["price"] * buy_remain,
                }
                buys[code] = buy_list[buy_idx:]
            else:
                buys[code] = buy_list[buy_idx:]
        else:
            buys[code] = []

    # 미매도 포지션
    open_positions = []
    for code, buy_list in buys.items():
        for buy in buy_list:
            if buy["quantity"] > 0:
                open_positions.append({
                    "stock_code": code,
                    "stock_name": buy["stock_name"],
                    "quantity": buy["quantity"],
                    "buy_price": buy["price"],
                    "buy_amount": buy["price"] * buy["quantity"],
                    "buy_time": buy["order_time"],
                })

    return matched, open_positions, unmatched_sells


def _match_sells_with_buys(unmatched_sells, hist_buys):
    """매칭 안 된 매도를 과거 매수와 FIFO 매칭."""
    from collections import defaultdict

    buys: dict[str, list] = defaultdict(list)
    for item in hist_buys:
        buys[item.stock_code].append({
            "stock_code": item.stock_code,
            "stock_name": item.stock_name,
            "quantity": item.quantity,
            "price": item.price,
            "order_time": item.order_time,
        })

    for code in buys:
        buys[code].sort(key=lambda x: x["order_time"])

    matched = []
    still_unmatched = []
    for sell in unmatched_sells:
        code = sell["stock_code"]
        buy_list = buys.get(code, [])
        sell_qty = sell["quantity"]

        while sell_qty > 0 and buy_list:
            buy = buy_list[0]
            match_qty = min(buy["quantity"], sell_qty)

            pnl = (sell["price"] - buy["price"]) * match_qty
            pnl_pct = (
                (sell["price"] - buy["price"]) / buy["price"] * 100
                if buy["price"] > 0 else 0
            )
            matched.append({
                "stock_code": code,
                "stock_name": sell["stock_name"] or buy["stock_name"],
                "quantity": match_qty,
                "buy_price": buy["price"],
                "sell_price": sell["price"],
                "buy_amount": buy["price"] * match_qty,
                "sell_amount": sell["price"] * match_qty,
                "pnl": pnl,
                "pnl_pct": round(pnl_pct, 2),
                "buy_time": buy["order_time"],
                "sell_time": sell["order_time"],
            })

            sell_qty -= match_qty
            buy["quantity"] -= match_qty
            if buy["quantity"] <= 0:
                buy_list.pop(0)

        if sell_qty > 0:
            still_unmatched.append({**sell, "quantity": sell_qty})

    return matched, still_unmatched


@router.get("/stocks/{code}")
async def get_stock_analysis(
    code: str,
    engine: TradingEngine = Depends(get_engine),
):
    """Get analysis for a specific stock."""
    if not engine.data_manager:
        return {"code": code, "bars": 0}

    df = engine.data_manager.get_today_df(code)
    bar_count = len(df) if not df.empty else 0
    trades = [t for t in engine.get_trades_today() if t["stock_code"] == code]

    return {
        "code": code,
        "bar_count": bar_count,
        "last_price": int(df.iloc[-1]["close"]) if not df.empty else 0,
        "trades": trades,
    }
