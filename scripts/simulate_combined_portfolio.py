#!/usr/bin/env python3
"""3개 전략 통합 포트폴리오 시뮬레이션
  - 데이터드리븐 전략 1 (morning_rsi_neutral_atr)
  - 데이터드리븐 전략 3 (modified_rsi_neutral_atr)
  - 경윤 전략 (홍인기 돌파/눌림매매)

공유 자본금, 동시 보유 제한, confidence순 진입.
20일/60일 기준 각각 결과 출력.

실행:
  python scripts/simulate_combined_portfolio.py
"""

import copy
import sys
import time as time_module
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

from sqlalchemy import text
from src.database.connection import get_backtest_engine as get_engine
from src.strategies.data_driven import get_data_driven_strategies
from src.strategies.data_driven.daily_context import DailyContextLoader
from src.strategies.hongstyle.daily_chart_analyzer import DailyChartAnalyzer
from src.strategies.hongstyle.pattern_detector import PatternDetector
from src.strategies.hongstyle.signal_generator import SignalGenerator

# ── 설정 ──
INITIAL_CAPITAL = 10_000_000
MAX_POSITIONS = 3
DD_POSITION_PCT = 0.30         # 데이터드리븐: 자본의 30%
HONG_HIGH_PCT = 0.15           # 경윤 확신: 15% (원본 동일)
HONG_LOW_PCT = 0.05            # 경윤 보통: 5% (원본 동일)
HONG_CONFIDENCE_THRESHOLD = 0.7
HONG_MIN_CONFIDENCE = 0.6      # 원본 동일 (0.5→0.6)
COMMISSION_RATE = 0.00015
TAX_RATE = 0.0023
FORCE_CLOSE_TIME = time(15, 20)
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)

# 경윤 전략 설정
HONG_SCAN_START = time(9, 30)
HONG_SCAN_END = time(11, 0)
HONG_SL = 0.04
HONG_TP = 0.05
HONG_PARTIAL_RATIO = 0.7
HONG_BREAKEVEN_CUT = 0.005
HONG_LEADER_TOP_N = 30
HONG_MAX_CONSECUTIVE_LOSSES = 2  # 2연속 손절 → 당일 경윤 종료

# 경윤 필터 (gylee_runner 동일)
HONG_MIN_CAP_BIL = 5000         # 시총 5000억+
HONG_MIN_INST_BIL = 50          # 기관순매수 50억+
HONG_MAX_INST_BIL = 200         # 기관순매수 200억 이하
HONG_ONLY_DOLPA = True          # 돌파매매만 (눌림매매 제외)


@dataclass
class Position:
    code: str
    strategy_name: str
    entry_price: float
    entry_time: object
    quantity: int
    invested: float
    stop_loss_price: float
    take_profit_price: float
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    partial_sold: bool = False
    original_quantity: int = 0


@dataclass
class Trade:
    code: str
    strategy_name: str
    entry_price: float
    exit_price: float
    entry_time: object
    exit_time: object
    quantity: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    commission_total: float


def load_all_data():
    """DB에서 5분봉 + 일봉 데이터 로드."""
    engine = get_engine()

    with engine.connect() as conn:
        # 5분봉
        codes = [r[0] for r in conn.execute(text(
            "SELECT code FROM ohlcv_intraday GROUP BY code HAVING COUNT(*) >= 100"
        )).fetchall()]

    intraday_data = {}
    with engine.connect() as conn:
        for code in codes:
            rows = conn.execute(text(
                "SELECT datetime, open, high, low, close, volume "
                "FROM ohlcv_intraday WHERE code = :code ORDER BY datetime"
            ), {"code": code}).fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
                df = df.astype({c: float for c in ["open", "high", "low", "close", "volume"]})
                intraday_data[code] = df

    # 일봉 (홍인기 분석용)
    all_dates = sorted(set(d for df in intraday_data.values() for d in df.index.date))
    daily_start = min(all_dates) - timedelta(days=200) if all_dates else date.today() - timedelta(days=260)

    daily_grouped = {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT code, date, open, high, low, close, volume, value, change_rate
            FROM ohlcv_daily WHERE date >= :start ORDER BY code, date
        """), {"start": daily_start}).fetchall()

        df = pd.DataFrame(rows, columns=["code", "date", "open", "high", "low", "close", "volume", "value", "change_rate"])
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for col in ["open", "high", "low", "close", "volume", "value", "change_rate"]:
            df[col] = df[col].astype(float)

        for code, grp in df.groupby("code"):
            daily_grouped[code] = grp.sort_values("date").reset_index(drop=True)

    return intraday_data, daily_grouped, all_dates


def get_hong_entry_candidates(daily_grouped, trading_date, daily_analyzer, pattern_detector, signal_generator, daily_context=None):
    """홍인기/경윤 전략의 일일 진입 후보 생성 (시총/기관 필터 포함)."""
    # 대장주 선정 (거래대금 프록시)
    scores = []
    for code, df in daily_grouped.items():
        mask = df["date"] < trading_date
        recent = df[mask].tail(5)
        if len(recent) < 3:
            continue
        last = recent.iloc[-1]
        value = last["close"] * last["volume"]
        change = last["change_rate"]
        if change > 0 and value > 0:
            score = value * (1 + change / 100)
            scores.append((code, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    leaders = {code for code, _ in scores[:HONG_LEADER_TOP_N]}

    candidates = []
    for code in leaders:
        # ── 경윤 필터 1: 시총 5000억+ ──
        ctx = None
        if daily_context and code in daily_context:
            ctx = daily_context[code].get(trading_date)
        if ctx:
            if ctx.market_cap_bil < HONG_MIN_CAP_BIL:
                continue
            # ── 경윤 필터 2: 전일 기관 순매수 50~200억 ──
            if ctx.inst_net_buy_bil is not None:
                if not (HONG_MIN_INST_BIL <= ctx.inst_net_buy_bil <= HONG_MAX_INST_BIL):
                    continue

        df = daily_grouped.get(code)
        if df is None:
            continue
        mask = df["date"] < trading_date
        daily_bars = df[mask].tail(120)
        if len(daily_bars) < 20:
            continue

        daily_position = daily_analyzer.classify_daily_position(daily_bars)
        ki_score = daily_analyzer.calculate_ki(daily_bars)

        patterns = pattern_detector.detect_all_patterns(
            minute_bars=None, daily_bars=daily_bars,
            ki_score=ki_score.score, is_leading_sector=True, has_news_catalyst=False,
        )

        signal = signal_generator.generate_entry_signal(
            stock_code=code, daily_position=daily_position,
            ki_score=ki_score, patterns=patterns, is_leader=True,
        )

        if signal.action == "buy" and signal.confidence >= HONG_MIN_CONFIDENCE:
            # ── 경윤 필터 3: 돌파매매만 ──
            if HONG_ONLY_DOLPA and signal.method != "돌파매매":
                continue
            candidates.append({
                "code": code,
                "signal": signal,
                "ki_score": ki_score.score,
                "confidence": signal.confidence,
                "method": signal.method,
            })

    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    return candidates


def close_position(pos, exit_price, exit_time, reason):
    """포지션 청산."""
    sell_value = exit_price * pos.quantity
    sell_comm = sell_value * COMMISSION_RATE
    sell_tax = sell_value * TAX_RATE
    buy_comm = pos.entry_price * pos.quantity * COMMISSION_RATE
    total_comm = buy_comm + sell_comm + sell_tax

    net_pnl = (exit_price - pos.entry_price) * pos.quantity - total_comm
    pnl_pct = (exit_price / pos.entry_price - 1) * 100 if pos.entry_price > 0 else 0

    # 매도 후 받는 금액
    cash_back = sell_value - sell_comm - sell_tax

    return Trade(
        code=pos.code, strategy_name=pos.strategy_name,
        entry_price=pos.entry_price, exit_price=exit_price,
        entry_time=pos.entry_time, exit_time=exit_time,
        quantity=pos.quantity, pnl=net_pnl, pnl_pct=pnl_pct,
        exit_reason=reason, commission_total=total_comm,
    ), cash_back


def run_combined_simulation(intraday_data, daily_grouped, daily_context, n_days=None):
    """3개 전략 통합 시뮬레이션."""

    # 날짜 그룹핑
    date_code_df = {}
    all_dates_set = set()
    for code, df in intraday_data.items():
        for dt, day_df in df.groupby(df.index.date):
            all_dates_set.add(dt)
            if dt not in date_code_df:
                date_code_df[dt] = {}
            date_code_df[dt][code] = day_df

    all_dates = sorted(all_dates_set)
    if n_days and n_days < len(all_dates):
        all_dates = all_dates[-n_days:]

    # 전략 초기화
    dd_strategies = get_data_driven_strategies()
    for s in dd_strategies:
        s.HONG_MIN_INST_BIL = -999999
        s.HONG_MAX_INST_BIL = 999999

    daily_analyzer = DailyChartAnalyzer()
    pattern_detector = PatternDetector()
    signal_generator = SignalGenerator()

    # 상태
    capital = float(INITIAL_CAPITAL)
    positions = {}
    all_trades = []
    daily_records = []

    for current_date in tqdm(all_dates, desc="시뮬레이션", leave=False):
        day_data = date_code_df.get(current_date)
        if not day_data:
            continue

        day_pnl = 0.0
        day_trades_count = 0

        # ── 데이터드리븐 지표 사전 계산 ──
        dd_indicators = {}
        dd_ts_to_idx = {}
        for si, strategy in enumerate(dd_strategies):
            dd_indicators[si] = {}
            dd_ts_to_idx[si] = {}
            for code, day_df in day_data.items():
                ctx = None
                if daily_context and code in daily_context:
                    ctx = daily_context[code].get(current_date)
                strategy.set_daily_context(code, current_date, ctx)
                ind = strategy.precompute_day(day_df)
                dd_indicators[si][code] = ind
                dd_ts_to_idx[si][code] = {ts: i for i, ts in enumerate(ind["timestamps"])}

        # ── 경윤 전략 일일 분석 ──
        hong_candidates = get_hong_entry_candidates(
            daily_grouped, current_date, daily_analyzer, pattern_detector, signal_generator,
            daily_context=daily_context,
        )
        hong_entered_today = set()
        hong_consecutive_losses = 0
        hong_day_stopped = False

        # ── 봉별 순회 ──
        all_ts = sorted(set(ts for day_df in day_data.values() for ts in day_df.index.tolist()))

        for ts in all_ts:
            ct = ts.time() if hasattr(ts, 'time') else ts
            if not hasattr(ct, 'hour') or ct < MARKET_OPEN or ct > MARKET_CLOSE:
                continue

            # ── 강제 청산 ──
            if ct >= FORCE_CLOSE_TIME:
                for code in list(positions.keys()):
                    price = _get_price_at(code, ts, dd_indicators, dd_ts_to_idx, day_data)
                    if price is None:
                        continue
                    trade, cash_back = close_position(positions[code], price, ts, "장마감")
                    all_trades.append(trade)
                    capital += cash_back
                    day_pnl += trade.pnl
                    day_trades_count += 1
                    del positions[code]
                continue

            # ── 보유 포지션 SL/TP 체크 ──
            for code in list(positions.keys()):
                pos = positions[code]
                price_data = _get_hlc_at(code, ts, dd_indicators, dd_ts_to_idx, day_data)
                if price_data is None:
                    continue
                low_val, high_val, close_val = price_data

                is_hong = pos.strategy_name.startswith("경윤_")

                if is_hong and pos.partial_sold:
                    # 본전컷 체크
                    pnl_ratio = (close_val - pos.entry_price) / pos.entry_price
                    if pnl_ratio <= HONG_BREAKEVEN_CUT:
                        trade, cash_back = close_position(pos, close_val, ts, "본전컷")
                        all_trades.append(trade)
                        capital += cash_back
                        day_pnl += trade.pnl
                        day_trades_count += 1
                        del positions[code]
                        continue

                if is_hong and not pos.partial_sold and high_val >= pos.take_profit_price:
                    # 경윤 분할매도 (70%)
                    sell_qty = int(pos.original_quantity * HONG_PARTIAL_RATIO)
                    if sell_qty > 0 and sell_qty < pos.quantity:
                        sell_value = pos.take_profit_price * sell_qty
                        sell_comm = sell_value * COMMISSION_RATE
                        sell_tax = sell_value * TAX_RATE
                        buy_comm = pos.entry_price * sell_qty * COMMISSION_RATE
                        net_pnl = (pos.take_profit_price - pos.entry_price) * sell_qty - buy_comm - sell_comm - sell_tax
                        cash_back = sell_value - sell_comm - sell_tax

                        partial_trade = Trade(
                            code=code, strategy_name=pos.strategy_name,
                            entry_price=pos.entry_price, exit_price=pos.take_profit_price,
                            entry_time=pos.entry_time, exit_time=ts,
                            quantity=sell_qty, pnl=net_pnl,
                            pnl_pct=(pos.take_profit_price / pos.entry_price - 1) * 100,
                            exit_reason="1차익절", commission_total=buy_comm + sell_comm + sell_tax,
                        )
                        all_trades.append(partial_trade)
                        capital += cash_back
                        day_pnl += net_pnl
                        day_trades_count += 1
                        pos.quantity -= sell_qty
                        pos.partial_sold = True
                        hong_consecutive_losses = 0  # 익절 시 연속손절 리셋
                        continue

                # SL
                if low_val <= pos.stop_loss_price:
                    trade, cash_back = close_position(pos, pos.stop_loss_price, ts, "손절")
                    all_trades.append(trade)
                    capital += cash_back
                    day_pnl += trade.pnl
                    day_trades_count += 1
                    del positions[code]
                    # 경윤 연속 손절 카운트
                    if is_hong:
                        hong_consecutive_losses += 1
                        if hong_consecutive_losses >= HONG_MAX_CONSECUTIVE_LOSSES:
                            hong_day_stopped = True
                    continue

                # TP (데이터드리븐 or 경윤 남은 수량)
                if not is_hong and high_val >= pos.take_profit_price:
                    trade, cash_back = close_position(pos, pos.take_profit_price, ts, "익절")
                    all_trades.append(trade)
                    capital += cash_back
                    day_pnl += trade.pnl
                    day_trades_count += 1
                    del positions[code]
                    continue

            # ── 신규 진입 (3개 전략 통합) ──
            if len(positions) < MAX_POSITIONS:
                pending = []

                # 데이터드리븐 시그널
                for si, strategy in enumerate(dd_strategies):
                    for code in day_data:
                        if code in positions:
                            continue
                        if code not in dd_ts_to_idx[si] or ts not in dd_ts_to_idx[si][code]:
                            continue
                        idx = dd_ts_to_idx[si][code][ts]
                        ind = dd_indicators[si][code]
                        if daily_context and code in daily_context:
                            ctx = daily_context[code].get(current_date)
                            strategy.set_daily_context(code, current_date, ctx)
                        signal = strategy.check_entry_fast(code, idx, ind)
                        if signal:
                            pending.append({
                                "code": code, "confidence": signal.get("confidence", 1.0),
                                "strategy_name": strategy.name, "type": "dd",
                                "sl_pct": signal.get("stop_loss", 0.03),
                                "tp_pct": signal.get("take_profit", 0.05),
                                "si": si, "idx": idx,
                            })

                # 경윤 시그널 (당일 연속손절 종료 아닐 때만)
                if HONG_SCAN_START <= ct <= HONG_SCAN_END and not hong_day_stopped:
                    for cand in hong_candidates:
                        code = cand["code"]
                        if code in positions or code in hong_entered_today:
                            continue
                        if code not in day_data:
                            continue
                        # 현재 시점 가격 확인
                        price = _get_price_at(code, ts, dd_indicators, dd_ts_to_idx, day_data)
                        if price is None or price <= 0:
                            continue
                        pending.append({
                            "code": code, "confidence": cand["confidence"],
                            "strategy_name": f"경윤_{cand['method']}",
                            "type": "hong", "sl_pct": HONG_SL, "tp_pct": HONG_TP,
                            "hong_cand": cand,
                        })

                # confidence 정렬
                pending.sort(key=lambda x: x["confidence"], reverse=True)

                seen = set(positions.keys())
                for p in pending:
                    if len(positions) >= MAX_POSITIONS:
                        break
                    if p["code"] in seen:
                        continue

                    code = p["code"]
                    price = _get_price_at(code, ts, dd_indicators, dd_ts_to_idx, day_data)
                    if price is None or price <= 0:
                        continue

                    # 포지션 사이징
                    total_equity = capital + sum(
                        pos.entry_price * pos.quantity for pos in positions.values()
                    )
                    if p["type"] == "hong":
                        conf = p["confidence"]
                        alloc = HONG_HIGH_PCT if conf >= HONG_CONFIDENCE_THRESHOLD else HONG_LOW_PCT
                    else:
                        alloc = DD_POSITION_PCT

                    invest = total_equity * alloc
                    qty = int(invest / price)
                    if qty <= 0:
                        continue

                    buy_cost = price * qty
                    buy_comm = buy_cost * COMMISSION_RATE
                    total_cost = buy_cost + buy_comm
                    if total_cost > capital:
                        qty = int((capital * 0.99) / price)
                        if qty <= 0:
                            continue
                        buy_cost = price * qty
                        buy_comm = buy_cost * COMMISSION_RATE
                        total_cost = buy_cost + buy_comm

                    capital -= total_cost

                    positions[code] = Position(
                        code=code, strategy_name=p["strategy_name"],
                        entry_price=price, entry_time=ts,
                        quantity=qty, invested=total_cost,
                        stop_loss_price=price * (1 - p["sl_pct"]),
                        take_profit_price=price * (1 + p["tp_pct"]),
                        stop_loss_pct=p["sl_pct"], take_profit_pct=p["tp_pct"],
                        original_quantity=qty,
                    )
                    seen.add(code)
                    if p["type"] == "hong":
                        hong_entered_today.add(code)

        # 장종료 청산
        for code in list(positions.keys()):
            price = _get_last_price(code, dd_indicators, dd_ts_to_idx, day_data)
            if price is None:
                continue
            last_ts = all_ts[-1] if all_ts else ts
            trade, cash_back = close_position(positions[code], price, last_ts, "장마감")
            all_trades.append(trade)
            capital += cash_back
            day_pnl += trade.pnl
            day_trades_count += 1
            del positions[code]

        daily_records.append({
            "date": current_date, "equity": capital,
            "trades": day_trades_count, "pnl": day_pnl,
        })

    return capital, all_trades, daily_records


def _get_price_at(code, ts, dd_indicators, dd_ts_to_idx, day_data):
    """현재 시점 close 가격."""
    for si in dd_indicators:
        if code in dd_ts_to_idx[si] and ts in dd_ts_to_idx[si][code]:
            idx = dd_ts_to_idx[si][code][ts]
            return float(dd_indicators[si][code]["close"][idx])
    # fallback: day_data에서 직접
    if code in day_data:
        df = day_data[code]
        if ts in df.index:
            return float(df.loc[ts, "close"])
        before = df[df.index <= ts]
        if not before.empty:
            return float(before.iloc[-1]["close"])
    return None


def _get_hlc_at(code, ts, dd_indicators, dd_ts_to_idx, day_data):
    """현재 시점 high, low, close."""
    for si in dd_indicators:
        if code in dd_ts_to_idx[si] and ts in dd_ts_to_idx[si][code]:
            idx = dd_ts_to_idx[si][code][ts]
            ind = dd_indicators[si][code]
            return float(ind["low"][idx]), float(ind["high"][idx]), float(ind["close"][idx])
    if code in day_data:
        df = day_data[code]
        if ts in df.index:
            row = df.loc[ts]
            return float(row["low"]), float(row["high"]), float(row["close"])
    return None


def _get_last_price(code, dd_indicators, dd_ts_to_idx, day_data):
    """마지막 종가."""
    for si in dd_indicators:
        if code in dd_indicators[si]:
            ind = dd_indicators[si][code]
            return float(ind["close"][ind["n_bars"] - 1])
    if code in day_data:
        df = day_data[code]
        if not df.empty:
            return float(df.iloc[-1]["close"])
    return None


def print_result(final_capital, trades, daily_records, label):
    """결과 출력."""
    total_pnl = final_capital - INITIAL_CAPITAL
    total_return = (final_capital / INITIAL_CAPITAL - 1) * 100
    n_trades = len(trades)
    n_wins = sum(1 for t in trades if t.pnl > 0)
    wr = n_wins / n_trades * 100 if n_trades else 0
    total_comm = sum(t.commission_total for t in trades)
    n_days = len(daily_records)

    # MDD
    peak = INITIAL_CAPITAL
    max_dd = 0
    for d in daily_records:
        peak = max(peak, d["equity"])
        dd = (d["equity"] - peak) / peak * 100
        max_dd = min(max_dd, dd)

    print(f"\n{'━' * 70}")
    print(f"  [{label}]")
    print(f"{'━' * 70}")
    print(f"  초기자금:     {INITIAL_CAPITAL:>14,}원")
    print(f"  최종자금:     {final_capital:>14,.0f}원")
    print(f"  총 손익:      {total_pnl:>+14,.0f}원 ({total_return:+.2f}%)")
    print(f"  거래비용:     {total_comm:>14,.0f}원")
    print(f"  거래수:       {n_trades:>14}건")
    print(f"  승률:         {wr:>13.1f}%  ({n_wins}W / {n_trades - n_wins}L)")
    print(f"  MDD:          {max_dd:>13.2f}%")
    print(f"  기간:         {n_days:>14}일")

    if n_days > 0:
        daily_ret = total_return / n_days
        monthly = daily_ret * 22
        print(f"  일평균:       {daily_ret:>+13.3f}%")
        print(f"  월 환산:      {monthly:>+13.2f}%  ({total_pnl / n_days * 22:+,.0f}원/월)")

    # 전략별
    strat_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        strat_stats[t.strategy_name]["trades"] += 1
        if t.pnl > 0:
            strat_stats[t.strategy_name]["wins"] += 1
        strat_stats[t.strategy_name]["pnl"] += t.pnl

    print(f"\n  [전략별]")
    print(f"  {'전략':30s} {'거래':>5s} {'승률':>7s} {'손익':>14s}")
    print(f"  {'─' * 58}")
    for name in sorted(strat_stats.keys()):
        s = strat_stats[name]
        swr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
        print(f"  {name:30s} {s['trades']:5d} {swr:6.1f}% {s['pnl']:>+13,.0f}원")

    # 청산사유별
    reason_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for t in trades:
        reason_stats[t.exit_reason]["count"] += 1
        reason_stats[t.exit_reason]["pnl"] += t.pnl

    print(f"\n  [청산사유별]")
    for reason in ["익절", "1차익절", "손절", "본전컷", "장마감", "장마감강제"]:
        if reason in reason_stats:
            r = reason_stats[reason]
            print(f"  {reason:12s}: {r['count']:4d}건 | {r['pnl']:>+13,.0f}원")


def main():
    print("=" * 70)
    print("  3개 전략 통합 포트폴리오 시뮬레이션")
    print(f"  자본금: {INITIAL_CAPITAL:,}원 | 최대 {MAX_POSITIONS}종목")
    print(f"  전략: 데이터드리븐 2개 + 경윤(홍인기) 1개")
    print("=" * 70)

    # 데이터 로드
    print("\n  데이터 로딩 중...")
    t0 = time_module.time()
    intraday_data, daily_grouped, all_dates = load_all_data()
    print(f"  5분봉: {len(intraday_data)}종목, {len(all_dates)}거래일")
    print(f"  일봉: {len(daily_grouped)}종목")
    print(f"  기간: {min(all_dates)} ~ {max(all_dates)}")
    print(f"  로딩 시간: {time_module.time() - t0:.1f}초")

    # 일별 컨텍스트
    print(f"\n  일별 컨텍스트 로딩...")
    codes = list(intraday_data.keys())
    loader = DailyContextLoader()
    daily_context = loader.load(codes, min(all_dates), max(all_dates))
    print(f"  컨텍스트: {sum(len(v) for v in daily_context.values())}건")

    # ── 60일 시뮬레이션 ──
    print(f"\n  [60일 시뮬레이션 시작...]")
    t0 = time_module.time()
    cap_60, trades_60, daily_60 = run_combined_simulation(
        intraday_data, daily_grouped, daily_context, n_days=None
    )
    print(f"  60일 완료: {time_module.time() - t0:.1f}초")
    print_result(cap_60, trades_60, daily_60, f"60일 (전체 {len(daily_60)}일)")

    # ── 20일 시뮬레이션 ──
    print(f"\n  [20일 시뮬레이션 시작...]")
    t0 = time_module.time()
    cap_20, trades_20, daily_20 = run_combined_simulation(
        intraday_data, daily_grouped, daily_context, n_days=20
    )
    print(f"  20일 완료: {time_module.time() - t0:.1f}초")
    print_result(cap_20, trades_20, daily_20, "최근 20일")

    # ── 비교 요약 ──
    ret_20 = (cap_20 / INITIAL_CAPITAL - 1) * 100
    ret_60 = (cap_60 / INITIAL_CAPITAL - 1) * 100
    wr_20 = sum(1 for t in trades_20 if t.pnl > 0) / len(trades_20) * 100 if trades_20 else 0
    wr_60 = sum(1 for t in trades_60 if t.pnl > 0) / len(trades_60) * 100 if trades_60 else 0

    print(f"\n{'━' * 70}")
    print(f"  비교 요약")
    print(f"{'━' * 70}")
    print(f"  {'':25s} {'20일':>15s} {'60일':>15s}")
    print(f"  {'─' * 57}")
    print(f"  {'최종자금':25s} {cap_20:>14,.0f}원 {cap_60:>14,.0f}원")
    print(f"  {'수익률':25s} {ret_20:>+14.2f}% {ret_60:>+14.2f}%")
    print(f"  {'거래수':25s} {len(trades_20):>14}건 {len(trades_60):>14}건")
    print(f"  {'승률':25s} {wr_20:>13.1f}% {wr_60:>13.1f}%")

    if daily_20:
        m20 = ret_20 / len(daily_20) * 22
        print(f"  {'월환산':25s} {m20:>+14.2f}%")
    if daily_60:
        m60 = ret_60 / len(daily_60) * 22
        print(f"  {'월환산':25s} {'':>15s} {m60:>+14.2f}%")

    print(f"\n{'=' * 70}")
    print(f"  완료!")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
