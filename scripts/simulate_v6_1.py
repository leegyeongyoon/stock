"""
1000만원 실투자 시뮬레이션 v6 - 점수 기반 선별 시스템

OpenAI 분석 인사이트:
1. 승리 거래: 높은 종가 강도 (86% vs 66%)
2. 승리 거래: 높은 오전 등락률 (11% vs 9%)
3. 승리 거래: 높은 시가총액 (7만억 vs 4만억)
4. 패배 거래: 오후 낙폭 발생

v6 변경사항:
- 하드 필터 대신 점수 기반 선별
- 진입 시 품질 점수 계산하여 상위 종목만 진입
- 기존 조건은 유지하면서 추가 점수로 우선순위 결정
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from dataclasses import dataclass
import time as time_mod
from collections import defaultdict

END_DATE = "20260212"

# 리스크 파라미터
SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70
BREAKEVEN_CUT = 0.005

# 포지션 사이징
HIGH_CONF_PCT = 0.50
LOW_CONF_PCT = 0.30
MAX_POSITIONS = 3
MIN_CONFIDENCE = 0.70

# 기본 필터 (v5 기준 유지)
MIN_MARKET_CAP = 5000
MIN_INST_BUY = 50
MAX_INST_BUY = 200
SKIP_TOP_N = 1
ENTER_TOP_N = 4
MIN_DAILY_CHANGE = 6.0

# v6 점수 기반 선별 파라미터
MIN_QUALITY_SCORE = 60   # 최소 품질 점수 (100점 만점)
QUALITY_WEIGHT = {
    "market_cap": 15,     # 시가총액 점수 (최대 15점)
    "inst_buy": 15,       # 기관순매수 점수 (최대 15점)
    "daily_change": 20,   # 당일 등락률 점수 (최대 20점)
    "morning_change": 20, # 오전 등락률 점수 (최대 20점)
    "close_strength": 20, # 종가 강도 점수 (최대 20점) - 실시간 계산
    "leader_rank": 10,    # 리더 순위 점수 (최대 10점)
}

# 오버나잇 홀딩
MIN_OVERNIGHT_SCORE = 60
GAP_DOWN_STOP = -0.03

# 거래비용
COMMISSION = 0.00015
TAX = 0.0023

INITIAL_CAPITAL = 10_000_000

_kosdaq_set = None


def get_kosdaq_set():
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(END_DATE, market="KOSDAQ"))
    return _kosdaq_set


def code_to_ticker(code):
    return f"{code}{'.KQ' if code in get_kosdaq_set() else '.KS'}"


@dataclass
class Position:
    code: str
    name: str
    method: str
    entry_price: float
    quantity: int
    invested: float
    entry_time: str
    entry_date: str = ""
    partial_sold: bool = False
    original_quantity: int = 0
    is_overnight: bool = False
    overnight_score: int = 0
    quality_score: int = 0  # v6: 진입 시 품질 점수

    def __post_init__(self):
        if self.original_quantity == 0:
            self.original_quantity = self.quantity


@dataclass
class TradeResult:
    code: str
    name: str
    method: str
    date: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    commission_cost: float
    is_overnight: bool = False
    quality_score: int = 0


def get_trading_days(end_date, n_days=20):
    from datetime import timedelta
    end = pd.Timestamp(end_date)
    start = end - timedelta(days=60)
    df = pykrx_stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end_date, "005930")
    dates = [d.strftime("%Y%m%d") for d in df.index]
    return dates[-(n_days + 1):]


def fetch_daily_data(dates):
    print("=" * 70)
    print("  1. 일별 데이터 수집")
    print("=" * 70)
    daily_info = {}
    all_codes = set()

    for date in dates:
        df_ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(date, market="ALL")
        df_ohlcv = df_ohlcv[df_ohlcv["거래량"] > 0]
        df_cap = pykrx_stock.get_market_cap_by_ticker(date, market="ALL")

        if "시가총액" in df_ohlcv.columns:
            df = df_ohlcv.copy()
            df["시가총액"] = df_cap["시가총액"]
        else:
            df = df_ohlcv.join(df_cap[["시가총액"]], how="left")
        df["시가총액_억"] = df["시가총액"] / 1e8

        try:
            df_inst = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                date, date, market="KOSPI", investor="기관합계")
            df_inst_kq = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                date, date, market="KOSDAQ", investor="기관합계")
            inst_all = pd.concat([df_inst, df_inst_kq])
            df["기관순매수"] = inst_all["순매수거래대금"] / 1e8
        except Exception:
            df["기관순매수"] = 0

        top100 = set(df.nlargest(100, "거래대금").index.tolist())
        strong = set(df[df["등락률"] >= 3.0].index.tolist())
        universe = top100 | strong
        cap_filtered = set(df[df["시가총액_억"] >= MIN_MARKET_CAP].index.tolist())

        daily_info[date] = {"df": df, "universe": universe, "cap_filtered": cap_filtered}
        all_codes |= universe
        print(f"    {date}: {len(universe)}개")
        time_mod.sleep(0.3)

    return daily_info, all_codes


def fetch_5min_bulk(codes, dates):
    print("\n" + "=" * 70)
    print("  2. 5분봉 수집")
    print("=" * 70)
    bars_all = {}
    failed = 0
    batch_size = 20
    code_list = list(codes)
    date_set = set(pd.Timestamp(d).date() for d in dates)

    for bs in range(0, len(code_list), batch_size):
        batch = code_list[bs:bs + batch_size]
        tickers = [code_to_ticker(c) for c in batch]
        try:
            data = yf.download(" ".join(tickers), period="1mo", interval="5m",
                               progress=False, threads=True)
            if data.empty:
                failed += len(batch)
                continue
            for code in batch:
                ticker = code_to_ticker(code)
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if ticker in data.columns.get_level_values(1):
                            df = data.xs(ticker, level=1, axis=1).copy()
                        else:
                            failed += 1
                            continue
                    else:
                        df = data.copy()
                    df = df.dropna(subset=["Close"])
                    if df.empty:
                        failed += 1
                        continue
                    if df.index.tz is not None:
                        df.index = df.index.tz_convert("Asia/Seoul")
                    else:
                        df.index = df.index.tz_localize("UTC").tz_convert("Asia/Seoul")
                    bars_all[code] = {}
                    for d in date_set:
                        day = df[df.index.date == d]
                        if len(day) >= 10:
                            bars_all[code][d.strftime("%Y%m%d")] = day
                except Exception:
                    failed += 1
        except Exception:
            failed += len(batch)
        done = bs + len(batch)
        if (done // batch_size) % 10 == 0 and done > 0:
            print(f"    {done}/{len(code_list)}...")

    total_bars = sum(len(v) for v in bars_all.values())
    print(f"  완료: {len(bars_all)}종목, {total_bars}일별, {failed}실패")
    return bars_all


def select_leaders(bars_all, date, eligible_codes):
    scores = []
    for code in eligible_codes:
        if code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        morning = bars[(bars.index.hour == 9) & (bars.index.minute < 30)]
        if len(morning) < 2:
            continue
        vol_sum = morning["Volume"].sum()
        pchg = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
        momentum = vol_sum * max(pchg, 0)
        scores.append({"code": code, "momentum": momentum, "pchg": pchg, "vol_sum": vol_sum})
    scores.sort(key=lambda x: x["momentum"], reverse=True)
    return scores[:20]


def calc_quality_score(code, bars, df, prev_df, leader_rank, entry_time=None):
    """
    v6: 품질 점수 계산 (100점 만점)

    점수 구성:
    - 시가총액 (15점): 3만억+ = 15점, 1만억+ = 10점, 5천억+ = 5점
    - 기관순매수 (15점): 150억+ = 15점, 100억+ = 10점, 50억+ = 5점
    - 당일 등락률 (20점): 15%+ = 20점, 10%+ = 15점, 6%+ = 10점
    - 오전 등락률 (20점): 15%+ = 20점, 10%+ = 15점, 5%+ = 10점
    - 종가 강도 (20점): 90%+ = 20점, 75%+ = 15점, 60%+ = 10점
    - 리더 순위 (10점): TOP2 = 10점, TOP3 = 7점, TOP4 = 5점, TOP5 = 3점
    """
    score = 0
    score_breakdown = {}

    # 1. 시가총액 (15점)
    market_cap = df.loc[code, "시가총액_억"] if code in df.index else 0
    if market_cap >= 30000:
        cap_score = 15
    elif market_cap >= 10000:
        cap_score = 10
    elif market_cap >= 5000:
        cap_score = 5
    else:
        cap_score = 0
    score += cap_score
    score_breakdown["market_cap"] = cap_score

    # 2. 기관순매수 (15점)
    inst_buy = prev_df.loc[code, "기관순매수"] if prev_df is not None and code in prev_df.index else 0
    if inst_buy >= 150:
        inst_score = 15
    elif inst_buy >= 100:
        inst_score = 10
    elif inst_buy >= 50:
        inst_score = 5
    else:
        inst_score = 0
    score += inst_score
    score_breakdown["inst_buy"] = inst_score

    # 3. 당일 등락률 (20점)
    daily_change = df.loc[code, "등락률"] if code in df.index else 0
    if daily_change >= 15:
        daily_score = 20
    elif daily_change >= 10:
        daily_score = 15
    elif daily_change >= 6:
        daily_score = 10
    else:
        daily_score = 0
    score += daily_score
    score_breakdown["daily_change"] = daily_score

    # 4. 오전 등락률 (20점)
    morning_bars = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
    if not morning_bars.empty:
        morning_change = (morning_bars.iloc[-1]["Close"] / morning_bars.iloc[0]["Open"] - 1) * 100
    else:
        morning_change = 0

    if morning_change >= 15:
        morning_score = 20
    elif morning_change >= 10:
        morning_score = 15
    elif morning_change >= 5:
        morning_score = 10
    else:
        morning_score = 0
    score += morning_score
    score_breakdown["morning_change"] = morning_score

    # 5. 종가 강도 (20점) - 진입 시점까지의 강도
    if entry_time:
        bars_until = bars[bars.index <= entry_time]
    else:
        bars_until = bars

    if not bars_until.empty:
        day_high = bars_until["High"].max()
        day_low = bars_until["Low"].min()
        current_close = bars_until.iloc[-1]["Close"]
        if day_high > day_low:
            close_strength = (current_close - day_low) / (day_high - day_low) * 100
        else:
            close_strength = 50
    else:
        close_strength = 50

    if close_strength >= 90:
        close_score = 20
    elif close_strength >= 75:
        close_score = 15
    elif close_strength >= 60:
        close_score = 10
    else:
        close_score = 0
    score += close_score
    score_breakdown["close_strength"] = close_score

    # 6. 리더 순위 (10점)
    if leader_rank == 2:  # TOP1은 스킵하므로 실제 진입은 TOP2부터
        rank_score = 10
    elif leader_rank == 3:
        rank_score = 7
    elif leader_rank == 4:
        rank_score = 5
    elif leader_rank == 5:
        rank_score = 3
    else:
        rank_score = 0
    score += rank_score
    score_breakdown["leader_rank"] = rank_score

    return score, score_breakdown


def find_breakout(bars):
    window = bars[
        ((bars.index.hour == 9) & (bars.index.minute >= 30)) |
        (bars.index.hour == 10)
    ]
    if len(window) < 6:
        return None
    for i in range(5, len(window)):
        ph = window["High"].iloc[i-5:i].max()
        bar = window.iloc[i]
        if bar["High"] > ph and bar["Close"] > ph:
            av = window["Volume"].iloc[i-5:i].mean()
            if av > 0 and bar["Volume"] >= av * 1.2:
                return {"price": bar["Close"], "time": window.index[i], "confidence": 0.75}
    return None


def find_pullback(bars, vol_median):
    morning_full = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
    if morning_full.empty:
        return None
    morning_vol = morning_full["Volume"].sum()
    if morning_vol < vol_median:
        return None

    window = bars[
        (bars.index.hour >= 13) & (bars.index.hour < 15) &
        ~((bars.index.hour == 14) & (bars.index.minute > 30))
    ]
    if len(window) < 5:
        return None

    morning = bars[bars.index.hour < 12]
    if morning.empty:
        return None
    mh = morning["High"].max()
    ml = morning["Low"].min()
    r50 = mh - (mh - ml) * 0.5

    for i in range(2, len(window)):
        bar = window.iloc[i]
        prev = window.iloc[i - 1]
        if (prev["Low"] <= mh * 0.95 and
            bar["Close"] > prev["Close"] and
            bar["Close"] > r50 and
            bar["Low"] > ml):
            return {"price": bar["Close"], "time": window.index[i], "confidence": 0.6}
    return None


def get_morning_vol_median(bars_all, date, leader_codes):
    vols = []
    for code in leader_codes:
        if code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        morning = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
        if not morning.empty:
            vols.append(morning["Volume"].sum())
    return np.median(vols) if vols else 0


def calc_transaction_cost(price, qty, side="buy"):
    value = price * qty
    cost = value * COMMISSION
    if side == "sell":
        cost += value * TAX
    return cost


@dataclass
class OvernightScore:
    total_score: int
    should_hold: bool
    components: dict
    reasons: list


def evaluate_overnight_holding(code, pos, bars, daily_info, date, leaders):
    score = 0
    components = {}
    reasons = []

    if bars.empty:
        return OvernightScore(0, False, {}, ["데이터 없음"])

    last_bar = bars.iloc[-1]
    current_price = last_bar["Close"]
    pnl_pct = (current_price / pos.entry_price - 1) * 100

    if pnl_pct < 0:
        return OvernightScore(0, False, {}, [f"현재 손실 중 ({pnl_pct:.2f}%)"])

    day_high = bars["High"].max()
    day_open = bars.iloc[0]["Open"]
    if current_price < day_open and (day_high - current_price) > (current_price - bars["Low"].min()) * 2:
        return OvernightScore(0, False, {}, ["고점 패턴 감지 (가분수형)"])

    morning_bars = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
    afternoon_bars = bars[(bars.index.hour >= 12) & (bars.index.hour < 16)]
    if not morning_bars.empty and not afternoon_bars.empty:
        morning_vol = morning_bars["Volume"].sum()
        afternoon_vol = afternoon_bars["Volume"].sum()
        if afternoon_vol < morning_vol * 0.3:
            return OvernightScore(0, False, {}, ["거래량 고점 패턴 (오후 급감)"])

    ki_score = 0
    df = daily_info.get(date, {}).get("df")
    if df is not None and code in df.index:
        row = df.loc[code]
        chg = row.get("등락률", 0)
        vol_rank = df["거래대금"].rank(ascending=False).get(code, 100)
        ki_est = max(0, min(chg * 5 + (100 - vol_rank) * 0.3, 100))
        if ki_est >= 50:
            ki_score = 30
        elif ki_est >= 40:
            ki_score = 20
        elif ki_est >= 30:
            ki_score = 10
        components["ki"] = ki_score
        if ki_score > 0:
            reasons.append(f"끼점수 추정 {ki_est:.0f} → +{ki_score}점")
    score += ki_score

    leader_codes = [l["code"] for l in leaders[:5]]
    if code in leader_codes:
        rank = leader_codes.index(code) + 1
        leader_score = 20 if rank <= 2 else 15 if rank <= 3 else 10
        score += leader_score
        components["leader"] = leader_score
        reasons.append(f"대장주 TOP{rank} → +{leader_score}점")
    else:
        components["leader"] = 0

    daily_score = 0
    if df is not None and code in df.index:
        row = df.loc[code]
        chg = row.get("등락률", 0)
        if chg >= 10:
            daily_score = 20
            reasons.append("일봉 신고가급 상승 → +20점")
        elif chg >= 5:
            daily_score = 15
            reasons.append("일봉 전고점 돌파 가능 → +15점")
        elif chg >= 3:
            daily_score = 10
            reasons.append("일봉 바닥 반등 → +10점")
    score += daily_score
    components["daily_position"] = daily_score

    d1_score = 0
    if df is not None and code in df.index:
        row = df.loc[code]
        chg = row.get("등락률", 0)
        if chg >= 5:
            d1_score = 15
            reasons.append(f"D+1 후보 (오늘 +{chg:.1f}%) → +15점")
        elif chg >= 3:
            d1_score = 10
            reasons.append(f"D+1 가능 (오늘 +{chg:.1f}%) → +10점")
    score += d1_score
    components["d1_candidate"] = d1_score

    vol_score = 0
    if not morning_bars.empty and not afternoon_bars.empty:
        morning_vol = morning_bars["Volume"].sum()
        afternoon_vol = afternoon_bars["Volume"].sum()
        if morning_vol > 0:
            vol_ratio = afternoon_vol / morning_vol
            if vol_ratio >= 0.8:
                vol_score = 15
                reasons.append(f"오후거래량 충분 ({vol_ratio:.1%}) → +15점")
            elif vol_ratio >= 0.6:
                vol_score = 10
                reasons.append(f"오후거래량 적정 ({vol_ratio:.1%}) → +10점")
            elif vol_ratio >= 0.4:
                vol_score = 5
                reasons.append(f"오후거래량 보통 ({vol_ratio:.1%}) → +5점")
    score += vol_score
    components["afternoon_vol"] = vol_score

    should_hold = score >= MIN_OVERNIGHT_SCORE

    return OvernightScore(
        total_score=score,
        should_hold=should_hold,
        components=components,
        reasons=reasons
    )


def simulate_day(bars_all, daily_info, date, prev_date, capital, positions, overnight_stats, quality_stats):
    """v6: 품질 점수 기반 선별"""
    info = daily_info[date]
    df = info["df"]
    universe = info["universe"]
    cap_filtered = info["cap_filtered"]
    prev_df = daily_info[prev_date]["df"] if prev_date in daily_info else None

    eligible = universe & cap_filtered

    if prev_df is not None:
        inst_range = set(prev_df[
            (prev_df["기관순매수"] >= MIN_INST_BUY) & (prev_df["기관순매수"] <= MAX_INST_BUY)
        ].index.tolist())
        eligible = eligible & inst_range

    leaders = select_leaders(bars_all, date, eligible)
    leaders_filtered = leaders[SKIP_TOP_N:SKIP_TOP_N + ENTER_TOP_N]
    leader_codes = [s["code"] for s in leaders_filtered]
    vol_median = get_morning_vol_median(bars_all, date, leader_codes)

    trades_today = []
    skipped_reasons = defaultdict(int)

    # 오버나잇 포지션 갭하락 손절 체크
    codes_overnight = [c for c, p in positions.items() if p.is_overnight]
    for code in codes_overnight:
        if code not in bars_all or date not in bars_all[code]:
            continue
        pos = positions[code]
        bars = bars_all[code][date]
        if bars.empty:
            continue

        open_price = bars.iloc[0]["Open"]
        gap_pct = (open_price / pos.entry_price - 1)

        if gap_pct <= GAP_DOWN_STOP:
            sell_qty = pos.quantity
            cost = calc_transaction_cost(open_price, sell_qty, "sell")
            pnl = (open_price - pos.entry_price) * sell_qty - cost
            pnl_pct = gap_pct * 100

            trades_today.append(TradeResult(
                code=code, name=pos.name, method=pos.method, date=date,
                entry_time=pos.entry_time, entry_price=pos.entry_price,
                exit_time=str(bars.index[0])[:16], exit_price=open_price,
                quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
                exit_reason="갭하락손절", commission_cost=cost, is_overnight=True,
                quality_score=pos.quality_score,
            ))
            capital += open_price * sell_qty - cost
            overnight_stats["gap_stop"] += 1
            overnight_stats["gap_stop_pnl"] += pnl
            del positions[code]
        else:
            pos.is_overnight = False
            overnight_stats["success"] += 1

    # 보유 포지션 모니터링
    codes_to_monitor = list(positions.keys())
    for code in codes_to_monitor:
        if code not in bars_all or date not in bars_all[code]:
            continue
        pos = positions[code]
        bars = bars_all[code][date]

        for ts, bar in bars.iterrows():
            lo_pct = (bar["Low"] / pos.entry_price) - 1
            hi_pct = (bar["High"] / pos.entry_price) - 1

            if lo_pct <= SL_PCT:
                exit_price = pos.entry_price * (1 + SL_PCT)
                sell_qty = pos.quantity
                cost = calc_transaction_cost(exit_price, sell_qty, "sell")
                pnl = (exit_price - pos.entry_price) * sell_qty - cost
                pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

                trades_today.append(TradeResult(
                    code=code, name=pos.name, method=pos.method, date=date,
                    entry_time=pos.entry_time, entry_price=pos.entry_price,
                    exit_time=str(ts)[:16], exit_price=exit_price,
                    quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
                    exit_reason="손절", commission_cost=cost,
                    quality_score=pos.quality_score,
                ))
                capital += exit_price * sell_qty - cost
                del positions[code]
                break

            if hi_pct >= TP_PCT and not pos.partial_sold:
                exit_price = pos.entry_price * (1 + TP_PCT)
                sell_qty = int(pos.quantity * TP_PARTIAL)
                if sell_qty <= 0:
                    sell_qty = pos.quantity

                cost = calc_transaction_cost(exit_price, sell_qty, "sell")
                pnl = (exit_price - pos.entry_price) * sell_qty - cost
                pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

                trades_today.append(TradeResult(
                    code=code, name=pos.name, method=pos.method, date=date,
                    entry_time=pos.entry_time, entry_price=pos.entry_price,
                    exit_time=str(ts)[:16], exit_price=exit_price,
                    quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
                    exit_reason="1차익절", commission_cost=cost,
                    quality_score=pos.quality_score,
                ))
                capital += exit_price * sell_qty - cost
                pos.quantity -= sell_qty
                pos.partial_sold = True

                if pos.quantity <= 0:
                    del positions[code]
                    break
                continue

            if pos.partial_sold and lo_pct <= BREAKEVEN_CUT:
                exit_price = bar["Close"]
                sell_qty = pos.quantity
                cost = calc_transaction_cost(exit_price, sell_qty, "sell")
                pnl = (exit_price - pos.entry_price) * sell_qty - cost
                pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

                trades_today.append(TradeResult(
                    code=code, name=pos.name, method=pos.method, date=date,
                    entry_time=pos.entry_time, entry_price=pos.entry_price,
                    exit_time=str(ts)[:16], exit_price=exit_price,
                    quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
                    exit_reason="본전컷", commission_cost=cost,
                    quality_score=pos.quality_score,
                ))
                capital += exit_price * sell_qty - cost
                del positions[code]
                break

    # v6: 신규 진입 - 품질 점수 기반 선별
    entries = []
    for rank_idx, s in enumerate(leaders_filtered):
        code = s["code"]
        rank = SKIP_TOP_N + rank_idx + 1  # 실제 순위

        if code in positions:
            skipped_reasons["이미보유"] += 1
            continue
        if code not in bars_all or date not in bars_all[code]:
            continue

        # 당일 등락률 필터
        if code in df.index:
            daily_change = df.loc[code, "등락률"]
            if daily_change < MIN_DAILY_CHANGE:
                skipped_reasons["등락률부족"] += 1
                continue

        bars = bars_all[code][date]

        # 돌파매매
        entry = find_breakout(bars)
        if entry:
            quality_score, breakdown = calc_quality_score(
                code, bars, df, prev_df, rank, entry["time"]
            )
            entries.append({
                "code": code, "entry": entry, "method": "돌파",
                "momentum": s["momentum"], "quality_score": quality_score,
                "leader_rank": rank, "breakdown": breakdown
            })

        # 눌림매매
        entry = find_pullback(bars, vol_median)
        if entry:
            quality_score, breakdown = calc_quality_score(
                code, bars, df, prev_df, rank, entry["time"]
            )
            # 중복 체크
            if not any(e["code"] == code and e["method"] == "돌파" for e in entries):
                entries.append({
                    "code": code, "entry": entry, "method": "눌림",
                    "momentum": s["momentum"], "quality_score": quality_score,
                    "leader_rank": rank, "breakdown": breakdown
                })

    # v6: 품질 점수 순으로 정렬
    entries.sort(key=lambda x: x["quality_score"], reverse=True)

    for e in entries:
        if len(positions) >= MAX_POSITIONS:
            skipped_reasons["최대보유초과"] += 1
            continue

        code = e["code"]
        entry = e["entry"]
        price = entry["price"]
        conf = entry["confidence"]
        quality_score = e["quality_score"]

        # 확신도 필터
        if conf < MIN_CONFIDENCE:
            skipped_reasons["확신도부족"] += 1
            continue

        # v6: 품질 점수 필터
        if quality_score < MIN_QUALITY_SCORE:
            skipped_reasons["품질부족"] += 1
            quality_stats["filtered_low_quality"] += 1
            continue

        quality_stats["total_entries"] += 1
        quality_stats["score_sum"] += quality_score
        quality_stats["by_score"][quality_score // 10 * 10] += 1

        alloc_pct = HIGH_CONF_PCT if conf >= 0.7 else LOW_CONF_PCT
        invest_amount = capital * alloc_pct

        qty = int(invest_amount / price)
        if qty <= 0:
            skipped_reasons["자금부족"] += 1
            continue

        if price * qty < 100_000:
            skipped_reasons["소액스킵"] += 1
            continue

        buy_cost = calc_transaction_cost(price, qty, "buy")
        total_cost = price * qty + buy_cost

        if total_cost > capital:
            qty = int((capital - buy_cost) / price)
            if qty <= 0:
                skipped_reasons["자금부족"] += 1
                continue
            buy_cost = calc_transaction_cost(price, qty, "buy")
            total_cost = price * qty + buy_cost

        name = pykrx_stock.get_market_ticker_name(code) or code
        capital -= total_cost

        positions[code] = Position(
            code=code, name=name, method=e["method"],
            entry_price=price, quantity=qty,
            invested=price * qty,
            entry_time=str(entry["time"])[:16],
            entry_date=date,
            quality_score=quality_score,
        )

    # 장마감 청산 또는 오버나잇 홀딩
    codes_remaining = list(positions.keys())
    for code in codes_remaining:
        if code not in bars_all or date not in bars_all[code]:
            continue
        pos = positions[code]
        bars = bars_all[code][date]
        if bars.empty:
            continue

        overnight_result = evaluate_overnight_holding(
            code, pos, bars, daily_info, date, leaders
        )

        if overnight_result.should_hold:
            pos.is_overnight = True
            pos.overnight_score = overnight_result.total_score
            overnight_stats["total"] += 1
            overnight_stats["held_codes"].append({
                "code": code,
                "name": pos.name,
                "date": date,
                "score": overnight_result.total_score,
                "reasons": overnight_result.reasons,
            })
            continue

        last_bar = bars.iloc[-1]
        exit_price = last_bar["Close"]
        sell_qty = pos.quantity
        cost = calc_transaction_cost(exit_price, sell_qty, "sell")
        pnl = (exit_price - pos.entry_price) * sell_qty - cost
        pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

        trades_today.append(TradeResult(
            code=code, name=pos.name, method=pos.method, date=date,
            entry_time=pos.entry_time, entry_price=pos.entry_price,
            exit_time=str(bars.index[-1])[:16], exit_price=exit_price,
            quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
            exit_reason="장마감", commission_cost=cost,
            quality_score=pos.quality_score,
        ))
        capital += exit_price * sell_qty - cost
        del positions[code]

    return capital, trades_today, skipped_reasons


def main():
    print("=" * 70)
    print("  1000만원 실투자 시뮬레이션 v6 (품질 점수 기반)")
    print("=" * 70)
    print(f"  초기자금: {INITIAL_CAPITAL:,}원")
    print(f"  기본 필터: 시총{MIN_MARKET_CAP}억+ / 기관{MIN_INST_BUY}~{MAX_INST_BUY}억 / 등락률{MIN_DAILY_CHANGE}%+")
    print(f"  진입: TOP{SKIP_TOP_N+1}~{SKIP_TOP_N+ENTER_TOP_N}")
    print(f"  v6 품질 점수: 최소 {MIN_QUALITY_SCORE}점 (100점 만점)")
    print(f"  SL {SL_PCT*100:.0f}% / TP {TP_PCT*100:.0f}% ({TP_PARTIAL*100:.0f}%분매)")
    print("=" * 70)

    dates_all = get_trading_days(END_DATE, 20)
    prev_dates = dates_all[:-1]
    trade_dates = dates_all[1:]
    print(f"\n  매매일 {len(trade_dates)}일: {trade_dates[0]}~{trade_dates[-1]}")

    daily_info, all_codes = fetch_daily_data(dates_all)
    bars_all = fetch_5min_bulk(all_codes, trade_dates)

    print("\n" + "=" * 70)
    print("  3. 실투자 시뮬레이션 (v6 품질 점수)")
    print("=" * 70)

    capital = INITIAL_CAPITAL
    positions = {}
    all_trades = []
    all_skipped = defaultdict(int)
    daily_log = []

    overnight_stats = {
        "total": 0,
        "success": 0,
        "gap_stop": 0,
        "gap_stop_pnl": 0,
        "held_codes": [],
    }

    quality_stats = {
        "total_entries": 0,
        "score_sum": 0,
        "by_score": defaultdict(int),
        "filtered_low_quality": 0,
    }

    for i, date in enumerate(trade_dates):
        prev_date = prev_dates[i]
        day_start_capital = capital + sum(
            p.entry_price * p.quantity for p in positions.values()
        )

        capital, trades, skipped = simulate_day(
            bars_all, daily_info, date, prev_date, capital, positions, overnight_stats, quality_stats
        )
        all_trades.extend(trades)
        for k, v in skipped.items():
            all_skipped[k] += v

        day_pnl = sum(t.pnl for t in trades)
        day_end_capital = capital + sum(
            p.entry_price * p.quantity for p in positions.values()
        )

        d_fmt = f"{date[4:6]}/{date[6:]}"
        daily_log.append({
            "date": d_fmt,
            "trades": len(trades),
            "pnl": day_pnl,
            "capital": day_end_capital,
        })

        wins = sum(1 for t in trades if t.pnl > 0)
        print(f"    {d_fmt}: {len(trades)}거래 "
              f"({wins}W {len(trades)-wins}L) "
              f"PnL {day_pnl:+,.0f}원 "
              f"자산 {day_end_capital:,.0f}원")

    # 잔여 포지션 청산
    if positions:
        print(f"\n  [시뮬레이션 종료] 잔여 포지션 {len(positions)}건 강제 청산")
        last_date = trade_dates[-1]
        for code in list(positions.keys()):
            pos = positions[code]
            if code in bars_all and last_date in bars_all[code]:
                bars = bars_all[code][last_date]
                if not bars.empty:
                    exit_price = bars.iloc[-1]["Close"]
                    sell_qty = pos.quantity
                    cost = calc_transaction_cost(exit_price, sell_qty, "sell")
                    pnl = (exit_price - pos.entry_price) * sell_qty - cost
                    pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

                    all_trades.append(TradeResult(
                        code=code, name=pos.name, method=pos.method, date=last_date,
                        entry_time=pos.entry_time, entry_price=pos.entry_price,
                        exit_time="종료청산", exit_price=exit_price,
                        quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
                        exit_reason="종료청산", commission_cost=cost, is_overnight=True,
                        quality_score=pos.quality_score,
                    ))
                    capital += exit_price * sell_qty - cost
                    print(f"    {pos.name}({code}): {pnl:+,.0f}원 ({pnl_pct:+.2f}%)")
                    del positions[code]

    # 결과
    print("\n" + "=" * 70)
    print("  4. 최종 결과")
    print("=" * 70)

    final_capital = capital
    total_pnl = final_capital - INITIAL_CAPITAL
    total_return = (final_capital / INITIAL_CAPITAL - 1) * 100
    total_trades = len(all_trades)
    total_wins = sum(1 for t in all_trades if t.pnl > 0)
    total_commission = sum(t.commission_cost for t in all_trades)

    print(f"\n  초기자금:     {INITIAL_CAPITAL:>12,}원")
    print(f"  최종자금:     {final_capital:>12,.0f}원")
    print(f"  총 수익:      {total_pnl:>+12,.0f}원 ({total_return:+.2f}%)")
    print(f"  총 거래비용:  {total_commission:>12,.0f}원")
    print(f"  총 거래:      {total_trades:>8}건")
    print(f"  승률:         {total_wins/total_trades*100 if total_trades else 0:>7.1f}%")
    print(f"  승: {total_wins}건 / 패: {total_trades - total_wins}건")

    # v6: 품질 점수별 성과
    print(f"\n  [v6 품질 점수 분석]")
    print(f"    진입 건수: {quality_stats['total_entries']}건")
    if quality_stats['total_entries'] > 0:
        avg_score = quality_stats['score_sum'] / quality_stats['total_entries']
        print(f"    평균 점수: {avg_score:.1f}점")
    print(f"    품질 부족 스킵: {quality_stats['filtered_low_quality']}건")

    # 점수대별 성과
    print(f"\n  [품질 점수대별 거래 성과]")
    for score_range in sorted(quality_stats['by_score'].keys(), reverse=True):
        count = quality_stats['by_score'][score_range]
        trades_in_range = [t for t in all_trades if score_range <= t.quality_score < score_range + 10]
        if trades_in_range:
            wins_in_range = sum(1 for t in trades_in_range if t.pnl > 0)
            pnl_in_range = sum(t.pnl for t in trades_in_range)
            wr = wins_in_range / len(trades_in_range) * 100
            print(f"    {score_range}~{score_range+9}점: {len(trades_in_range)}건, "
                  f"승률 {wr:.1f}%, PnL {pnl_in_range:+,.0f}원")

    # 방법별
    print(f"\n  [방법별]")
    for m in ["돌파", "눌림"]:
        ts = [t for t in all_trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl > 0)
            mp = sum(t.pnl for t in ts)
            print(f"    {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | "
                  f"WR {mw/len(ts)*100:.1f}% | {mp:+,.0f}원")

    # 청산사유별
    print(f"\n  [청산사유별]")
    for reason in ["1차익절", "손절", "본전컷", "장마감", "갭하락손절", "종료청산"]:
        ts = [t for t in all_trades if t.exit_reason == reason]
        if ts:
            mp = sum(t.pnl for t in ts)
            print(f"    {reason}: {len(ts)}건 | {mp:+,.0f}원")

    # 오버나잇 홀딩 통계
    if overnight_stats["total"] > 0:
        print(f"\n  [오버나잇 홀딩]")
        print(f"    시도: {overnight_stats['total']}건")
        print(f"    성공: {overnight_stats['success']}건")
        print(f"    갭하락손절: {overnight_stats['gap_stop']}건 | {overnight_stats['gap_stop_pnl']:+,.0f}원")

    # 스킵 사유
    if all_skipped:
        print(f"\n  [진입 스킵 사유]")
        for reason, cnt in sorted(all_skipped.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {cnt}건")

    # 일별 요약
    print(f"\n  [일별]")
    print(f"  {'날짜':8s} {'거래':>4s} {'PnL':>12s} {'자산':>14s}")
    print(f"  {'─'*42}")
    for d in daily_log:
        print(f"  {d['date']:8s} {d['trades']:4d} {d['pnl']:>+12,.0f}원 {d['capital']:>14,.0f}원")

    # 최대 낙폭
    peak = INITIAL_CAPITAL
    max_dd = 0
    for d in daily_log:
        peak = max(peak, d["capital"])
        dd = (d["capital"] - peak) / peak * 100
        max_dd = min(max_dd, dd)
    print(f"\n  최대 낙폭(MDD): {max_dd:.2f}%")

    monthly_est = total_return / 20 * 22
    print(f"  월 환산 수익률: {monthly_est:+.2f}% ({total_pnl / 20 * 22:+,.0f}원/월)")


if __name__ == "__main__":
    main()
