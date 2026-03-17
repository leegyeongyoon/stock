#!/usr/bin/env python3
"""OLD vs NEW 알고리즘 비교 시뮬레이션

OLD: 기존 파라미터 (시간대 필터 없음, SL 3%, 리스크관리 없음)
NEW: 고도화 적용 (시간대 필터, 적응형 SL/TP, 연속손실 차단, 종목 쿨다운, 일일 손실 2%)

1000만원 기준, 실제 DB 데이터 사용.
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
from src.database.connection import get_engine
from src.strategies.data_driven.intraday_strategy_1 import MorningRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_3 import ModifiedRSINeutralATRStrategy
from src.strategies.data_driven.intraday_strategy_gap import OpeningGapReversalStrategy
from src.strategies.data_driven.daily_context import DailyContextLoader

# ══════════════════════════════════════════════════════
#  설정
# ══════════════════════════════════════════════════════
INITIAL_CAPITAL = 10_000_000
MAX_POSITIONS = 3
COMMISSION = 0.00015
TAX = 0.0023
SLIPPAGE = 0.001

# 경윤 v6.2 설정
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
#  데이터 로딩 (simulate_combined_v2 동일)
# ══════════════════════════════════════════════════════
def load_all_data():
    engine = get_engine()
    with engine.connect() as conn:
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

    all_dates = sorted(set(d for df in intraday_data.values() for d in df.index.date))

    daily_start = min(all_dates) - timedelta(days=30) if all_dates else date.today() - timedelta(days=90)
    daily_by_date = {}
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


def _compute_prev_day_data(intraday_data, daily_by_date, all_dates):
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


# ══════════════════════════════════════════════════════
#  경윤 v6.2 헬퍼 (simulate_combined_v2에서 복사)
# ══════════════════════════════════════════════════════
def v6_select_universe(daily_by_date, trading_date):
    day_data = daily_by_date.get(trading_date, {})
    if not day_data:
        return set()
    by_value = sorted(day_data.items(), key=lambda x: x[1]["value"], reverse=True)
    top100 = {code for code, _ in by_value[:100]}
    strong = {code for code, d in day_data.items() if d["change_rate"] >= 3.0}
    return top100 | strong


def v6_select_leaders(universe, intraday_data, trading_date, eligible_codes):
    scores = []
    for code in eligible_codes:
        if code not in intraday_data:
            continue
        df = intraday_data[code]
        day_df = df[df.index.date == trading_date]
        if day_df.empty:
            continue
        morning = day_df[(day_df.index.hour == 9) & (day_df.index.minute < 30)]
        if len(morning) < 2:
            continue
        vol_sum = morning["volume"].sum()
        pchg = (morning.iloc[-1]["close"] / morning.iloc[0]["open"] - 1) * 100
        momentum = vol_sum * max(pchg, 0)
        scores.append({"code": code, "momentum": momentum, "pchg": pchg, "vol_sum": vol_sum})
    scores.sort(key=lambda x: x["momentum"], reverse=True)
    top20 = scores[:20]
    filtered = top20[V6_SKIP_TOP_N:V6_SKIP_TOP_N + V6_ENTER_TOP_N]
    return filtered, top20


def v6_find_breakout(day_df):
    window = day_df[((day_df.index.hour == 9) & (day_df.index.minute >= 30)) | (day_df.index.hour == 10)]
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
                return {"price": bar_close, "time": window.index[i], "confidence": 0.75}
    return None


def v6_find_pullback(day_df, vol_median):
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
        if (prev["low"] <= mh * 0.95 and bar["close"] > prev["close"]
                and bar["close"] > r50 and bar["low"] > ml):
            return {"price": float(bar["close"]), "time": window.index[i], "confidence": 0.6}
    return None


def v6_morning_vol_median(intraday_data, trading_date, leader_codes):
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
                          leader_rank, leaders_top5, entry_time=None):
    score = 0
    cap_bil = 0
    if daily_ctx:
        cap_bil = daily_ctx.market_cap_bil or 0
    if cap_bil >= 30000:
        score += 15
    elif cap_bil >= 10000:
        score += 10
    elif cap_bil >= 5000:
        score += 5

    inst = 0
    if daily_ctx and daily_ctx.inst_net_buy_bil is not None:
        inst = daily_ctx.inst_net_buy_bil
    if inst >= 150:
        score += 15
    elif inst >= 100:
        score += 10
    elif inst >= 50:
        score += 5

    chg = daily_info.get("change_rate", 0)
    if chg >= 15:
        score += 20
    elif chg >= 10:
        score += 15
    elif chg >= 6:
        score += 10

    morning = day_df[day_df.index.hour < 12]
    if not morning.empty and morning.iloc[0]["open"] > 0:
        mchg = (morning.iloc[-1]["close"] / morning.iloc[0]["open"] - 1) * 100
        if mchg >= 15:
            score += 20
        elif mchg >= 10:
            score += 15
        elif mchg >= 5:
            score += 10

    if not morning.empty:
        mh = morning["high"].max()
        ml = morning["low"].min()
        mc = morning.iloc[-1]["close"]
        if mh > ml:
            cs = (mc - ml) / (mh - ml)
            if cs >= 0.9:
                score += 20
            elif cs >= 0.75:
                score += 15
            elif cs >= 0.6:
                score += 10

    if code in leaders_top5:
        rank = leaders_top5.index(code) + 1
        if rank <= 2:
            score += 10
        elif rank <= 3:
            score += 7
        elif rank <= 4:
            score += 5
        else:
            score += 3

    return score


def v6_evaluate_overnight(code, pos, bars, daily_info, leaders_top5):
    if bars.empty:
        return 0, False
    last_price = float(bars.iloc[-1]["close"])
    pnl_pct = (last_price / pos.entry_price - 1) * 100
    if pnl_pct < 0:
        return 0, False

    score = 0
    chg = daily_info.get("change_rate", 0)
    ki_est = max(0, min(chg * 5 + 30, 100))
    if ki_est >= 50: score += 30
    elif ki_est >= 40: score += 20
    elif ki_est >= 30: score += 10

    if code in leaders_top5:
        rank = leaders_top5.index(code) + 1
        score += 20 if rank <= 2 else 15 if rank <= 3 else 10

    if chg >= 10: score += 20
    elif chg >= 5: score += 15
    elif chg >= 3: score += 10

    if chg >= 5: score += 15
    elif chg >= 3: score += 10

    morning = bars[bars.index.hour < 12]
    afternoon = bars[bars.index.hour >= 12]
    if not morning.empty and not afternoon.empty and morning["volume"].sum() > 0:
        vr = afternoon["volume"].sum() / morning["volume"].sum()
        if vr >= 0.8: score += 15
        elif vr >= 0.6: score += 10
        elif vr >= 0.4: score += 5

    return score, score >= V6_OVERNIGHT_MIN


# ══════════════════════════════════════════════════════
#  거래 실행
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


def _get_hlc(code, ts, day_data):
    if code not in day_data:
        return None
    df = day_data[code]
    if ts in df.index:
        row = df.loc[ts]
        return float(row["low"]), float(row["high"]), float(row["close"])
    return None


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


# ══════════════════════════════════════════════════════
#  리스크 관리 (NEW 전용)
# ══════════════════════════════════════════════════════
class SimRiskManager:
    """시뮬레이션용 리스크 관리."""

    def __init__(self, initial_capital, max_daily_loss_pct=0.02,
                 consecutive_loss_limit=3, max_stock_entries=2):
        self.initial_capital = initial_capital
        self.max_daily_loss_pct = max_daily_loss_pct
        self.consecutive_loss_limit = consecutive_loss_limit
        self.max_stock_entries = max_stock_entries

        self._consecutive_losses = 0
        self._stock_cooldown = set()   # SL 종목 → 당일 재진입 차단
        self._stock_entry_count = {}   # 종목별 당일 진입 횟수
        self._circuit_breaker = False
        self._day_pnl = 0.0

    def reset_daily(self):
        self._consecutive_losses = 0
        self._stock_cooldown.clear()
        self._stock_entry_count.clear()
        self._circuit_breaker = False
        self._day_pnl = 0.0

    def record_trade(self, exit_reason, stock_code, pnl):
        self._day_pnl += pnl
        if exit_reason in ("손절", "SL"):
            self._consecutive_losses += 1
            self._stock_cooldown.add(stock_code)
        elif exit_reason in ("익절", "TP", "1차익절"):
            self._consecutive_losses = 0
        # Circuit breaker
        if self._day_pnl / self.initial_capital < -self.max_daily_loss_pct:
            self._circuit_breaker = True

    def record_entry(self, stock_code):
        self._stock_entry_count[stock_code] = self._stock_entry_count.get(stock_code, 0) + 1

    def can_enter(self, stock_code):
        if self._circuit_breaker:
            return False
        if self._consecutive_losses >= self.consecutive_loss_limit:
            return False
        if stock_code in self._stock_cooldown:
            return False
        if self._stock_entry_count.get(stock_code, 0) >= self.max_stock_entries:
            return False
        return True


# ══════════════════════════════════════════════════════
#  시뮬레이션 코어
# ══════════════════════════════════════════════════════
def run_simulation(intraday_data, daily_by_date, daily_context, all_dates,
                   mode="NEW", n_days=None):
    """
    mode="OLD": 기존 파라미터 (시간대 필터 9~14, SL 3%, 리스크관리 없음)
    mode="NEW": 고도화 (시간대 필터, 적응형 SL/TP, 연속손실 차단, 쿨다운)
    """
    is_new = (mode == "NEW")

    # 날짜별 5분봉 그룹핑
    date_code_df = {}
    all_dates_set = set()
    for code, df in intraday_data.items():
        for dt, day_df in df.groupby(df.index.date):
            all_dates_set.add(dt)
            if dt not in date_code_df:
                date_code_df[dt] = {}
            date_code_df[dt][code] = day_df

    sim_dates = sorted(all_dates_set & set(all_dates))
    if n_days and n_days < len(sim_dates):
        sim_dates = sim_dates[-n_days:]

    all_dates_full = sorted(all_dates_set)
    prev_date_map = {}
    for i, d in enumerate(all_dates_full):
        if i > 0:
            prev_date_map[d] = all_dates_full[i - 1]

    # DD 전략 초기화
    strat1 = MorningRSINeutralATRStrategy()
    strat3 = ModifiedRSINeutralATRStrategy()

    if mode == "OLD":
        gap = OpeningGapReversalStrategy(stop_loss_pct=0.03)
        # OLD: 전략3 시간 필터는 원래 9~14, SL 고정 3%
        old_sl = 0.03
        old_tp = 0.05
    else:
        gap = OpeningGapReversalStrategy(stop_loss_pct=0.025)
        old_sl = None  # adaptive SL/TP 사용
        old_tp = None

    dd_strategies = [strat1, strat3, gap]

    # 전일 데이터 주입
    prev_day_data = _compute_prev_day_data(intraday_data, daily_by_date, all_dates_full)
    for s in dd_strategies:
        if hasattr(s, "_prev_day_data"):
            s._prev_day_data = prev_day_data

    # 리스크 매니저 (NEW만)
    risk_mgr = SimRiskManager(INITIAL_CAPITAL) if is_new else None

    DD_POSITION_PCT = 0.40

    capital = float(INITIAL_CAPITAL)
    positions = {}
    all_trades = []
    daily_records = []
    v6_consec_loss = 0
    v6_day_stopped = False

    blocked_by_risk = 0  # 리스크로 차단된 진입 수

    for current_date in tqdm(sim_dates, desc=f"{mode} 시뮬레이션", leave=False):
        day_data = date_code_df.get(current_date)
        if not day_data:
            continue

        prev_date = prev_date_map.get(current_date)
        day_pnl = 0.0
        day_trades = []
        v6_consec_loss = 0
        v6_day_stopped = False
        if risk_mgr:
            risk_mgr.reset_daily()

        # ── 오버나잇 갭하락 손절 ──
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
                if risk_mgr:
                    risk_mgr.record_trade("손절", code, trade.pnl)
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
        v6_entries = []
        universe = v6_select_universe(daily_by_date, current_date)
        top20 = []

        if universe:
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
                day_info = daily_by_date.get(current_date, {}).get(code, {})
                if day_info.get("change_rate", 0) < V6_MIN_DAILY_CHANGE:
                    continue
                day_df = day_data[code]
                ctx = daily_context.get(code, {}).get(current_date) if daily_context else None
                prev_ctx = daily_context.get(code, {}).get(prev_date) if daily_context and prev_date else None

                breakout = v6_find_breakout(day_df)
                if breakout:
                    qs = v6_calc_quality_score(code, day_df, day_info, ctx, prev_ctx, actual_rank, top5_codes, breakout["time"])
                    if qs >= V6_MIN_QUALITY and not (70 <= qs < 80):
                        v6_entries.append({
                            "code": code, "time": breakout["time"],
                            "price": breakout["price"], "confidence": breakout["confidence"],
                            "quality": qs, "method": "돌파매매", "rank": actual_rank,
                        })

                pullback = v6_find_pullback(day_df, vol_median)
                if pullback and not any(e["code"] == code and e["method"] == "돌파매매" for e in v6_entries):
                    qs = v6_calc_quality_score(code, day_df, day_info, ctx, prev_ctx, actual_rank, top5_codes, pullback["time"])
                    if qs >= V6_MIN_QUALITY and not (70 <= qs < 80):
                        v6_entries.append({
                            "code": code, "time": pullback["time"],
                            "price": pullback["price"], "confidence": pullback["confidence"],
                            "quality": qs, "method": "눌림매매", "rank": actual_rank,
                        })

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
                    if risk_mgr:
                        risk_mgr.record_trade("장마감", code, trade.pnl)
                    del positions[code]
                continue

            # ── SL/TP 체크 ──
            for code in list(positions.keys()):
                pos = positions[code]
                hlc = _get_hlc(code, ts, day_data)
                if hlc is None:
                    continue
                low_val, high_val, close_val = hlc
                is_v6 = pos.strategy_name.startswith("경윤_")

                # v6 분할매도 후 본전컷
                if is_v6 and pos.partial_sold:
                    pnl_r = (close_val - pos.entry_price) / pos.entry_price
                    if pnl_r <= V6_BREAKEVEN_CUT:
                        trade, cash_back = close_position(pos, close_val, ts, "본전컷")
                        all_trades.append(trade)
                        day_trades.append(trade)
                        capital += cash_back
                        day_pnl += trade.pnl
                        if risk_mgr:
                            risk_mgr.record_trade("본전컷", code, trade.pnl)
                        del positions[code]
                        continue

                # v6 분할매도
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
                        if risk_mgr:
                            risk_mgr.record_trade("1차익절", code, pnl)
                        continue

                # SL
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
                    if risk_mgr:
                        risk_mgr.record_trade("손절", code, trade.pnl)
                    continue

                # TP (DD 전량)
                tp_pct = pos.take_profit_pct
                if not is_v6 and high_val >= pos.entry_price * (1 + tp_pct):
                    tp_price = pos.entry_price * (1 + tp_pct)
                    trade, cash_back = close_position(pos, tp_price, ts, "익절")
                    all_trades.append(trade)
                    day_trades.append(trade)
                    capital += cash_back
                    day_pnl += trade.pnl
                    del positions[code]
                    if risk_mgr:
                        risk_mgr.record_trade("익절", code, trade.pnl)
                    continue

                # DD 시간청산
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
                            trade, cash_back = close_position(pos, close_val, ts, exit_reason)
                            all_trades.append(trade)
                            day_trades.append(trade)
                            capital += cash_back
                            day_pnl += trade.pnl
                            del positions[code]
                            if risk_mgr:
                                risk_mgr.record_trade(exit_reason, code, trade.pnl)
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

                    # OLD 모드: 전략3의 시간 필터를 원래대로 (9~14)
                    if mode == "OLD" and strategy.name == "modified_rsi_neutral_atr":
                        hours = ind["hours"]
                        hour = hours[idx]
                        if hour < 9 or hour >= 14:
                            continue
                        # 원래 check_entry_fast에서 시간 필터가 걸리므로
                        # OLD 모드에서는 별도 처리 필요
                        # 원래 코드는 hour < 9 or hour >= 14 체크 → 현재는 새 필터
                        # OLD 시뮬에서는 원래 조건으로 직접 체크

                    signal = strategy.check_entry_fast(code, idx, ind)

                    # OLD 모드: strategy 3의 시간필터를 무시하고 원래 조건 재적용
                    if mode == "OLD" and strategy.name == "modified_rsi_neutral_atr" and signal is None:
                        # 새 시간필터 때문에 차단된 것일 수 있음 → 원래 조건으로 재시도
                        hours = ind.get("hours", np.array([]))
                        if idx < len(hours):
                            hour = hours[idx]
                            # 원래 시간 조건: 9 <= hour < 14
                            if 9 <= hour < 14:
                                # 새 시간 필터에 의해 차단된 경우 수동 체크
                                signal = _old_strategy3_check(strategy, code, idx, ind)

                    if signal:
                        if mode == "OLD":
                            sl = old_sl or signal.get("stop_loss", 0.03)
                            tp = old_tp or signal.get("take_profit", 0.05)
                        else:
                            sl = signal.get("stop_loss", 0.025)
                            tp = signal.get("take_profit", 0.05)

                        pending.append({
                            "code": code, "type": "dd",
                            "strategy_name": strategy.name,
                            "price": float(ind["close"][idx]),
                            "quality": int(signal.get("confidence", 1.0) * 100),
                            "alloc_pct": DD_POSITION_PCT,
                            "sl_pct": sl, "tp_pct": tp,
                        })

            # v6.2 시그널
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

            pending.sort(key=lambda x: x["quality"], reverse=True)
            seen = set(positions.keys())

            for p in pending:
                if len(positions) >= MAX_POSITIONS:
                    break
                if p["code"] in seen:
                    continue

                # NEW: 리스크 체크
                if risk_mgr and not risk_mgr.can_enter(p["code"]):
                    blocked_by_risk += 1
                    continue

                price = p["price"]
                if price is None or price <= 0:
                    continue
                price = price * (1 + SLIPPAGE)

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
                if risk_mgr:
                    risk_mgr.record_entry(p["code"])

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
                top5 = [s["code"] for s in top20[:5]] if top20 else []
                ov_score, should_hold = v6_evaluate_overnight(code, pos, bars, day_info, top5)
                if should_hold:
                    pos.is_overnight = True
                    pos.overnight_score = ov_score
                    continue

            last_price = float(bars.iloc[-1]["close"])
            last_ts = bars.index[-1]
            trade, cash_back = close_position(pos, last_price, last_ts, "장마감")
            all_trades.append(trade)
            day_trades.append(trade)
            capital += cash_back
            day_pnl += trade.pnl
            if risk_mgr:
                risk_mgr.record_trade("장마감", code, trade.pnl)
            del positions[code]

        daily_records.append({
            "date": current_date,
            "equity": capital + sum(p.entry_price * p.quantity for p in positions.values()),
            "trades": len(day_trades),
            "pnl": day_pnl,
        })

    return capital, all_trades, daily_records, positions, blocked_by_risk


def _old_strategy3_check(strategy, code, bar_idx, indicators):
    """OLD 모드: 전략3 원래 조건으로 진입 체크 (시간필터 9~14)."""
    if bar_idx < strategy.min_bars:
        return None
    n = indicators["n_bars"]
    if bar_idx >= n:
        return None

    atr = indicators["atr_10_pct"]
    rsi = indicators["rsi_14"]
    vwap = indicators["vwap"]
    closes = indicators["close"]
    hours = indicators["hours"]
    bullish_candle = indicators["bullish_candle"]

    hour = hours[bar_idx]
    # OLD: 원래 시간 조건
    if hour < 9 or hour >= 14:
        return None

    if np.isnan(atr[bar_idx]) or np.isnan(rsi[bar_idx]) or np.isnan(vwap[bar_idx]):
        return None
    if atr[bar_idx] < strategy.atr_threshold:
        return None
    if rsi[bar_idx] < 40 or rsi[bar_idx] > 60:
        return None
    if closes[bar_idx] <= vwap[bar_idx] * 1.002:
        return None
    if not bullish_candle[bar_idx - 1] or not bullish_candle[bar_idx - 2]:
        return None

    passes, hong_reason = strategy.passes_hong_filter()
    if not passes:
        return None
    if not strategy.passes_intraday_value_filter(bar_idx, indicators):
        return None

    return {
        "reason": f"OLD: rsi={rsi[bar_idx]:.2f}, atr={atr[bar_idx]:.4f}",
        "stop_loss": 0.03,
        "take_profit": 0.05,
        "confidence": 1.0 * strategy.hong_confidence_boost(),
    }


# ══════════════════════════════════════════════════════
#  결과 출력
# ══════════════════════════════════════════════════════
def print_result(final_capital, trades, daily_records, remaining_positions, label,
                 blocked_by_risk=0):
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

    avg_win = np.mean([t.pnl for t in trades if t.pnl > 0]) if n_wins else 0
    avg_loss = np.mean([t.pnl for t in trades if t.pnl <= 0]) if (n_trades - n_wins) else 0

    print(f"\n{'━' * 70}")
    print(f"  [{label}]")
    print(f"{'━' * 70}")
    print(f"  초기자금:     {INITIAL_CAPITAL:>14,}원")
    print(f"  최종자금:     {total_equity:>14,.0f}원")
    print(f"  총 손익:      {total_pnl:>+14,.0f}원 ({total_return:+.2f}%)")
    print(f"  거래비용:     {total_comm:>14,.0f}원")
    print(f"  거래수:       {n_trades:>14}건")
    print(f"  승률:         {wr:>13.1f}%  ({n_wins}W / {n_trades - n_wins}L)")
    print(f"  평균 수익:    {avg_win:>+14,.0f}원")
    print(f"  평균 손실:    {avg_loss:>+14,.0f}원")
    print(f"  MDD:          {max_dd:>13.2f}%")
    print(f"  기간:         {n_days:>14}일")

    if blocked_by_risk > 0:
        print(f"  리스크 차단:  {blocked_by_risk:>14}건")

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
    for reason in sorted(reason_stats.keys()):
        r = reason_stats[reason]
        print(f"  {reason:12s}: {r['count']:4d}건 | {r['pnl']:>+13,.0f}원")

    # 시간대별 (hour)
    hour_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        if hasattr(t.entry_time, "hour"):
            h = t.entry_time.hour
            hour_stats[h]["trades"] += 1
            if t.pnl > 0:
                hour_stats[h]["wins"] += 1
            hour_stats[h]["pnl"] += t.pnl

    print(f"\n  [시간대별]")
    for h in sorted(hour_stats.keys()):
        s = hour_stats[h]
        swr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
        print(f"  {h:2d}시: {s['trades']:4d}건 WR {swr:5.1f}% | {s['pnl']:>+10,.0f}원")

    return total_return, wr, max_dd, total_pnl


def main():
    print("=" * 70)
    print("  OLD vs NEW 알고리즘 비교 시뮬레이션")
    print(f"  자본금: {INITIAL_CAPITAL:,}원 | 최대 {MAX_POSITIONS}종목")
    print("  OLD: 시간대 9~14, SL 3%, TP 5%, 리스크관리 없음")
    print("  NEW: 시간대 9+10:45+11, 적응형 SL/TP, 연속3SL차단, 쿨다운, CB 2%")
    print("=" * 70)

    print("\n  데이터 로딩...")
    t0 = time_module.time()
    intraday_data, daily_by_date, all_dates = load_all_data()
    print(f"  5분봉: {len(intraday_data)}종목, {len(all_dates)}거래일")
    print(f"  기간: {min(all_dates)} ~ {max(all_dates)}")
    print(f"  로딩: {time_module.time() - t0:.1f}초")

    codes = list(intraday_data.keys())
    print(f"\n  일별 컨텍스트 로딩...")
    loader = DailyContextLoader()
    daily_context = loader.load(codes, min(all_dates), max(all_dates))
    print(f"  컨텍스트: {sum(len(v) for v in daily_context.values())}건")

    # 전체 기간 OLD
    print(f"\n  [OLD 시뮬레이션...]")
    t0 = time_module.time()
    cap_old, trades_old, daily_old, rem_old, blocked_old = run_simulation(
        intraday_data, daily_by_date, daily_context, all_dates, mode="OLD"
    )
    print(f"  완료: {time_module.time() - t0:.1f}초")
    ret_old, wr_old, dd_old, pnl_old = print_result(
        cap_old, trades_old, daily_old, rem_old, "OLD (기존)", blocked_old
    )

    # 전체 기간 NEW
    print(f"\n  [NEW 시뮬레이션...]")
    t0 = time_module.time()
    cap_new, trades_new, daily_new, rem_new, blocked_new = run_simulation(
        intraday_data, daily_by_date, daily_context, all_dates, mode="NEW"
    )
    print(f"  완료: {time_module.time() - t0:.1f}초")
    ret_new, wr_new, dd_new, pnl_new = print_result(
        cap_new, trades_new, daily_new, rem_new, "NEW (고도화)", blocked_new
    )

    # 비교 요약
    print(f"\n{'━' * 70}")
    print(f"  [비교 요약] {len(daily_old)}일 기간")
    print(f"{'━' * 70}")
    print(f"  {'항목':15s} {'OLD':>15s} {'NEW':>15s} {'개선':>15s}")
    print(f"  {'─' * 60}")
    print(f"  {'수익률':15s} {ret_old:>+14.2f}% {ret_new:>+14.2f}% {ret_new - ret_old:>+14.2f}%")
    print(f"  {'손익':15s} {pnl_old:>+14,.0f} {pnl_new:>+14,.0f} {pnl_new - pnl_old:>+14,.0f}")
    print(f"  {'승률':15s} {wr_old:>14.1f}% {wr_new:>14.1f}% {wr_new - wr_old:>+14.1f}%")
    print(f"  {'MDD':15s} {dd_old:>14.2f}% {dd_new:>14.2f}% {dd_new - dd_old:>+14.2f}%")
    print(f"  {'거래수':15s} {len(trades_old):>14} {len(trades_new):>14} {len(trades_new) - len(trades_old):>+14}")
    if blocked_new > 0:
        print(f"  {'리스크차단':15s} {'─':>14s} {blocked_new:>14} {'':>14s}")
    print(f"{'━' * 70}")


if __name__ == "__main__":
    main()
