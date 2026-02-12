"""
홍인기 전략 테마 기반 백테스트
- 실제 테마 데이터(오늘 기준)의 핫테마 종목만 대상
- vs 기존 거래대금 상위 30종목 proxy 비교
"""

import os
import sys
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger

# ── 오늘의 실제 핫테마 종목 (ThemeAnalyzer 결과) ──
THEME_STOCKS = {
    "028260": {"name": "삼성물산", "theme": "건설 대표주", "score": 25},
    "000720": {"name": "현대건설", "theme": "건설 대표주", "score": 10},
    "047040": {"name": "대우건설", "theme": "건설 대표주", "score": 0},
    "006360": {"name": "GS건설", "theme": "건설 대표주", "score": 0},
    "294870": {"name": "HDC현대산업개발", "theme": "건설 대표주", "score": 0},
    "003240": {"name": "태광산업", "theme": "홈쇼핑", "score": 35},
    "023530": {"name": "롯데쇼핑", "theme": "홈쇼핑", "score": 10},
    "057050": {"name": "현대홈쇼핑", "theme": "홈쇼핑", "score": 5},
    "035760": {"name": "CJ ENM", "theme": "홈쇼핑", "score": 5},
    "007070": {"name": "GS리테일", "theme": "홈쇼핑", "score": 0},
    "055550": {"name": "신한지주", "theme": "은행", "score": 10},
    "175330": {"name": "JB금융지주", "theme": "은행", "score": 0},
    "138930": {"name": "BNK금융지주", "theme": "은행", "score": 0},
    "024110": {"name": "기업은행", "theme": "은행", "score": 0},
    "139130": {"name": "iM금융지주", "theme": "은행", "score": 0},
    "002020": {"name": "코오롱", "theme": "두나무", "score": 20},
    "120110": {"name": "코오롱인더", "theme": "두나무", "score": 5},
    "003530": {"name": "한화투자증권", "theme": "두나무", "score": 0},
    "246690": {"name": "TS인베스트먼트", "theme": "두나무", "score": 0},
    "027830": {"name": "대성창투", "theme": "두나무", "score": 0},
    "000810": {"name": "삼성화재", "theme": "손해보험", "score": 30},
    "005830": {"name": "DB손해보험", "theme": "손해보험", "score": 10},
    "000370": {"name": "한화손해보험", "theme": "손해보험", "score": 0},
    "001450": {"name": "현대해상", "theme": "손해보험", "score": 0},
    "000660": {"name": "SK하이닉스", "theme": "IT 대표주", "score": 30},
    "004170": {"name": "신세계", "theme": "백화점", "score": 25},
    "017670": {"name": "SK텔레콤", "theme": "통신", "score": 20},
}

THEME_CODES = list(THEME_STOCKS.keys())


@dataclass
class Position:
    code: str
    name: str
    theme: str
    strategy: str
    entry_price: float
    quantity: int
    entry_time: str
    entry_bar_idx: int
    partial_sold: bool = False
    original_quantity: int = 0


@dataclass
class Trade:
    code: str
    name: str
    theme: str
    strategy: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    reason: str
    entry_time: str
    exit_time: str


def load_data():
    """DB에서 데이터 로드"""
    from sqlalchemy import create_engine
    db_url = os.getenv("DATABASE_URL")
    engine = create_engine(db_url)

    logger.info("데이터 로딩...")

    # 5분봉 (테마 종목만)
    placeholders = ",".join(f"'{c}'" for c in THEME_CODES)
    intraday_df = pd.read_sql(f"""
        SELECT code, datetime, open, high, low, close, volume
        FROM ohlcv_intraday
        WHERE code IN ({placeholders})
        ORDER BY code, datetime
    """, engine)
    intraday_df["datetime"] = pd.to_datetime(intraday_df["datetime"])
    intraday_df["date"] = intraday_df["datetime"].dt.date

    # 일봉 (테마 종목 + ki 점수용)
    daily_df = pd.read_sql(f"""
        SELECT code, date, open, high, low, close, volume
        FROM ohlcv_daily
        WHERE code IN ({placeholders})
        ORDER BY code, date
    """, engine)
    daily_df["date"] = pd.to_datetime(daily_df["date"]).dt.date

    logger.info(f"5분봉: {len(intraday_df):,}행, 일봉: {len(daily_df):,}행")

    return intraday_df, daily_df


def calculate_ki_score(daily_df: pd.DataFrame, code: str, target_date) -> float:
    """끼 점수 계산 (일봉 기반)"""
    stock_daily = daily_df[daily_df["code"] == code].copy()
    stock_daily = stock_daily[stock_daily["date"] < target_date].tail(90)

    if len(stock_daily) < 20:
        return 0

    opens = stock_daily["open"].values
    closes = stock_daily["close"].values
    volumes = stock_daily["volume"].values

    # 일간 등락률
    mask = opens > 0
    daily_gains = np.zeros(len(opens))
    daily_gains[mask] = ((closes[mask] - opens[mask]) / opens[mask]) * 100

    max_gain = np.max(daily_gains) if len(daily_gains) > 0 else 0
    avg_volume = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
    max_volume = np.max(volumes) if len(volumes) > 0 else 0

    volume_ratio = max_volume / avg_volume if avg_volume > 0 else 0

    # 끼 점수: 최대 등락률 + 거래량 비율 조합
    ki = min(max_gain * 5 + volume_ratio * 3, 100)
    return round(ki, 1)


def classify_daily_position(daily_df: pd.DataFrame, code: str, target_date) -> str:
    """일봉 자리 분류"""
    stock_daily = daily_df[daily_df["code"] == code].copy()
    stock_daily = stock_daily[stock_daily["date"] < target_date].tail(120)

    if len(stock_daily) < 20:
        return "해당없음"

    closes = stock_daily["close"].values
    highs = stock_daily["high"].values

    current = closes[-1]
    high_52w = np.max(highs) if len(highs) > 0 else current
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else np.mean(closes)

    # 신고가
    if current >= high_52w * 0.97:
        return "신고가"
    # 전고점 돌파
    recent_high = np.max(highs[-60:]) if len(highs) >= 60 else np.max(highs)
    if current >= recent_high * 0.95:
        return "전고점돌파"
    # 빈집 (MA 위에서 조정)
    if current > ma20 and current > ma60:
        return "빈집"
    # 바닥 반등
    if current < ma60 and current > closes[-5:].min() * 1.02:
        return "바닥반등"

    return "해당없음"


def detect_entry_signal(bars: pd.DataFrame, bar_idx: int, ki: float, position: str) -> dict | None:
    """진입 시그널 감지"""
    if bar_idx < 5:
        return None

    bar = bars.iloc[bar_idx]
    prev_bars = bars.iloc[max(0, bar_idx - 5):bar_idx]

    # 시간 필터: 9:05 ~ 11:00
    bar_time = bar["datetime"]
    if hasattr(bar_time, "hour"):
        h, m = bar_time.hour, bar_time.minute
    else:
        bar_time = pd.Timestamp(bar_time)
        h, m = bar_time.hour, bar_time.minute

    if h < 9 or (h == 9 and m < 5):
        return None
    if h >= 11:
        return None

    price = bar["close"]
    volume = bar["volume"]

    if price <= 0 or volume <= 0:
        return None

    # 거래량 급증 체크
    avg_vol = prev_bars["volume"].mean()
    if avg_vol <= 0:
        return None
    vol_ratio = volume / avg_vol

    if vol_ratio < 1.5:
        return None

    # 양봉 확인
    if bar["close"] <= bar["open"]:
        return None

    # 변동률 체크 (전봉 대비)
    prev_close = prev_bars.iloc[-1]["close"]
    if prev_close <= 0:
        return None
    change_pct = (price - prev_close) / prev_close * 100

    if change_pct < 0.3:  # 최소 0.3% 이상 상승
        return None

    # 돌파 매매: 직전 5봉 고가 돌파 + 거래량 급증
    recent_high = prev_bars["high"].max()
    if price > recent_high and vol_ratio >= 2.0:
        confidence = min(0.5 + (ki / 200) + (vol_ratio - 2) * 0.1, 0.95)
        if position in ("신고가", "전고점돌파", "빈집"):
            confidence += 0.1
        return {
            "method": "돌파매매",
            "confidence": min(confidence, 0.95),
            "reason": f"5봉 고가돌파 + 거래량 {vol_ratio:.1f}배"
        }

    # 눌림 매매: 직전 상승 후 눌림에서 반등
    if len(prev_bars) >= 3:
        prev3 = prev_bars.tail(3)
        if prev3.iloc[0]["close"] > prev3.iloc[1]["close"] < prev3.iloc[2]["close"]:
            # V자 반등 + 거래량
            if vol_ratio >= 1.5:
                confidence = min(0.4 + (ki / 200), 0.85)
                if position in ("빈집", "바닥반등"):
                    confidence += 0.1
                return {
                    "method": "눌림매매",
                    "confidence": min(confidence, 0.95),
                    "reason": f"V자 반등 + 거래량 {vol_ratio:.1f}배"
                }

    return None


def run_theme_backtest():
    """오늘 핫테마 종목으로 백테스트"""
    intraday_df, daily_df = load_data()

    # 거래일 목록
    dates = sorted(intraday_df["date"].unique())
    logger.info(f"거래일: {len(dates)}일 ({dates[0]} ~ {dates[-1]})")

    # 그룹핑
    daily_by_code = {code: g for code, g in daily_df.groupby("code")}
    intraday_by_date = {d: g for d, g in intraday_df.groupby("date")}

    # 백테스트 설정
    INIT_CAPITAL = 10_000_000
    MAX_POSITIONS = 5
    SL_PCT = -4.0
    TP_PCT = 5.0
    PARTIAL_SELL_RATIO = 0.7  # 70% 분할매도
    COMMISSION = 0.00015  # 매수 수수료
    TAX = 0.0023  # 매도 세금
    MAX_CONSECUTIVE_LOSS = 2

    cash = INIT_CAPITAL
    positions: dict[str, Position] = {}
    all_trades: list[Trade] = []
    equity_curve = []
    daily_pnl_list = []

    # 통계
    total_signals = 0
    total_entries = 0
    consecutive_losses = 0
    day_stopped_count = 0

    for day_idx, trade_date in enumerate(dates):
        day_bars = intraday_by_date.get(trade_date)
        if day_bars is None or day_bars.empty:
            continue

        day_cash_start = cash
        day_trades = []
        day_stopped = False

        # 이 날의 테마 종목 5분봉
        for code in THEME_CODES:
            if code not in THEME_STOCKS:
                continue

            stock_bars = day_bars[day_bars["code"] == code].sort_values("datetime").reset_index(drop=True)
            if stock_bars.empty or len(stock_bars) < 5:
                continue

            info = THEME_STOCKS[code]
            name = info["name"]
            theme = info["theme"]

            # Ki점수 & 일봉 자리 (하루에 한번)
            ki = calculate_ki_score(daily_df, code, trade_date)
            position_type = classify_daily_position(daily_df, code, trade_date)

            for bar_idx in range(len(stock_bars)):
                bar = stock_bars.iloc[bar_idx]

                # ── 포지션 모니터 ──
                if code in positions:
                    pos = positions[code]
                    current_price = bar["close"]
                    pnl_pct = (current_price - pos.entry_price) / pos.entry_price * 100

                    should_close = False
                    close_reason = ""
                    close_qty = pos.quantity

                    # 분할 익절: +5% → 70% 매도
                    if pnl_pct >= TP_PCT and not pos.partial_sold:
                        sell_qty = int(pos.quantity * PARTIAL_SELL_RATIO)
                        if sell_qty > 0:
                            pnl_amt = (current_price - pos.entry_price) * sell_qty
                            pnl_amt -= current_price * sell_qty * (TAX + COMMISSION)
                            cash += current_price * sell_qty * (1 - TAX - COMMISSION)

                            all_trades.append(Trade(
                                code=code, name=name, theme=theme,
                                strategy=pos.strategy, entry_price=pos.entry_price,
                                exit_price=current_price, quantity=sell_qty,
                                pnl=pnl_amt, pnl_pct=pnl_pct, reason="1차익절",
                                entry_time=pos.entry_time,
                                exit_time=str(bar["datetime"]),
                            ))
                            day_trades.append(all_trades[-1])
                            pos.quantity -= sell_qty
                            pos.partial_sold = True
                            consecutive_losses = 0
                            continue

                    # 본전컷: partial_sold 후 원가 복귀
                    if pos.partial_sold and pnl_pct <= 0.5:
                        should_close = True
                        close_reason = "본전컷"
                        close_qty = pos.quantity

                    # 손절: -4%
                    if pnl_pct <= SL_PCT:
                        should_close = True
                        close_reason = "손절"
                        close_qty = pos.quantity

                    # 장마감 (마지막 봉)
                    if bar_idx >= len(stock_bars) - 2:
                        if code in positions:
                            should_close = True
                            close_reason = "장마감"
                            close_qty = pos.quantity

                    if should_close and code in positions:
                        pnl_amt = (current_price - pos.entry_price) * close_qty
                        pnl_amt -= current_price * close_qty * (TAX + COMMISSION)
                        cash += current_price * close_qty * (1 - TAX - COMMISSION)

                        all_trades.append(Trade(
                            code=code, name=name, theme=theme,
                            strategy=pos.strategy, entry_price=pos.entry_price,
                            exit_price=current_price, quantity=close_qty,
                            pnl=pnl_amt, pnl_pct=pnl_pct, reason=close_reason,
                            entry_time=pos.entry_time,
                            exit_time=str(bar["datetime"]),
                        ))
                        day_trades.append(all_trades[-1])

                        if close_reason == "손절":
                            consecutive_losses += 1
                            if consecutive_losses >= MAX_CONSECUTIVE_LOSS:
                                day_stopped = True
                                day_stopped_count += 1
                        elif close_reason in ("1차익절",):
                            consecutive_losses = 0

                        del positions[code]
                    continue

                # ── 진입 시그널 ──
                if day_stopped:
                    continue
                if code in positions:
                    continue
                if len(positions) >= MAX_POSITIONS:
                    continue

                signal = detect_entry_signal(stock_bars, bar_idx, ki, position_type)
                if signal is None:
                    continue

                total_signals += 1

                if signal["confidence"] < 0.5:
                    continue

                # 포지션 사이징 (끼 기반)
                price = bar["close"]
                if ki >= 60 and signal["confidence"] >= 0.7:
                    alloc_pct = 0.12  # 확신종목: 12%
                elif ki >= 40:
                    alloc_pct = 0.06  # 보통: 6%
                else:
                    alloc_pct = 0.03  # 애매: 3%

                invest_amount = cash * alloc_pct
                quantity = int(invest_amount / price)
                if quantity <= 0:
                    continue

                cost = price * quantity * (1 + COMMISSION)
                if cost > cash:
                    continue

                # 매수 실행
                cash -= cost
                positions[code] = Position(
                    code=code, name=name, theme=theme,
                    strategy=f"홍스타일_{signal['method']}",
                    entry_price=price, quantity=quantity,
                    entry_time=str(bar["datetime"]),
                    entry_bar_idx=bar_idx,
                    original_quantity=quantity,
                )
                total_entries += 1

        # 일말 정리: 남은 포지션 강제 청산 (안전)
        for code in list(positions.keys()):
            pos = positions[code]
            stock_bars = day_bars[day_bars["code"] == code].sort_values("datetime")
            if stock_bars.empty:
                continue
            last_price = stock_bars.iloc[-1]["close"]
            pnl_pct = (last_price - pos.entry_price) / pos.entry_price * 100
            pnl_amt = (last_price - pos.entry_price) * pos.quantity
            pnl_amt -= last_price * pos.quantity * (TAX + COMMISSION)
            cash += last_price * pos.quantity * (1 - TAX - COMMISSION)

            all_trades.append(Trade(
                code=code, name=pos.name, theme=pos.theme,
                strategy=pos.strategy, entry_price=pos.entry_price,
                exit_price=last_price, quantity=pos.quantity,
                pnl=pnl_amt, pnl_pct=pnl_pct, reason="장마감",
                entry_time=pos.entry_time,
                exit_time=str(stock_bars.iloc[-1]["datetime"]),
            ))
            day_trades.append(all_trades[-1])
            del positions[code]

        # 일별 자산 기록
        equity = cash
        day_pnl = sum(t.pnl for t in day_trades)
        equity_curve.append({"date": trade_date, "equity": equity})
        daily_pnl_list.append({"date": trade_date, "pnl": day_pnl, "trades": len(day_trades)})

        if (day_idx + 1) % 10 == 0:
            logger.info(
                f"  [{day_idx+1}/{len(dates)}] {trade_date} | "
                f"자산={equity:,.0f} | 거래={len(day_trades)} | "
                f"PnL={day_pnl:+,.0f}"
            )

    # ═══ 결과 집계 ═══
    final_equity = cash
    total_return = (final_equity - INIT_CAPITAL) / INIT_CAPITAL * 100
    total_pnl = final_equity - INIT_CAPITAL

    sell_trades = [t for t in all_trades if t.reason != "매수"]
    wins = [t for t in sell_trades if t.pnl > 0]
    losses = [t for t in sell_trades if t.pnl <= 0]
    win_rate = len(wins) / len(sell_trades) * 100 if sell_trades else 0
    avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.pnl_pct for t in losses]) if losses else 0

    # 최대 낙폭
    peak = INIT_CAPITAL
    max_dd = 0
    for e in equity_curve:
        peak = max(peak, e["equity"])
        dd = (peak - e["equity"]) / peak * 100
        max_dd = max(max_dd, dd)

    # 테마별 집계
    theme_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
    for t in sell_trades:
        theme_stats[t.theme]["trades"] += 1
        if t.pnl > 0:
            theme_stats[t.theme]["wins"] += 1
        theme_stats[t.theme]["pnl"] += t.pnl

    # 전략별 집계
    strategy_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
    for t in sell_trades:
        strategy_stats[t.strategy]["trades"] += 1
        if t.pnl > 0:
            strategy_stats[t.strategy]["wins"] += 1
        strategy_stats[t.strategy]["pnl"] += t.pnl

    # 청산 사유별
    reason_stats = defaultdict(lambda: {"trades": 0, "pnl": 0})
    for t in sell_trades:
        reason_stats[t.reason]["trades"] += 1
        reason_stats[t.reason]["pnl"] += t.pnl

    # ═══ 출력 ═══
    print("\n" + "=" * 70)
    print("  홍인기 전략 백테스트 (오늘 핫테마 종목 기반)")
    print("=" * 70)
    print(f"\n  핫테마: 건설대표주, 홈쇼핑, 은행, 두나무, 손해보험, IT대표주, 백화점, 통신")
    print(f"  대상 종목: {len(THEME_STOCKS)}개 (실제 테마 분석 결과)")
    print(f"  기간: {len(dates)}거래일 ({dates[0]} ~ {dates[-1]})")
    print(f"  초기자본:      {INIT_CAPITAL:>12,}원")
    print(f"  최종자산:      {final_equity:>12,.0f}원")
    print(f"  총수익률:      {total_return:>+11.2f}%")
    print(f"  총손익:        {total_pnl:>+12,.0f}원")

    print(f"\n  ── 거래 통계 ──")
    print(f"  시그널 수:  {total_signals}건 (conf>=0.5 통과)")
    print(f"  진입 수:    {total_entries}건")
    print(f"  청산 수:    {len(sell_trades)}건")
    print(f"  승리:       {len(wins)}건")
    print(f"  패배:       {len(losses)}건")
    print(f"  승률:       {win_rate:.1f}%")
    print(f"  평균 수익:  {avg_win:+.2f}%")
    print(f"  평균 손실:  {avg_loss:+.2f}%")
    print(f"  최대낙폭:   {max_dd:.2f}%")
    print(f"  당일종료:   {day_stopped_count}일 (2연속 손절)")

    print(f"\n  ── 테마별 성과 ──")
    for theme, st in sorted(theme_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = st["wins"] / st["trades"] * 100 if st["trades"] > 0 else 0
        print(f"    {theme:>12s}: {st['trades']:>3}건 | 승률 {wr:5.1f}% | PnL {st['pnl']:>+12,.0f}원")

    print(f"\n  ── 전략별 성과 ──")
    for strat, st in sorted(strategy_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = st["wins"] / st["trades"] * 100 if st["trades"] > 0 else 0
        print(f"    {strat:>16s}: {st['trades']:>3}건 | 승률 {wr:5.1f}% | PnL {st['pnl']:>+12,.0f}원")

    print(f"\n  ── 청산 사유별 ──")
    for reason, st in sorted(reason_stats.items(), key=lambda x: x[1]["trades"], reverse=True):
        print(f"    {reason:>10s}: {st['trades']:>3}건 | PnL {st['pnl']:>+12,.0f}원")

    # 최근 10일 일별 PnL
    print(f"\n  ── 최근 일별 PnL ──")
    for dp in daily_pnl_list[-15:]:
        eq = [e["equity"] for e in equity_curve if e["date"] == dp["date"]]
        eq_val = eq[0] if eq else 0
        marker = " ★" if dp["pnl"] > 0 else ""
        print(f"    {dp['date']}: 거래 {dp['trades']:>2}건 | PnL {dp['pnl']:>+10,.0f}원 | 자산 {eq_val:>12,.0f}원{marker}")

    # 비교 요약
    print(f"\n  ── 기존 proxy 백테스트 비교 ──")
    print(f"    거래대금 Top30 proxy: -14.11% (338건, WR 44.1%)")
    print(f"    오늘 핫테마 종목:     {total_return:+.2f}% ({len(sell_trades)}건, WR {win_rate:.1f}%)")
    diff = total_return - (-14.11)
    print(f"    차이:                 {diff:+.2f}%p")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_theme_backtest()
