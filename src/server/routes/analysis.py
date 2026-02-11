"""Analysis and reporting API routes."""

from fastapi import APIRouter, Depends, Query

from src.engine.strategy_runner import STRATEGY_META
from src.engine.trading_engine import TradingEngine
from src.server.dependencies import get_engine

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
            "total_pnl": round(total_pnl, 0),
            "avg_pnl": round(total_pnl / total_trades, 0) if total_trades > 0 else 0,
            "max_win": round(max_win, 0),
            "max_loss": round(max_loss, 0),
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
            "total_pnl": round(d["total_pnl"], 0),
            "win_rate": round(d["wins"] / d["trades"] * 100, 1) if d["trades"] > 0 else 0,
            "avg_pnl": round(d["total_pnl"] / d["trades"], 0) if d["trades"] > 0 else 0,
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
    # 저장된 거래 + 오늘 거래
    stored = engine.trade_store.load_all_trades()
    today = engine.get_trades_today()
    all_trades = stored + today

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
