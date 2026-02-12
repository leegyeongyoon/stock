"""
홍인기 핫테마 스캘핑 백테스트
- 오늘 핫테마 대장주 대상
- 짧은 TP/SL로 빈번하게 매매
- 한 종목 하루에 여러번 진입 가능
- 여러 TP/SL 조합 비교
"""

import os
import sys
import numpy as np
import pandas as pd
from dataclasses import dataclass
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from loguru import logger

# 오늘의 핫테마 종목
THEME_STOCKS = {
    "028260": {"name": "삼성물산", "theme": "건설"},
    "000720": {"name": "현대건설", "theme": "건설"},
    "047040": {"name": "대우건설", "theme": "건설"},
    "006360": {"name": "GS건설", "theme": "건설"},
    "294870": {"name": "HDC현대산업개발", "theme": "건설"},
    "003240": {"name": "태광산업", "theme": "홈쇼핑"},
    "023530": {"name": "롯데쇼핑", "theme": "홈쇼핑"},
    "057050": {"name": "현대홈쇼핑", "theme": "홈쇼핑"},
    "035760": {"name": "CJ ENM", "theme": "홈쇼핑"},
    "007070": {"name": "GS리테일", "theme": "홈쇼핑"},
    "055550": {"name": "신한지주", "theme": "은행"},
    "175330": {"name": "JB금융지주", "theme": "은행"},
    "138930": {"name": "BNK금융지주", "theme": "은행"},
    "024110": {"name": "기업은행", "theme": "은행"},
    "139130": {"name": "iM금융지주", "theme": "은행"},
    "002020": {"name": "코오롱", "theme": "두나무"},
    "120110": {"name": "코오롱인더", "theme": "두나무"},
    "003530": {"name": "한화투자증권", "theme": "두나무"},
    "246690": {"name": "TS인베스트먼트", "theme": "두나무"},
    "027830": {"name": "대성창투", "theme": "두나무"},
    "000810": {"name": "삼성화재", "theme": "손해보험"},
    "005830": {"name": "DB손해보험", "theme": "손해보험"},
    "000370": {"name": "한화손해보험", "theme": "손해보험"},
    "001450": {"name": "현대해상", "theme": "손해보험"},
    "000660": {"name": "SK하이닉스", "theme": "IT"},
    "004170": {"name": "신세계", "theme": "백화점"},
    "017670": {"name": "SK텔레콤", "theme": "통신"},
}

CODES = list(THEME_STOCKS.keys())
COMMISSION = 0.00015
TAX = 0.0023
ROUND_TRIP_COST = COMMISSION * 2 + TAX  # ~0.26%


@dataclass
class ScalpTrade:
    code: str
    name: str
    theme: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    reason: str
    hold_bars: int
    entry_time: str
    exit_time: str


def load_data():
    from sqlalchemy import create_engine
    engine = create_engine(os.getenv("DATABASE_URL"))

    placeholders = ",".join(f"'{c}'" for c in CODES)
    intraday_df = pd.read_sql(f"""
        SELECT code, datetime, open, high, low, close, volume
        FROM ohlcv_intraday WHERE code IN ({placeholders})
        ORDER BY code, datetime
    """, engine)
    intraday_df["datetime"] = pd.to_datetime(intraday_df["datetime"])
    intraday_df["date"] = intraday_df["datetime"].dt.date
    return intraday_df


def run_scalp_backtest(
    intraday_df: pd.DataFrame,
    tp_pct: float = 1.5,
    sl_pct: float = -1.0,
    max_hold_bars: int = 6,
    max_positions: int = 3,
    alloc_pct: float = 0.15,
    min_vol_ratio: float = 1.5,
    allow_reentry: bool = True,
    time_start_h: int = 9, time_start_m: int = 5,
    time_end_h: int = 14, time_end_m: int = 30,
    label: str = "",
):
    """스캘핑 백테스트 실행"""
    INIT_CAPITAL = 10_000_000
    cash = INIT_CAPITAL
    dates = sorted(intraday_df["date"].unique())
    intraday_by_date = {d: g for d, g in intraday_df.groupby("date")}

    all_trades: list[ScalpTrade] = []
    equity_curve = []
    daily_stats = []

    for day_idx, trade_date in enumerate(dates):
        day_bars = intraday_by_date.get(trade_date)
        if day_bars is None:
            continue

        positions = {}  # code -> {entry_price, quantity, entry_bar, entry_time}
        day_trades = []
        # 하루에 같은 종목 재진입 횟수 제한
        day_entry_count = defaultdict(int)
        MAX_REENTRY = 3

        for code in CODES:
            if code not in THEME_STOCKS:
                continue

            stock_bars = day_bars[day_bars["code"] == code].sort_values("datetime").reset_index(drop=True)
            if len(stock_bars) < 5:
                continue

            info = THEME_STOCKS[code]

            for bar_idx in range(len(stock_bars)):
                bar = stock_bars.iloc[bar_idx]
                bt = pd.Timestamp(bar["datetime"])
                h, m = bt.hour, bt.minute

                # ── 포지션 모니터 ──
                if code in positions:
                    pos = positions[code]
                    current = bar["close"]
                    pnl_pct_now = (current - pos["entry_price"]) / pos["entry_price"] * 100
                    hold_bars = bar_idx - pos["entry_bar"]

                    close_it = False
                    reason = ""

                    # TP
                    if pnl_pct_now >= tp_pct:
                        close_it = True
                        reason = "TP"
                    # SL
                    elif pnl_pct_now <= sl_pct:
                        close_it = True
                        reason = "SL"
                    # 시간 제한
                    elif hold_bars >= max_hold_bars:
                        close_it = True
                        reason = "시간초과"
                    # 장마감 임박
                    elif bar_idx >= len(stock_bars) - 2:
                        close_it = True
                        reason = "장마감"
                    # 고점 대비 하락 (트레일링)
                    elif pnl_pct_now >= tp_pct * 0.6 and hold_bars >= 3:
                        # 수익 중인데 3봉 지남 → 일부 먹고 나감
                        close_it = True
                        reason = "트레일"

                    if close_it:
                        pnl_amt = (current - pos["entry_price"]) * pos["quantity"]
                        pnl_amt -= current * pos["quantity"] * (TAX + COMMISSION)
                        cash += current * pos["quantity"] * (1 - TAX - COMMISSION)

                        trade = ScalpTrade(
                            code=code, name=info["name"], theme=info["theme"],
                            entry_price=pos["entry_price"], exit_price=current,
                            quantity=pos["quantity"], pnl=pnl_amt, pnl_pct=pnl_pct_now,
                            reason=reason, hold_bars=hold_bars,
                            entry_time=pos["entry_time"], exit_time=str(bar["datetime"]),
                        )
                        all_trades.append(trade)
                        day_trades.append(trade)
                        del positions[code]
                    continue

                # ── 진입 시그널 ──
                if bar_idx < 3:
                    continue
                if h < time_start_h or (h == time_start_h and m < time_start_m):
                    continue
                if h > time_end_h or (h == time_end_h and m > time_end_m):
                    continue
                if len(positions) >= max_positions:
                    continue
                if not allow_reentry and day_entry_count[code] > 0:
                    continue
                if day_entry_count[code] >= MAX_REENTRY:
                    continue

                price = bar["close"]
                volume = bar["volume"]
                if price <= 0 or volume <= 0:
                    continue

                prev = stock_bars.iloc[max(0, bar_idx-3):bar_idx]
                avg_vol = prev["volume"].mean()
                if avg_vol <= 0:
                    continue
                vol_ratio = volume / avg_vol

                # 양봉 + 거래량 급증
                if bar["close"] <= bar["open"]:
                    continue
                if vol_ratio < min_vol_ratio:
                    continue

                # 직전 고가 돌파
                recent_high = prev["high"].max()
                if price <= recent_high:
                    continue

                # 매수
                invest = cash * alloc_pct
                qty = int(invest / price)
                if qty <= 0:
                    continue
                cost = price * qty * (1 + COMMISSION)
                if cost > cash:
                    continue

                cash -= cost
                positions[code] = {
                    "entry_price": price, "quantity": qty,
                    "entry_bar": bar_idx, "entry_time": str(bar["datetime"]),
                }
                day_entry_count[code] += 1

        # 일말 강제 청산
        for code, pos in list(positions.items()):
            stock_bars = day_bars[day_bars["code"] == code].sort_values("datetime")
            if stock_bars.empty:
                continue
            last = stock_bars.iloc[-1]
            current = last["close"]
            pnl_pct_now = (current - pos["entry_price"]) / pos["entry_price"] * 100
            pnl_amt = (current - pos["entry_price"]) * pos["quantity"]
            pnl_amt -= current * pos["quantity"] * (TAX + COMMISSION)
            cash += current * pos["quantity"] * (1 - TAX - COMMISSION)

            trade = ScalpTrade(
                code=code, name=THEME_STOCKS[code]["name"],
                theme=THEME_STOCKS[code]["theme"],
                entry_price=pos["entry_price"], exit_price=current,
                quantity=pos["quantity"], pnl=pnl_amt, pnl_pct=pnl_pct_now,
                reason="장마감", hold_bars=0,
                entry_time=pos["entry_time"], exit_time=str(last["datetime"]),
            )
            all_trades.append(trade)
            day_trades.append(trade)

        equity_curve.append({"date": trade_date, "equity": cash})
        day_pnl = sum(t.pnl for t in day_trades)
        daily_stats.append({"date": trade_date, "pnl": day_pnl, "trades": len(day_trades)})

    # ═══ 집계 ═══
    final = cash
    total_return = (final - INIT_CAPITAL) / INIT_CAPITAL * 100
    wins = [t for t in all_trades if t.pnl > 0]
    losses = [t for t in all_trades if t.pnl <= 0]
    wr = len(wins) / len(all_trades) * 100 if all_trades else 0
    avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.pnl_pct for t in losses]) if losses else 0
    avg_hold = np.mean([t.hold_bars for t in all_trades]) if all_trades else 0

    peak = INIT_CAPITAL
    max_dd = 0
    for e in equity_curve:
        peak = max(peak, e["equity"])
        dd = (peak - e["equity"]) / peak * 100
        max_dd = max(max_dd, dd)

    # 청산 사유별
    reason_stats = defaultdict(lambda: {"cnt": 0, "pnl": 0, "wins": 0})
    for t in all_trades:
        reason_stats[t.reason]["cnt"] += 1
        reason_stats[t.reason]["pnl"] += t.pnl
        if t.pnl > 0:
            reason_stats[t.reason]["wins"] += 1

    # 테마별
    theme_stats = defaultdict(lambda: {"cnt": 0, "pnl": 0, "wins": 0})
    for t in all_trades:
        theme_stats[t.theme]["cnt"] += 1
        theme_stats[t.theme]["pnl"] += t.pnl
        if t.pnl > 0:
            theme_stats[t.theme]["wins"] += 1

    # 일평균
    trading_days = len([d for d in daily_stats if d["trades"] > 0])
    avg_daily_trades = len(all_trades) / trading_days if trading_days else 0
    avg_daily_pnl = np.mean([d["pnl"] for d in daily_stats if d["trades"] > 0]) if trading_days else 0

    return {
        "label": label,
        "tp": tp_pct, "sl": sl_pct, "max_hold": max_hold_bars,
        "total_return": total_return,
        "total_pnl": final - INIT_CAPITAL,
        "trades": len(all_trades),
        "wins": len(wins), "losses": len(losses),
        "wr": wr, "avg_win": avg_win, "avg_loss": avg_loss,
        "avg_hold": avg_hold, "max_dd": max_dd,
        "avg_daily_trades": avg_daily_trades,
        "avg_daily_pnl": avg_daily_pnl,
        "reason_stats": dict(reason_stats),
        "theme_stats": dict(theme_stats),
        "daily_stats": daily_stats,
        "equity_curve": equity_curve,
        "all_trades": all_trades,
    }


def main():
    logger.info("데이터 로딩...")
    intraday_df = load_data()
    logger.info(f"5분봉: {len(intraday_df):,}행")

    # ═══ 여러 전략 비교 ═══
    configs = [
        # (label, tp, sl, max_hold_bars, max_pos, alloc, min_vol, reentry, time_range)
        ("A. 초단타 (TP1%/SL0.7%/15분)", 1.0, -0.7, 3, 3, 0.15, 1.5, True, 9, 5, 14, 30),
        ("B. 단타 (TP1.5%/SL1%/30분)", 1.5, -1.0, 6, 3, 0.15, 1.5, True, 9, 5, 14, 30),
        ("C. 스윙단타 (TP2%/SL1.2%/1시간)", 2.0, -1.2, 12, 3, 0.15, 1.5, True, 9, 5, 14, 30),
        ("D. 넓은 스윙 (TP3%/SL1.5%/2시간)", 3.0, -1.5, 24, 3, 0.15, 1.5, True, 9, 5, 14, 30),
        ("E. 오전집중 (TP1.5%/SL1%/9-11시)", 1.5, -1.0, 6, 3, 0.15, 1.5, True, 9, 5, 11, 0),
        ("F. 재진입X (TP1.5%/SL1%/30분)", 1.5, -1.0, 6, 3, 0.15, 1.5, False, 9, 5, 14, 30),
        ("G. 공격적 (TP1.5%/SL1%/5종목)", 1.5, -1.0, 6, 5, 0.10, 1.3, True, 9, 5, 14, 30),
        ("H. 기존 홍인기 (TP5%/SL4%/홀드)", 5.0, -4.0, 999, 5, 0.12, 1.5, False, 9, 5, 14, 30),
    ]

    results = []
    for cfg in configs:
        label = cfg[0]
        logger.info(f"  실행 중: {label}")
        r = run_scalp_backtest(
            intraday_df,
            tp_pct=cfg[1], sl_pct=cfg[2], max_hold_bars=cfg[3],
            max_positions=cfg[4], alloc_pct=cfg[5], min_vol_ratio=cfg[6],
            allow_reentry=cfg[7],
            time_start_h=cfg[8], time_start_m=cfg[9],
            time_end_h=cfg[10], time_end_m=cfg[11],
            label=label,
        )
        results.append(r)

    # ═══ 비교표 출력 ═══
    print("\n" + "=" * 100)
    print("  홍인기 핫테마 스캘핑 전략 비교 (60거래일, 27종목)")
    print("=" * 100)

    print(f"\n  수수료: 매수 0.015% + 매도 0.015% + 세금 0.23% = 왕복 ~0.26%")
    print(f"  참고: TP 1%면 실질수익 ~0.74%, TP 1.5%면 ~1.24%\n")

    header = f"{'전략':40s} {'수익률':>8s} {'거래수':>6s} {'승률':>6s} {'평균+':>7s} {'평균-':>7s} {'MDD':>6s} {'일평균':>8s} {'홀드':>5s}"
    print(header)
    print("-" * 100)

    for r in results:
        line = (
            f"  {r['label']:38s} "
            f"{r['total_return']:>+7.2f}% "
            f"{r['trades']:>5d}건 "
            f"{r['wr']:>5.1f}% "
            f"{r['avg_win']:>+6.2f}% "
            f"{r['avg_loss']:>+6.2f}% "
            f"{r['max_dd']:>5.2f}% "
            f"{r['avg_daily_pnl']:>+7.0f}원 "
            f"{r['avg_hold']:>4.1f}봉"
        )
        print(line)

    # 상세 결과: 가장 좋은 전략
    best = max(results, key=lambda x: x["total_return"])
    print(f"\n{'=' * 100}")
    print(f"  BEST: {best['label']}")
    print(f"{'=' * 100}")
    print(f"  수익률: {best['total_return']:+.2f}% | 총손익: {best['total_pnl']:+,.0f}원")
    print(f"  거래: {best['trades']}건 (승 {best['wins']} / 패 {best['losses']})")
    print(f"  승률: {best['wr']:.1f}% | 평균수익 {best['avg_win']:+.2f}% | 평균손실 {best['avg_loss']:+.2f}%")
    print(f"  평균 홀드: {best['avg_hold']:.1f}봉 ({best['avg_hold']*5:.0f}분)")
    print(f"  일평균 거래: {best['avg_daily_trades']:.1f}건 | 일평균 PnL: {best['avg_daily_pnl']:+,.0f}원")
    print(f"  최대낙폭: {best['max_dd']:.2f}%")

    print(f"\n  ── 청산 사유별 ──")
    for reason, st in sorted(best["reason_stats"].items(), key=lambda x: x[1]["cnt"], reverse=True):
        wr = st["wins"]/st["cnt"]*100 if st["cnt"] else 0
        print(f"    {reason:>8s}: {st['cnt']:>4}건 (승률 {wr:5.1f}%) | PnL {st['pnl']:>+12,.0f}원")

    print(f"\n  ── 테마별 ──")
    for theme, st in sorted(best["theme_stats"].items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = st["wins"]/st["cnt"]*100 if st["cnt"] else 0
        print(f"    {theme:>8s}: {st['cnt']:>4}건 (승률 {wr:5.1f}%) | PnL {st['pnl']:>+12,.0f}원")

    print(f"\n  ── 최근 15일 ──")
    for d in best["daily_stats"][-15:]:
        eq = [e["equity"] for e in best["equity_curve"] if e["date"] == d["date"]]
        ev = eq[0] if eq else 0
        star = " ★" if d["pnl"] > 0 else ""
        print(f"    {d['date']}: {d['trades']:>3}건 | PnL {d['pnl']:>+10,.0f}원 | 자산 {ev:>12,.0f}원{star}")

    # 최악 전략
    worst = min(results, key=lambda x: x["total_return"])
    if worst != best:
        print(f"\n  ── WORST: {worst['label']} ──")
        print(f"  수익률: {worst['total_return']:+.2f}% | 거래 {worst['trades']}건 | 승률 {worst['wr']:.1f}%")

    # 손익 분기점 분석
    print(f"\n{'=' * 100}")
    print(f"  손익분기 분석 (왕복 수수료 ~0.26%)")
    print(f"{'=' * 100}")
    for r in results:
        be_wr = 0
        if r["avg_win"] and r["avg_loss"]:
            net_win = r["avg_win"] - ROUND_TRIP_COST * 100
            net_loss = abs(r["avg_loss"]) + ROUND_TRIP_COST * 100
            if net_win + net_loss > 0:
                be_wr = net_loss / (net_win + net_loss) * 100
        margin = r["wr"] - be_wr
        status = "✓ 수익" if margin > 0 else "✗ 손실"
        print(f"  {r['label']:40s}: 실제WR {r['wr']:5.1f}% vs 필요WR {be_wr:5.1f}% → 마진 {margin:+5.1f}%p {status}")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
