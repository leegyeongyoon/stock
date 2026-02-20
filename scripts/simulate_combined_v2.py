#!/usr/bin/env python3
"""4개 전략 통합 포트폴리오 시뮬레이션 v2

전략:
  1. morning_rsi_neutral_atr (데이터드리븐 #1)
  2. modified_rsi_neutral_atr (데이터드리븐 #3)
  3. opening_gap_reversal (갭 반전 전략 - Hong Strong 기반)
  4. 경윤 v6.2 (품질 점수 기반 돌파/눌림매매)

공유 자본금 1000만원, 최대 3종목 동시보유.

실행:
  python scripts/simulate_combined_v2.py
"""

import sys
import time as time_module
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

warnings.filterwarnings("ignore")

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

from sqlalchemy import text
from src.database.connection import get_backtest_engine as get_engine
from src.strategies.data_driven import get_data_driven_strategies, get_gap_strategy
from src.strategies.data_driven.daily_context import DailyContextLoader

# ══════════════════════════════════════════════════════
#  공통 설정
# ══════════════════════════════════════════════════════
INITIAL_CAPITAL = 10_000_000
MAX_POSITIONS = 3
COMMISSION = 0.00015
TAX = 0.0023

# ── 데이터드리븐 설정 ──
DD_POSITION_PCT = 0.40
DD_SL = 0.03
DD_TP = 0.05

# ── 경윤 v6.2 설정 (simulate_v6_scoring.py 동일) ──
V6_HIGH_CONF_PCT = 0.40
V6_LOW_CONF_PCT = 0.20
V6_MIN_CONFIDENCE = 0.70
V6_MIN_CAP_BIL = 5000
V6_MIN_INST = 50
V6_MAX_INST = 200
V6_SKIP_TOP_N = 1
V6_ENTER_TOP_N = 4
V6_MIN_DAILY_CHANGE = 6.0
V6_MIN_QUALITY = 60
V6_SL = 0.04
V6_TP = 0.05
V6_PARTIAL_RATIO = 0.70
V6_BREAKEVEN_CUT = 0.005
V6_OVERNIGHT_MIN = 60
V6_GAP_DOWN_STOP = -0.03
V6_MAX_CONSEC_LOSS = 2

FORCE_CLOSE_TIME = time(15, 20)


@dataclass
class Position:
    code: str
    strategy_name: str
    entry_price: float
    entry_time: object
    quantity: int
    invested: float
    stop_loss_pct: float
    take_profit_pct: float
    partial_sold: bool = False
    original_quantity: int = 0
    is_overnight: bool = False
    overnight_score: int = 0
    quality_score: int = 0
    entry_date: object = None

    def __post_init__(self):
        if self.original_quantity == 0:
            self.original_quantity = self.quantity


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
    quality_score: int = 0


# ══════════════════════════════════════════════════════
#  데이터 로딩
# ══════════════════════════════════════════════════════
def load_all_data():
    """DB에서 5분봉 + 일봉 로드."""
    engine = get_engine()

    with engine.connect() as conn:
        codes = [r[0] for r in conn.execute(text(
            "SELECT code FROM ohlcv_intraday GROUP BY code HAVING COUNT(*) >= 100"
        )).fetchall()]

    # 5분봉
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

    all_dates = sorted(set(d for df in intraday_data.values() for d in df.index.date))

    # 일봉 (등락률, 거래대금 등)
    daily_start = min(all_dates) - timedelta(days=30) if all_dates else date.today() - timedelta(days=90)
    daily_by_date = {}  # {date: {code: {change_rate, value, ...}}}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT code, date, open, high, low, close, volume, value, change_rate
            FROM ohlcv_daily WHERE date >= :start ORDER BY date
        """), {"start": daily_start}).fetchall()

    for row in rows:
        code, d = row[0], row[1]
        if isinstance(d, datetime):
            d = d.date()
        if d not in daily_by_date:
            daily_by_date[d] = {}
        daily_by_date[d][code] = {
            "open": float(row[2] or 0), "high": float(row[3] or 0),
            "low": float(row[4] or 0), "close": float(row[5] or 0),
            "volume": float(row[6] or 0), "value": float(row[7] or 0),
            "change_rate": float(row[8] or 0),
        }

    return intraday_data, daily_by_date, all_dates


# ══════════════════════════════════════════════════════
#  경윤 v6.2 헬퍼 함수
# ══════════════════════════════════════════════════════
def v6_select_universe(daily_by_date, trading_date):
    """거래대금 TOP100 OR 등락률 >= 3%"""
    day_data = daily_by_date.get(trading_date, {})
    if not day_data:
        return set()

    # 거래대금 순으로 정렬
    by_value = sorted(day_data.items(), key=lambda x: x[1]["value"], reverse=True)
    top100 = {code for code, _ in by_value[:100]}
    strong = {code for code, d in day_data.items() if d["change_rate"] >= 3.0}
    return top100 | strong


def v6_select_leaders(universe, intraday_data, trading_date, eligible_codes):
    """오전 모멘텀 TOP20에서 TOP2~5 선별."""
    scores = []
    for code in eligible_codes:
        if code not in intraday_data:
            continue
        df = intraday_data[code]
        day_df = df[df.index.date == trading_date]
        if day_df.empty:
            continue

        # 오전 09:00~09:30 바
        morning = day_df[(day_df.index.hour == 9) & (day_df.index.minute < 30)]
        if len(morning) < 2:
            continue

        vol_sum = morning["volume"].sum()
        pchg = (morning.iloc[-1]["close"] / morning.iloc[0]["open"] - 1) * 100
        momentum = vol_sum * max(pchg, 0)
        scores.append({"code": code, "momentum": momentum, "pchg": pchg, "vol_sum": vol_sum})

    scores.sort(key=lambda x: x["momentum"], reverse=True)
    top20 = scores[:20]
    # TOP1 스킵, TOP2~5
    filtered = top20[V6_SKIP_TOP_N:V6_SKIP_TOP_N + V6_ENTER_TOP_N]
    return filtered, top20


def v6_find_breakout(day_df):
    """5봉 고점 돌파 + 거래량 1.2x (09:30~11:00)."""
    window = day_df[
        ((day_df.index.hour == 9) & (day_df.index.minute >= 30)) |
        (day_df.index.hour == 10)
    ]
    if len(window) < 6:
        return None

    for i in range(5, len(window)):
        ph = window["high"].iloc[i-5:i].max()
        bar_high = float(window.iloc[i]["high"])
        bar_close = float(window.iloc[i]["close"])
        bar_vol = float(window.iloc[i]["volume"])

        if bar_high > ph and bar_close > ph:
            avg_vol = window["volume"].iloc[i-5:i].mean()
            if avg_vol > 0 and bar_vol >= avg_vol * 1.2:
                return {
                    "price": bar_close,
                    "time": window.index[i],
                    "confidence": 0.75,
                }
    return None


def v6_find_pullback(day_df, vol_median):
    """95% 깊이 눌림 + 오전거래량 >= 중간값 (13:00~14:30)."""
    morning_full = day_df[(day_df.index.hour >= 9) & (day_df.index.hour < 12)]
    if morning_full.empty:
        return None
    morning_vol = morning_full["volume"].sum()
    if morning_vol < vol_median:
        return None

    window = day_df[
        (day_df.index.hour >= 13) & (day_df.index.hour < 15) &
        ~((day_df.index.hour == 14) & (day_df.index.minute > 30))
    ]
    if len(window) < 5:
        return None

    morning = day_df[day_df.index.hour < 12]
    if morning.empty:
        return None

    mh = morning["high"].max()
    ml = morning["low"].min()
    r50 = mh - (mh - ml) * 0.5

    for i in range(2, len(window)):
        bar = window.iloc[i]
        prev = window.iloc[i - 1]
        if (prev["low"] <= mh * 0.95 and
            bar["close"] > prev["close"] and
            bar["close"] > r50 and
            bar["low"] > ml):
            return {
                "price": float(bar["close"]),
                "time": window.index[i],
                "confidence": 0.6,
            }
    return None


def v6_morning_vol_median(intraday_data, trading_date, leader_codes):
    """리더 종목 오전 거래량 중간값."""
    vols = []
    for code in leader_codes:
        if code not in intraday_data:
            continue
        df = intraday_data[code]
        day_df = df[df.index.date == trading_date]
        morning = day_df[(day_df.index.hour >= 9) & (day_df.index.hour < 12)]
        if not morning.empty:
            vols.append(morning["volume"].sum())
    return np.median(vols) if vols else 0


def v6_calc_quality_score(code, day_df, daily_info, daily_ctx, prev_daily_ctx,
                          leader_rank, entry_time=None):
    """v6.2 품질 점수 (100점 만점)."""
    score = 0

    # 1. 시가총액 (15점)
    cap_bil = 0
    if daily_ctx:
        cap_bil = daily_ctx.market_cap_bil
    if cap_bil >= 30000:
        score += 15
    elif cap_bil >= 10000:
        score += 10
    elif cap_bil >= 5000:
        score += 5

    # 2. 기관순매수 - 전일 기준 (15점)
    inst = 0
    if prev_daily_ctx and prev_daily_ctx.inst_net_buy_bil is not None:
        inst = prev_daily_ctx.inst_net_buy_bil
    if inst >= 150:
        score += 15
    elif inst >= 100:
        score += 10
    elif inst >= 50:
        score += 5

    # 3. 당일 등락률 (20점)
    daily_change = daily_info.get("change_rate", 0)
    if daily_change >= 15:
        score += 20
    elif daily_change >= 10:
        score += 15
    elif daily_change >= 6:
        score += 10

    # 4. 오전 등락률 (20점)
    morning_bars = day_df[(day_df.index.hour >= 9) & (day_df.index.hour < 12)]
    morning_change = 0
    if not morning_bars.empty and morning_bars.iloc[0]["open"] > 0:
        morning_change = (morning_bars.iloc[-1]["close"] / morning_bars.iloc[0]["open"] - 1) * 100
    if morning_change >= 15:
        score += 20
    elif morning_change >= 10:
        score += 15
    elif morning_change >= 5:
        score += 10

    # 5. 종가 강도 (20점)
    if entry_time is not None:
        bars_until = day_df[day_df.index <= entry_time]
    else:
        bars_until = day_df
    if not bars_until.empty:
        dh = bars_until["high"].max()
        dl = bars_until["low"].min()
        cc = bars_until.iloc[-1]["close"]
        cs = (cc - dl) / (dh - dl) * 100 if dh > dl else 50
    else:
        cs = 50
    if cs >= 90:
        score += 20
    elif cs >= 75:
        score += 15
    elif cs >= 60:
        score += 10

    # 6. 리더 순위 (10점)
    if leader_rank == 2:
        score += 10
    elif leader_rank == 3:
        score += 7
    elif leader_rank == 4:
        score += 5
    elif leader_rank == 5:
        score += 3

    return score


def v6_evaluate_overnight(code, pos, day_df, daily_info, leaders_top5):
    """오버나잇 홀딩 평가 (100점)."""
    if day_df.empty:
        return 0, False

    current_price = float(day_df.iloc[-1]["close"])
    pnl_pct = (current_price / pos.entry_price - 1) * 100
    if pnl_pct < 0:
        return 0, False

    # 가분수 체크
    dh = day_df["high"].max()
    do = float(day_df.iloc[0]["open"])
    dl = day_df["low"].min()
    if current_price < do and (dh - current_price) > (current_price - dl) * 2:
        return 0, False

    # 거래량 고점 체크
    morning = day_df[(day_df.index.hour >= 9) & (day_df.index.hour < 12)]
    afternoon = day_df[(day_df.index.hour >= 12) & (day_df.index.hour < 16)]
    if not morning.empty and not afternoon.empty:
        mv = morning["volume"].sum()
        av = afternoon["volume"].sum()
        if mv > 0 and av < mv * 0.3:
            return 0, False

    score = 0

    # 끼 추정
    chg = daily_info.get("change_rate", 0)
    ki_est = max(0, min(chg * 5 + 30, 100))
    if ki_est >= 50:
        score += 30
    elif ki_est >= 40:
        score += 20
    elif ki_est >= 30:
        score += 10

    # 대장주 여부
    if code in leaders_top5:
        rank = leaders_top5.index(code) + 1
        score += 20 if rank <= 2 else 15 if rank <= 3 else 10

    # 등락률
    if chg >= 10:
        score += 20
    elif chg >= 5:
        score += 15
    elif chg >= 3:
        score += 10

    # D+1 후보
    if chg >= 5:
        score += 15
    elif chg >= 3:
        score += 10

    # 오후 거래량
    if not morning.empty and not afternoon.empty and morning["volume"].sum() > 0:
        vr = afternoon["volume"].sum() / morning["volume"].sum()
        if vr >= 0.8:
            score += 15
        elif vr >= 0.6:
            score += 10
        elif vr >= 0.4:
            score += 5

    return score, score >= V6_OVERNIGHT_MIN


# ══════════════════════════════════════════════════════
#  거래 실행 헬퍼
# ══════════════════════════════════════════════════════
def calc_cost(price, qty, side="buy"):
    value = price * qty
    cost = value * COMMISSION
    if side == "sell":
        cost += value * TAX
    return cost


def close_position(pos, exit_price, exit_time, reason):
    sell_value = exit_price * pos.quantity
    sell_cost = calc_cost(exit_price, pos.quantity, "sell")
    buy_cost = calc_cost(pos.entry_price, pos.quantity, "buy")
    total_comm = buy_cost + sell_cost

    pnl = (exit_price - pos.entry_price) * pos.quantity - total_comm
    pnl_pct = (exit_price / pos.entry_price - 1) * 100 if pos.entry_price > 0 else 0
    cash_back = sell_value - sell_cost

    trade = Trade(
        code=pos.code, strategy_name=pos.strategy_name,
        entry_price=pos.entry_price, exit_price=exit_price,
        entry_time=pos.entry_time, exit_time=exit_time,
        quantity=pos.quantity, pnl=pnl, pnl_pct=pnl_pct,
        exit_reason=reason, commission_total=total_comm,
        quality_score=pos.quality_score,
    )
    return trade, cash_back


# ══════════════════════════════════════════════════════
#  메인 시뮬레이션
# ══════════════════════════════════════════════════════
def _compute_prev_day_data_for_sim(intraday_data, daily_by_date, all_dates):
    """갭 전략용 전일 종가 + 일간 거래량 계산.

    avg_vol = 전일 일간 총 거래량 (전략에서 /78로 봉당 환산).
    """
    prev_day_data = {}
    date_list = sorted(all_dates)
    for i in range(1, len(date_list)):
        current_date = date_list[i]
        prev_date = date_list[i - 1]
        prev_daily = daily_by_date.get(prev_date, {})
        for code in intraday_data:
            prev_info = prev_daily.get(code)
            if prev_info and prev_info["close"] > 0:
                if code not in prev_day_data:
                    prev_day_data[code] = {}
                prev_day_data[code][current_date] = {
                    "close": prev_info["close"],
                    "avg_vol": prev_info.get("volume", 0),
                }
    return prev_day_data


def run_simulation(intraday_data, daily_by_date, daily_context, n_days=None):

    # 날짜별 5분봉 그룹핑
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

    # 전일 날짜 매핑
    all_dates_full = sorted(all_dates_set)
    prev_date_map = {}
    for i, d in enumerate(all_dates_full):
        if i > 0:
            prev_date_map[d] = all_dates_full[i - 1]

    # DD 전략 초기화 (전략1+3 + 갭 반전 전략)
    dd_strategies = get_data_driven_strategies()
    gap_strategy = get_gap_strategy()
    dd_strategies.append(gap_strategy)

    # 갭 전략에 전일 데이터 주입
    prev_day_data = _compute_prev_day_data_for_sim(
        intraday_data, daily_by_date, all_dates_full
    )
    for strategy in dd_strategies:
        if hasattr(strategy, "_prev_day_data"):
            strategy._prev_day_data = prev_day_data

    # 상태
    capital = float(INITIAL_CAPITAL)
    positions = {}
    all_trades = []
    daily_records = []
    v6_consec_loss = 0
    v6_day_stopped = False

    for current_date in tqdm(all_dates, desc="시뮬레이션", leave=False):
        day_data = date_code_df.get(current_date)
        if not day_data:
            continue

        prev_date = prev_date_map.get(current_date)
        day_pnl = 0.0
        day_trades = []
        v6_consec_loss = 0
        v6_day_stopped = False

        # ── 오버나잇 갭하락 손절 체크 ──
        for code in list(positions.keys()):
            pos = positions[code]
            if not pos.is_overnight:
                continue
            if code not in day_data:
                continue
            bars = day_data[code]
            if bars.empty:
                continue

            open_price = float(bars.iloc[0]["open"])
            gap_pct = (open_price / pos.entry_price - 1)

            if gap_pct <= V6_GAP_DOWN_STOP:
                trade, cash_back = close_position(pos, open_price, bars.index[0], "갭하락손절")
                all_trades.append(trade)
                day_trades.append(trade)
                capital += cash_back
                day_pnl += trade.pnl
                del positions[code]
            else:
                pos.is_overnight = False

        # ── DD 지표 사전 계산 ──
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

        # ── v6.2 후보 사전 계산 ──
        v6_entries = []  # [{code, time, price, confidence, quality, method, rank}]
        universe = v6_select_universe(daily_by_date, current_date)

        if universe:
            # 필터: 시총 + 기관
            eligible = set()
            for code in universe:
                ctx = daily_context.get(code, {}).get(current_date) if daily_context else None
                prev_ctx = daily_context.get(code, {}).get(prev_date) if daily_context and prev_date else None

                if ctx and ctx.market_cap_bil < V6_MIN_CAP_BIL:
                    continue
                if prev_ctx and prev_ctx.inst_net_buy_bil is not None:
                    if not (V6_MIN_INST <= prev_ctx.inst_net_buy_bil <= V6_MAX_INST):
                        continue
                eligible.add(code)

            leaders, top20 = v6_select_leaders(universe, intraday_data, current_date, eligible)
            leader_codes = [s["code"] for s in leaders]
            top5_codes = [s["code"] for s in top20[:5]]
            vol_median = v6_morning_vol_median(intraday_data, current_date, leader_codes)

            for rank_idx, s in enumerate(leaders):
                code = s["code"]
                actual_rank = V6_SKIP_TOP_N + rank_idx + 1

                if code not in day_data:
                    continue

                # 등락률 필터
                day_info = daily_by_date.get(current_date, {}).get(code, {})
                if day_info.get("change_rate", 0) < V6_MIN_DAILY_CHANGE:
                    continue

                day_df = day_data[code]
                ctx = daily_context.get(code, {}).get(current_date) if daily_context else None
                prev_ctx = daily_context.get(code, {}).get(prev_date) if daily_context and prev_date else None

                # 돌파매매
                breakout = v6_find_breakout(day_df)
                if breakout:
                    qs = v6_calc_quality_score(
                        code, day_df, day_info, ctx, prev_ctx, actual_rank, breakout["time"]
                    )
                    if qs >= V6_MIN_QUALITY and not (70 <= qs < 80):
                        v6_entries.append({
                            "code": code, "time": breakout["time"],
                            "price": breakout["price"], "confidence": breakout["confidence"],
                            "quality": qs, "method": "돌파매매", "rank": actual_rank,
                        })

                # 눌림매매
                pullback = v6_find_pullback(day_df, vol_median)
                if pullback and not any(e["code"] == code and e["method"] == "돌파매매" for e in v6_entries):
                    qs = v6_calc_quality_score(
                        code, day_df, day_info, ctx, prev_ctx, actual_rank, pullback["time"]
                    )
                    if qs >= V6_MIN_QUALITY and not (70 <= qs < 80):
                        v6_entries.append({
                            "code": code, "time": pullback["time"],
                            "price": pullback["price"], "confidence": pullback["confidence"],
                            "quality": qs, "method": "눌림매매", "rank": actual_rank,
                        })

        # v6 entries를 시간순 + 품질순 정렬
        v6_entries.sort(key=lambda x: (-x["quality"], x["time"]))
        v6_entered_today = set()

        # ── 봉별 순회 ──
        all_ts = sorted(set(ts for day_df in day_data.values() for ts in day_df.index.tolist()))

        for ts in all_ts:
            ct = ts.time() if hasattr(ts, "time") else ts
            if ct < time(9, 0) or ct > time(15, 30):
                continue

            # ── 강제 청산 ──
            if ct >= FORCE_CLOSE_TIME:
                for code in list(positions.keys()):
                    pos = positions[code]
                    price = _get_close(code, ts, day_data)
                    if price is None:
                        continue
                    trade, cash_back = close_position(pos, price, ts, "장마감")
                    all_trades.append(trade)
                    day_trades.append(trade)
                    capital += cash_back
                    day_pnl += trade.pnl
                    del positions[code]
                continue

            # ── 보유 포지션 SL/TP 체크 ──
            for code in list(positions.keys()):
                pos = positions[code]
                hlc = _get_hlc(code, ts, day_data)
                if hlc is None:
                    continue
                low_val, high_val, close_val = hlc
                is_v6 = pos.strategy_name.startswith("경윤_")

                # 분할매도 후 본전컷 (v6)
                if is_v6 and pos.partial_sold:
                    pnl_r = (close_val - pos.entry_price) / pos.entry_price
                    if pnl_r <= V6_BREAKEVEN_CUT:
                        trade, cash_back = close_position(pos, close_val, ts, "본전컷")
                        all_trades.append(trade)
                        day_trades.append(trade)
                        capital += cash_back
                        day_pnl += trade.pnl
                        del positions[code]
                        continue

                # 분할매도 (v6, TP 도달 + partial 안 함)
                if is_v6 and not pos.partial_sold and high_val >= pos.entry_price * (1 + V6_TP):
                    tp_price = pos.entry_price * (1 + V6_TP)
                    sell_qty = int(pos.original_quantity * V6_PARTIAL_RATIO)
                    if sell_qty > 0 and sell_qty < pos.quantity:
                        sv = tp_price * sell_qty
                        sc = calc_cost(tp_price, sell_qty, "sell")
                        bc = calc_cost(pos.entry_price, sell_qty, "buy")
                        pnl = (tp_price - pos.entry_price) * sell_qty - bc - sc
                        partial_trade = Trade(
                            code=code, strategy_name=pos.strategy_name,
                            entry_price=pos.entry_price, exit_price=tp_price,
                            entry_time=pos.entry_time, exit_time=ts,
                            quantity=sell_qty, pnl=pnl,
                            pnl_pct=(tp_price / pos.entry_price - 1) * 100,
                            exit_reason="1차익절", commission_total=bc + sc,
                            quality_score=pos.quality_score,
                        )
                        all_trades.append(partial_trade)
                        day_trades.append(partial_trade)
                        capital += sv - sc
                        day_pnl += pnl
                        pos.quantity -= sell_qty
                        pos.partial_sold = True
                        v6_consec_loss = 0
                        continue

                # SL (포지션에 저장된 SL% 사용)
                sl_pct = pos.stop_loss_pct
                if low_val <= pos.entry_price * (1 - sl_pct):
                    sl_price = pos.entry_price * (1 - sl_pct)
                    trade, cash_back = close_position(pos, sl_price, ts, "손절")
                    all_trades.append(trade)
                    day_trades.append(trade)
                    capital += cash_back
                    day_pnl += trade.pnl
                    del positions[code]
                    if is_v6:
                        v6_consec_loss += 1
                        if v6_consec_loss >= V6_MAX_CONSEC_LOSS:
                            v6_day_stopped = True
                    continue

                # TP (DD 전량 매도, 포지션에 저장된 TP% 사용)
                tp_pct = pos.take_profit_pct
                if not is_v6 and high_val >= pos.entry_price * (1 + tp_pct):
                    tp_price = pos.entry_price * (1 + tp_pct)
                    trade, cash_back = close_position(pos, tp_price, ts, "익절")
                    all_trades.append(trade)
                    day_trades.append(trade)
                    capital += cash_back
                    day_pnl += trade.pnl
                    del positions[code]
                    continue

                # DD 전략 check_exit_fast (시간청산 등)
                if not is_v6 and code in positions:
                    for si, strategy in enumerate(dd_strategies):
                        if strategy.name != pos.strategy_name:
                            continue
                        if code not in dd_ts_to_idx[si] or ts not in dd_ts_to_idx[si][code]:
                            break
                        idx = dd_ts_to_idx[si][code][ts]
                        ind = dd_indicators[si][code]
                        exit_reason = strategy.check_exit_fast(None, idx, ind)
                        if exit_reason:
                            trade, cash_back = close_position(
                                pos, close_val, ts, exit_reason
                            )
                            all_trades.append(trade)
                            day_trades.append(trade)
                            capital += cash_back
                            day_pnl += trade.pnl
                            del positions[code]
                        break

            # ── 신규 진입 ──
            if len(positions) >= MAX_POSITIONS:
                continue

            pending = []

            # DD 시그널
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
                            "code": code, "type": "dd",
                            "strategy_name": strategy.name,
                            "price": float(ind["close"][idx]),
                            "quality": int(signal.get("confidence", 1.0) * 100),
                            "alloc_pct": DD_POSITION_PCT,
                            "sl_pct": signal.get("stop_loss", DD_SL),
                            "tp_pct": signal.get("take_profit", DD_TP),
                        })

            # v6.2 시그널 (시간 일치하는 것만)
            if not v6_day_stopped:
                for e in v6_entries:
                    if e["code"] in positions or e["code"] in v6_entered_today:
                        continue
                    if e["time"] != ts:
                        continue
                    if e["confidence"] < V6_MIN_CONFIDENCE:
                        continue
                    alloc = V6_HIGH_CONF_PCT if e["confidence"] >= 0.7 else V6_LOW_CONF_PCT
                    pending.append({
                        "code": e["code"], "type": "v6",
                        "strategy_name": f"경윤_{e['method']}",
                        "price": e["price"],
                        "quality": e["quality"],
                        "alloc_pct": alloc,
                        "sl_pct": V6_SL, "tp_pct": V6_TP,
                    })

            # 품질/confidence 순 진입
            pending.sort(key=lambda x: x["quality"], reverse=True)
            seen = set(positions.keys())

            for p in pending:
                if len(positions) >= MAX_POSITIONS:
                    break
                if p["code"] in seen:
                    continue

                price = p["price"]
                if price is None or price <= 0:
                    continue

                total_equity = capital + sum(
                    pos.entry_price * pos.quantity for pos in positions.values()
                )
                invest = total_equity * p["alloc_pct"]
                qty = int(invest / price)
                if qty <= 0:
                    continue

                buy_cost = calc_cost(price, qty, "buy")
                total_cost = price * qty + buy_cost
                if total_cost > capital:
                    qty = int((capital * 0.99) / price)
                    if qty <= 0:
                        continue
                    buy_cost = calc_cost(price, qty, "buy")
                    total_cost = price * qty + buy_cost

                capital -= total_cost
                positions[p["code"]] = Position(
                    code=p["code"], strategy_name=p["strategy_name"],
                    entry_price=price, entry_time=ts,
                    quantity=qty, invested=price * qty,
                    stop_loss_pct=p["sl_pct"], take_profit_pct=p["tp_pct"],
                    quality_score=p.get("quality", 0),
                    entry_date=current_date,
                )
                seen.add(p["code"])
                if p["type"] == "v6":
                    v6_entered_today.add(p["code"])

        # ── 장종료: 오버나잇 or 청산 ──
        for code in list(positions.keys()):
            pos = positions[code]
            if code not in day_data:
                continue
            bars = day_data[code]
            if bars.empty:
                continue

            is_v6 = pos.strategy_name.startswith("경윤_")

            if is_v6:
                day_info = daily_by_date.get(current_date, {}).get(code, {})
                top5 = [s["code"] for s in (top20[:5] if universe else [])] if universe else []
                ov_score, should_hold = v6_evaluate_overnight(code, pos, bars, day_info, top5)

                if should_hold:
                    pos.is_overnight = True
                    pos.overnight_score = ov_score
                    continue

            # 청산
            last_price = float(bars.iloc[-1]["close"])
            last_ts = bars.index[-1]
            trade, cash_back = close_position(pos, last_price, last_ts, "장마감")
            all_trades.append(trade)
            day_trades.append(trade)
            capital += cash_back
            day_pnl += trade.pnl
            del positions[code]

        daily_records.append({
            "date": current_date,
            "equity": capital + sum(p.entry_price * p.quantity for p in positions.values()),
            "trades": len(day_trades),
            "pnl": day_pnl,
        })

    return capital, all_trades, daily_records, positions


def _get_close(code, ts, day_data):
    if code not in day_data:
        return None
    df = day_data[code]
    if ts in df.index:
        return float(df.loc[ts, "close"])
    before = df[df.index <= ts]
    if not before.empty:
        return float(before.iloc[-1]["close"])
    return None


def _get_hlc(code, ts, day_data):
    if code not in day_data:
        return None
    df = day_data[code]
    if ts in df.index:
        row = df.loc[ts]
        return float(row["low"]), float(row["high"]), float(row["close"])
    return None


# ══════════════════════════════════════════════════════
#  결과 출력
# ══════════════════════════════════════════════════════
def print_result(final_capital, trades, daily_records, remaining_positions, label):
    # 잔여 포지션 가치 포함
    remaining_val = sum(p.entry_price * p.quantity for p in remaining_positions.values())
    total_equity = final_capital + remaining_val

    total_pnl = total_equity - INITIAL_CAPITAL
    total_return = (total_equity / INITIAL_CAPITAL - 1) * 100
    n_trades = len(trades)
    n_wins = sum(1 for t in trades if t.pnl > 0)
    wr = n_wins / n_trades * 100 if n_trades else 0
    total_comm = sum(t.commission_total for t in trades)
    n_days = len(daily_records)

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
    print(f"  최종자금:     {total_equity:>14,.0f}원")
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

    if remaining_positions:
        print(f"\n  [오버나잇 보유 {len(remaining_positions)}건]")
        for code, pos in remaining_positions.items():
            print(f"    {code} ({pos.strategy_name}): {pos.quantity}주 @ {pos.entry_price:,.0f}원")

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
    for reason in ["익절", "1차익절", "손절", "본전컷", "장마감", "갭하락손절"]:
        if reason in reason_stats:
            r = reason_stats[reason]
            print(f"  {reason:12s}: {r['count']:4d}건 | {r['pnl']:>+13,.0f}원")

    # v6 품질 점수별
    v6_trades = [t for t in trades if t.strategy_name.startswith("경윤_")]
    if v6_trades:
        print(f"\n  [경윤 품질 점수별]")
        for sr in [90, 80, 60]:
            ts_range = [t for t in v6_trades if sr <= t.quality_score < sr + 10]
            if ts_range:
                rw = sum(1 for t in ts_range if t.pnl > 0)
                rp = sum(t.pnl for t in ts_range)
                print(f"  {sr}~{sr+9}점: {len(ts_range)}건, "
                      f"WR {rw/len(ts_range)*100:.1f}%, PnL {rp:+,.0f}원")


def main():
    print("=" * 70)
    print("  4개 전략 통합 시뮬레이션 v2 (DD1+3 + 갭반전 + 경윤 v6.2)")
    print(f"  자본금: {INITIAL_CAPITAL:,}원 | 최대 {MAX_POSITIONS}종목")
    print(f"  DD: SL{DD_SL*100:.0f}% TP{DD_TP*100:.0f}% | 경윤: SL{V6_SL*100:.0f}% TP{V6_TP*100:.0f}%")
    print(f"  갭반전: SL2.5% TP5% @11:30 (Hong Strong 필수)")
    print(f"  경윤 v6.2: 품질{V6_MIN_QUALITY}+, 70-79스킵, 등락률{V6_MIN_DAILY_CHANGE}%+")
    print("=" * 70)

    print("\n  데이터 로딩...")
    t0 = time_module.time()
    intraday_data, daily_by_date, all_dates = load_all_data()
    print(f"  5분봉: {len(intraday_data)}종목, {len(all_dates)}거래일")
    print(f"  일봉: {len(daily_by_date)}일")
    print(f"  기간: {min(all_dates)} ~ {max(all_dates)}")
    print(f"  로딩: {time_module.time() - t0:.1f}초")

    codes = list(intraday_data.keys())
    print(f"\n  일별 컨텍스트 로딩...")
    loader = DailyContextLoader()
    daily_context = loader.load(codes, min(all_dates), max(all_dates))
    print(f"  컨텍스트: {sum(len(v) for v in daily_context.values())}건")

    # 60일
    print(f"\n  [60일 시뮬레이션...]")
    t0 = time_module.time()
    cap60, trades60, daily60, rem60 = run_simulation(
        intraday_data, daily_by_date, daily_context, n_days=None
    )
    print(f"  완료: {time_module.time() - t0:.1f}초")
    print_result(cap60, trades60, daily60, rem60, f"60일 (전체 {len(daily60)}일)")

    # 20일
    print(f"\n  [20일 시뮬레이션...]")
    t0 = time_module.time()
    cap20, trades20, daily20, rem20 = run_simulation(
        intraday_data, daily_by_date, daily_context, n_days=20
    )
    print(f"  완료: {time_module.time() - t0:.1f}초")
    print_result(cap20, trades20, daily20, rem20, "최근 20일")

    # 비교
    eq60 = cap60 + sum(p.entry_price * p.quantity for p in rem60.values())
    eq20 = cap20 + sum(p.entry_price * p.quantity for p in rem20.values())
    ret60 = (eq60 / INITIAL_CAPITAL - 1) * 100
    ret20 = (eq20 / INITIAL_CAPITAL - 1) * 100
    wr60 = sum(1 for t in trades60 if t.pnl > 0) / len(trades60) * 100 if trades60 else 0
    wr20 = sum(1 for t in trades20 if t.pnl > 0) / len(trades20) * 100 if trades20 else 0

    print(f"\n{'━' * 70}")
    print(f"  비교 요약")
    print(f"{'━' * 70}")
    print(f"  {'':25s} {'20일':>15s} {'60일':>15s}")
    print(f"  {'─' * 57}")
    print(f"  {'최종자금':25s} {eq20:>14,.0f}원 {eq60:>14,.0f}원")
    print(f"  {'수익률':25s} {ret20:>+14.2f}% {ret60:>+14.2f}%")
    print(f"  {'거래수':25s} {len(trades20):>14}건 {len(trades60):>14}건")
    print(f"  {'승률':25s} {wr20:>13.1f}% {wr60:>13.1f}%")
    print(f"\n{'=' * 70}")


def grid_search():
    """포지션 비율 그리드서치"""
    global DD_POSITION_PCT, V6_HIGH_CONF_PCT, V6_LOW_CONF_PCT

    print("=" * 70)
    print("  포지션 비율 그리드서치 (자본금 1000만, 3종목)")
    print("=" * 70)

    print("\n  데이터 로딩...")
    t0 = time_module.time()
    intraday_data, daily_by_date, all_dates = load_all_data()
    codes = list(intraday_data.keys())
    loader = DailyContextLoader()
    daily_context = loader.load(codes, min(all_dates), max(all_dates))
    print(f"  로딩 완료: {time_module.time() - t0:.1f}초\n")

    # 그리드 정의
    dd_pcts = [0.20, 0.25, 0.30, 0.35, 0.40]
    v6_high_pcts = [0.40, 0.50, 0.60]
    v6_low_pcts = [0.20, 0.30]

    results = []
    total = len(dd_pcts) * len(v6_high_pcts) * len(v6_low_pcts)
    idx = 0

    for dd in dd_pcts:
        for v6h in v6_high_pcts:
            for v6l in v6_low_pcts:
                if v6l > v6h:
                    continue
                idx += 1
                DD_POSITION_PCT = dd
                V6_HIGH_CONF_PCT = v6h
                V6_LOW_CONF_PCT = v6l

                cap60, trades60, daily60, rem60 = run_simulation(
                    intraday_data, daily_by_date, daily_context, n_days=None
                )
                eq60 = cap60 + sum(p.entry_price * p.quantity for p in rem60.values())
                ret60 = (eq60 / INITIAL_CAPITAL - 1) * 100
                wr60 = sum(1 for t in trades60 if t.pnl > 0) / len(trades60) * 100 if trades60 else 0
                peak = INITIAL_CAPITAL
                mdd = 0
                equity = INITIAL_CAPITAL
                for d in daily60:
                    equity = d["equity"]
                    if equity > peak:
                        peak = equity
                    dd_val = (peak - equity) / peak * 100
                    if dd_val > mdd:
                        mdd = dd_val

                cap20, trades20, daily20, rem20 = run_simulation(
                    intraday_data, daily_by_date, daily_context, n_days=20
                )
                eq20 = cap20 + sum(p.entry_price * p.quantity for p in rem20.values())
                ret20 = (eq20 / INITIAL_CAPITAL - 1) * 100

                results.append({
                    "dd": dd, "v6h": v6h, "v6l": v6l,
                    "ret60": ret60, "ret20": ret20,
                    "wr60": wr60, "trades": len(trades60), "mdd": mdd,
                    "pnl60": eq60 - INITIAL_CAPITAL,
                })
                print(f"  [{idx:2d}/{total}] DD={dd:.0%} V6H={v6h:.0%} V6L={v6l:.0%} "
                      f"→ 60일 {ret60:+.2f}% (WR {wr60:.1f}%, {len(trades60)}건, MDD {mdd:.1f}%) "
                      f"| 20일 {ret20:+.2f}%")

    # 정렬
    results.sort(key=lambda x: x["ret60"], reverse=True)

    print(f"\n{'━' * 90}")
    print(f"  TOP 10 (60일 수익률 기준)")
    print(f"{'━' * 90}")
    print(f"  {'#':>3} {'DD':>5} {'V6H':>5} {'V6L':>5} {'60일':>8} {'20일':>8} {'WR':>6} {'거래':>5} {'MDD':>6} {'손익':>12}")
    print(f"  {'─' * 85}")
    for i, r in enumerate(results[:10]):
        print(f"  {i+1:3d} {r['dd']:>5.0%} {r['v6h']:>5.0%} {r['v6l']:>5.0%} "
              f"{r['ret60']:>+7.2f}% {r['ret20']:>+7.2f}% {r['wr60']:>5.1f}% "
              f"{r['trades']:>4}건 {r['mdd']:>5.1f}% {r['pnl60']:>+11,.0f}원")

    print(f"\n  WORST 3")
    print(f"  {'─' * 85}")
    for r in results[-3:]:
        print(f"      DD={r['dd']:.0%} V6H={r['v6h']:.0%} V6L={r['v6l']:.0%} "
              f"→ 60일 {r['ret60']:+.2f}% | 20일 {r['ret20']:+.2f}%")

    # 최적값 복원
    best = results[0]
    DD_POSITION_PCT = best["dd"]
    V6_HIGH_CONF_PCT = best["v6h"]
    V6_LOW_CONF_PCT = best["v6l"]
    print(f"\n  ✓ 최적 비율: DD={best['dd']:.0%} V6H={best['v6h']:.0%} V6L={best['v6l']:.0%}")
    print(f"    60일 {best['ret60']:+.2f}%, 20일 {best['ret20']:+.2f}%, "
          f"WR {best['wr60']:.1f}%, MDD {best['mdd']:.1f}%")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "grid":
        grid_search()
    else:
        main()
