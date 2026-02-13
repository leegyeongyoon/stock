"""
OpenAI 고급 반복 분석 v2.0
- 15회 반복 분석
- 20일/60일 교차 검증
- 새로운 조건 발견 및 추가
- 승리/패배 거래 패턴 심층 분석
"""

import warnings
warnings.filterwarnings("ignore")

import json
import os
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
import time as time_mod

from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from openai import OpenAI

# OpenAI 클라이언트
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

END_DATE = "20260212"


def to_python_type(obj):
    """numpy 타입을 Python 기본 타입으로 변환"""
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: to_python_type(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_python_type(item) for item in obj]
    elif pd.isna(obj):
        return None
    return obj


@dataclass
class StrategyParams:
    """전략 파라미터"""
    # 기본 리스크
    sl_pct: float = -0.04
    tp_pct: float = 0.05
    tp_partial: float = 0.70
    max_positions: int = 3
    min_confidence: float = 0.70

    # 기본 필터
    min_market_cap: int = 5000
    min_inst_buy: int = 50
    max_inst_buy: int = 200
    skip_top_n: int = 1
    enter_top_n: int = 4
    min_daily_change: float = 6.0

    # v6 품질 점수
    min_quality_score: int = 60
    skip_score_70_79: bool = True

    # 추가 조건 (발견될 수 있음)
    min_morning_change: Optional[float] = None
    min_close_strength: Optional[float] = None
    max_afternoon_drop: Optional[float] = None
    min_volume_ratio: Optional[float] = None
    min_momentum: Optional[float] = None
    max_leader_rank: Optional[int] = None
    min_prev_day_change: Optional[float] = None  # 전일 등락률
    min_consecutive_up: Optional[int] = None     # 연속 상승일
    max_gap_up: Optional[float] = None           # 최대 갭 상승
    min_intraday_range: Optional[float] = None   # 최소 일중 변동폭
    max_high_tail: Optional[float] = None        # 최대 윗꼬리
    min_body_ratio: Optional[float] = None       # 최소 몸통 비율

    def to_dict(self):
        return to_python_type(asdict(self))


@dataclass
class TradeData:
    """거래 데이터 (분석용)"""
    code: str
    name: str
    date: str
    method: str
    entry_time: str
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    quality_score: int
    is_win: bool

    # 분석용 추가 데이터
    market_cap: float = 0
    inst_buy: float = 0
    daily_change: float = 0
    morning_change: float = 0
    close_strength: float = 0
    leader_rank: int = 0
    afternoon_change: float = 0
    volume_ratio: float = 0
    momentum: float = 0
    prev_day_change: float = 0
    gap_pct: float = 0
    intraday_range: float = 0
    high_tail_pct: float = 0
    body_ratio: float = 0

    def to_dict(self):
        return to_python_type(asdict(self))


# 캐시
_kosdaq_set = None
_daily_cache = {}
_bars_cache = {}


def get_kosdaq_set():
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(END_DATE, market="KOSDAQ"))
    return _kosdaq_set


def code_to_ticker(code):
    return f"{code}{'.KQ' if code in get_kosdaq_set() else '.KS'}"


def get_trading_days(end_date, n_days):
    from datetime import timedelta
    end = pd.Timestamp(end_date)
    start = end - timedelta(days=90)
    df = pykrx_stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end_date, "005930")
    dates = [d.strftime("%Y%m%d") for d in df.index]
    return dates[-(n_days + 1):]


def fetch_daily_data(dates):
    """일별 데이터 수집 (캐시 사용)"""
    global _daily_cache

    daily_info = {}
    all_codes = set()

    for date in dates:
        if date in _daily_cache:
            daily_info[date] = _daily_cache[date]
            all_codes |= daily_info[date]["universe"]
            continue

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

        daily_info[date] = {"df": df, "universe": universe}
        _daily_cache[date] = daily_info[date]
        all_codes |= universe
        time_mod.sleep(0.2)

    return daily_info, all_codes


def fetch_5min_bulk(codes, dates):
    """5분봉 수집 (캐시 사용)"""
    global _bars_cache

    bars_all = {}
    to_fetch = []
    date_set = set(pd.Timestamp(d).date() for d in dates)

    for code in codes:
        if code in _bars_cache:
            bars_all[code] = _bars_cache[code]
        else:
            to_fetch.append(code)

    if not to_fetch:
        return bars_all

    batch_size = 20
    for bs in range(0, len(to_fetch), batch_size):
        batch = to_fetch[bs:bs + batch_size]
        tickers = [code_to_ticker(c) for c in batch]
        try:
            data = yf.download(" ".join(tickers), period="1mo", interval="5m",
                               progress=False, threads=True)
            if data.empty:
                continue
            for code in batch:
                ticker = code_to_ticker(code)
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if ticker in data.columns.get_level_values(1):
                            df = data.xs(ticker, level=1, axis=1).copy()
                        else:
                            continue
                    else:
                        df = data.copy()
                    df = df.dropna(subset=["Close"])
                    if df.empty:
                        continue
                    if df.index.tz is not None:
                        df.index = df.index.tz_convert("Asia/Seoul")
                    else:
                        df.index = df.index.tz_localize("UTC").tz_convert("Asia/Seoul")
                    bars_all[code] = {}
                    _bars_cache[code] = {}
                    for d in date_set:
                        day = df[df.index.date == d]
                        if len(day) >= 10:
                            bars_all[code][d.strftime("%Y%m%d")] = day
                            _bars_cache[code][d.strftime("%Y%m%d")] = day
                except Exception:
                    pass
        except Exception:
            pass

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
        scores.append({"code": code, "momentum": momentum, "pchg": pchg})
    scores.sort(key=lambda x: x["momentum"], reverse=True)
    return scores[:20]


def calc_extended_features(code, bars, df, prev_df, leader_rank, entry_time=None):
    """확장된 특성 계산"""
    features = {
        "market_cap": 0,
        "inst_buy": 0,
        "daily_change": 0,
        "morning_change": 0,
        "close_strength": 0,
        "leader_rank": leader_rank,
        "afternoon_change": 0,
        "volume_ratio": 0,
        "momentum": 0,
        "prev_day_change": 0,
        "gap_pct": 0,
        "intraday_range": 0,
        "high_tail_pct": 0,
        "body_ratio": 0,
        "quality_score": 0,
    }

    # 기본 데이터
    if code in df.index:
        features["market_cap"] = float(df.loc[code, "시가총액_억"])
        features["daily_change"] = float(df.loc[code, "등락률"])

    if prev_df is not None and code in prev_df.index:
        features["inst_buy"] = float(prev_df.loc[code, "기관순매수"])
        features["prev_day_change"] = float(prev_df.loc[code, "등락률"])

    if bars.empty:
        return features

    # 오전 등락률
    morning_bars = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
    if not morning_bars.empty:
        features["morning_change"] = (
            morning_bars.iloc[-1]["Close"] / morning_bars.iloc[0]["Open"] - 1
        ) * 100
        morning_vol = morning_bars["Volume"].sum()
    else:
        morning_vol = 0

    # 오후 등락률
    afternoon_bars = bars[(bars.index.hour >= 12) & (bars.index.hour < 16)]
    if not afternoon_bars.empty and not morning_bars.empty:
        features["afternoon_change"] = (
            afternoon_bars.iloc[-1]["Close"] / morning_bars.iloc[-1]["Close"] - 1
        ) * 100
        afternoon_vol = afternoon_bars["Volume"].sum()
        if morning_vol > 0:
            features["volume_ratio"] = afternoon_vol / morning_vol

    # 종가 강도
    if entry_time:
        bars_until = bars[bars.index <= entry_time]
    else:
        bars_until = bars

    if not bars_until.empty:
        day_high = bars_until["High"].max()
        day_low = bars_until["Low"].min()
        current_close = bars_until.iloc[-1]["Close"]
        if day_high > day_low:
            features["close_strength"] = (current_close - day_low) / (day_high - day_low) * 100

    # 갭
    if not bars.empty:
        day_open = bars.iloc[0]["Open"]
        if prev_df is not None and code in prev_df.index:
            prev_close = prev_df.loc[code, "종가"]
            if prev_close > 0:
                features["gap_pct"] = (day_open / prev_close - 1) * 100

    # 일중 변동폭
    if not bars.empty:
        day_high = bars["High"].max()
        day_low = bars["Low"].min()
        if day_low > 0:
            features["intraday_range"] = (day_high - day_low) / day_low * 100

    # 윗꼬리 / 몸통 비율
    if not bars.empty:
        day_open = bars.iloc[0]["Open"]
        day_close = bars.iloc[-1]["Close"]
        day_high = bars["High"].max()
        day_low = bars["Low"].min()

        body = abs(day_close - day_open)
        total_range = day_high - day_low

        if total_range > 0:
            features["body_ratio"] = body / total_range * 100
            upper_shadow = day_high - max(day_open, day_close)
            features["high_tail_pct"] = upper_shadow / total_range * 100

    # 모멘텀
    if not morning_bars.empty:
        features["momentum"] = morning_vol * max(features["morning_change"], 0)

    # 품질 점수 계산
    score = 0

    # 시가총액 (15점)
    mc = features["market_cap"]
    if mc >= 30000:
        score += 15
    elif mc >= 10000:
        score += 10
    elif mc >= 5000:
        score += 5

    # 기관순매수 (15점)
    ib = features["inst_buy"]
    if ib >= 150:
        score += 15
    elif ib >= 100:
        score += 10
    elif ib >= 50:
        score += 5

    # 당일 등락률 (20점)
    dc = features["daily_change"]
    if dc >= 15:
        score += 20
    elif dc >= 10:
        score += 15
    elif dc >= 6:
        score += 10

    # 오전 등락률 (20점)
    mc = features["morning_change"]
    if mc >= 15:
        score += 20
    elif mc >= 10:
        score += 15
    elif mc >= 5:
        score += 10

    # 종가 강도 (20점)
    cs = features["close_strength"]
    if cs >= 90:
        score += 20
    elif cs >= 75:
        score += 15
    elif cs >= 60:
        score += 10

    # 리더 순위 (10점)
    lr = leader_rank
    if lr == 2:
        score += 10
    elif lr == 3:
        score += 7
    elif lr == 4:
        score += 5
    elif lr == 5:
        score += 3

    features["quality_score"] = score

    return features


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


def should_skip_by_params(features: dict, params: StrategyParams) -> tuple:
    """파라미터 기반 스킵 여부 판단"""
    # 품질 점수 필터
    if features["quality_score"] < params.min_quality_score:
        return True, "품질점수부족"

    # 70-79점 스킵
    if params.skip_score_70_79 and 70 <= features["quality_score"] < 80:
        return True, "70-79점스킵"

    # 추가 조건들
    if params.min_morning_change is not None:
        if features["morning_change"] < params.min_morning_change:
            return True, f"오전등락률부족(<{params.min_morning_change}%)"

    if params.min_close_strength is not None:
        if features["close_strength"] < params.min_close_strength:
            return True, f"종가강도부족(<{params.min_close_strength})"

    if params.max_afternoon_drop is not None:
        if features["afternoon_change"] < params.max_afternoon_drop:
            return True, f"오후낙폭초과(<{params.max_afternoon_drop}%)"

    if params.min_volume_ratio is not None:
        if features["volume_ratio"] < params.min_volume_ratio:
            return True, f"거래량비율부족(<{params.min_volume_ratio})"

    if params.min_momentum is not None:
        if features["momentum"] < params.min_momentum:
            return True, f"모멘텀부족(<{params.min_momentum})"

    if params.max_leader_rank is not None:
        if features["leader_rank"] > params.max_leader_rank:
            return True, f"순위초과(>{params.max_leader_rank})"

    if params.min_prev_day_change is not None:
        if features["prev_day_change"] < params.min_prev_day_change:
            return True, f"전일등락률부족"

    if params.max_gap_up is not None:
        if features["gap_pct"] > params.max_gap_up:
            return True, f"갭상승과다"

    if params.min_intraday_range is not None:
        if features["intraday_range"] < params.min_intraday_range:
            return True, f"변동폭부족"

    if params.max_high_tail is not None:
        if features["high_tail_pct"] > params.max_high_tail:
            return True, f"윗꼬리과다"

    if params.min_body_ratio is not None:
        if features["body_ratio"] < params.min_body_ratio:
            return True, f"몸통비율부족"

    return False, None


def run_simulation(params: StrategyParams, n_days: int = 40) -> tuple:
    """시뮬레이션 실행 - 상세 거래 데이터 반환"""

    COMMISSION = 0.00015
    TAX = 0.0023
    INITIAL_CAPITAL = 10_000_000

    dates_all = get_trading_days(END_DATE, n_days)
    prev_dates = dates_all[:-1]
    trade_dates = dates_all[1:]

    daily_info, all_codes = fetch_daily_data(dates_all)
    bars_all = fetch_5min_bulk(all_codes, trade_dates)

    capital = INITIAL_CAPITAL
    positions = {}
    all_trades: List[TradeData] = []
    skipped_reasons = defaultdict(int)

    for i, date in enumerate(trade_dates):
        prev_date = prev_dates[i]
        info = daily_info[date]
        df = info["df"]
        universe = info["universe"]
        prev_df = daily_info[prev_date]["df"] if prev_date in daily_info else None

        # 필터링
        cap_filtered = set(df[df["시가총액_억"] >= params.min_market_cap].index.tolist())
        eligible = universe & cap_filtered

        if prev_df is not None:
            inst_range = set(prev_df[
                (prev_df["기관순매수"] >= params.min_inst_buy) &
                (prev_df["기관순매수"] <= params.max_inst_buy)
            ].index.tolist())
            eligible = eligible & inst_range

        leaders = select_leaders(bars_all, date, eligible)
        leaders_filtered = leaders[params.skip_top_n:params.skip_top_n + params.enter_top_n]
        leader_codes = [s["code"] for s in leaders_filtered]

        # 오전 거래량 중앙값
        vols = []
        for code in leader_codes:
            if code in bars_all and date in bars_all[code]:
                bars = bars_all[code][date]
                morning = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
                if not morning.empty:
                    vols.append(morning["Volume"].sum())
        vol_median = np.median(vols) if vols else 0

        # 보유 포지션 청산 체크
        codes_to_check = list(positions.keys())
        for code in codes_to_check:
            if code not in bars_all or date not in bars_all[code]:
                continue
            pos = positions[code]
            bars = bars_all[code][date]

            for ts, bar in bars.iterrows():
                lo_pct = (bar["Low"] / pos["entry_price"]) - 1
                hi_pct = (bar["High"] / pos["entry_price"]) - 1

                # 손절
                if lo_pct <= params.sl_pct:
                    exit_price = pos["entry_price"] * (1 + params.sl_pct)
                    sell_qty = pos["quantity"]
                    cost = exit_price * sell_qty * (COMMISSION + TAX)
                    pnl = (exit_price - pos["entry_price"]) * sell_qty - cost
                    pnl_pct = ((exit_price / pos["entry_price"]) - 1) * 100

                    features_without_qs = {k: v for k, v in pos["features"].items() if k != "quality_score"}
                    all_trades.append(TradeData(
                        code=code, name=pos["name"], date=date,
                        method=pos["method"],
                        entry_time=pos["entry_time"],
                        entry_price=pos["entry_price"],
                        exit_price=exit_price,
                        pnl=pnl, pnl_pct=pnl_pct,
                        exit_reason="손절",
                        quality_score=pos["quality_score"],
                        is_win=pnl > 0,
                        **features_without_qs
                    ))
                    capital += exit_price * sell_qty - cost
                    del positions[code]
                    break

                # 익절
                if hi_pct >= params.tp_pct and not pos.get("partial_sold"):
                    exit_price = pos["entry_price"] * (1 + params.tp_pct)
                    sell_qty = int(pos["quantity"] * params.tp_partial)
                    if sell_qty <= 0:
                        sell_qty = pos["quantity"]

                    cost = exit_price * sell_qty * (COMMISSION + TAX)
                    pnl = (exit_price - pos["entry_price"]) * sell_qty - cost
                    pnl_pct = ((exit_price / pos["entry_price"]) - 1) * 100

                    features_without_qs = {k: v for k, v in pos["features"].items() if k != "quality_score"}
                    all_trades.append(TradeData(
                        code=code, name=pos["name"], date=date,
                        method=pos["method"],
                        entry_time=pos["entry_time"],
                        entry_price=pos["entry_price"],
                        exit_price=exit_price,
                        pnl=pnl, pnl_pct=pnl_pct,
                        exit_reason="1차익절",
                        quality_score=pos["quality_score"],
                        is_win=True,
                        **features_without_qs
                    ))
                    capital += exit_price * sell_qty - cost
                    pos["quantity"] -= sell_qty
                    pos["partial_sold"] = True

                    if pos["quantity"] <= 0:
                        del positions[code]
                        break

        # 신규 진입
        entries = []
        for rank_idx, s in enumerate(leaders_filtered):
            code = s["code"]
            rank = params.skip_top_n + rank_idx + 1

            if code in positions:
                continue
            if code not in bars_all or date not in bars_all[code]:
                continue

            # 당일 등락률 필터
            if code in df.index:
                daily_change = df.loc[code, "등락률"]
                if daily_change < params.min_daily_change:
                    continue

            bars = bars_all[code][date]

            # 돌파 신호
            entry = find_breakout(bars)
            if entry:
                features = calc_extended_features(code, bars, df, prev_df, rank, entry["time"])

                # 파라미터 기반 스킵 체크
                skip, reason = should_skip_by_params(features, params)
                if skip:
                    skipped_reasons[reason] += 1
                    continue

                entries.append({
                    "code": code, "entry": entry, "method": "돌파",
                    "momentum": s["momentum"], "features": features
                })

            # 눌림 신호
            entry = find_pullback(bars, vol_median)
            if entry:
                features = calc_extended_features(code, bars, df, prev_df, rank, entry["time"])

                skip, reason = should_skip_by_params(features, params)
                if skip:
                    skipped_reasons[reason] += 1
                    continue

                if not any(e["code"] == code and e["method"] == "돌파" for e in entries):
                    entries.append({
                        "code": code, "entry": entry, "method": "눌림",
                        "momentum": s["momentum"], "features": features
                    })

        # 품질 점수순 정렬
        entries.sort(key=lambda x: x["features"]["quality_score"], reverse=True)

        for e in entries:
            if len(positions) >= params.max_positions:
                break

            code = e["code"]
            entry = e["entry"]
            price = entry["price"]
            conf = entry["confidence"]
            features = e["features"]

            if conf < params.min_confidence:
                continue

            alloc_pct = 0.50 if conf >= 0.7 else 0.30
            invest_amount = capital * alloc_pct
            qty = int(invest_amount / price)
            if qty <= 0 or price * qty < 100_000:
                continue

            buy_cost = price * qty * COMMISSION
            total_cost = price * qty + buy_cost

            if total_cost > capital:
                continue

            name = pykrx_stock.get_market_ticker_name(code) or code
            capital -= total_cost

            positions[code] = {
                "code": code, "name": name, "method": e["method"],
                "entry_price": price, "quantity": qty,
                "entry_time": str(entry["time"])[:16],
                "quality_score": features["quality_score"],
                "features": features,
            }

        # 장마감 청산
        codes_remaining = list(positions.keys())
        for code in codes_remaining:
            if code not in bars_all or date not in bars_all[code]:
                continue
            pos = positions[code]
            bars = bars_all[code][date]
            if bars.empty:
                continue

            last_bar = bars.iloc[-1]
            exit_price = last_bar["Close"]
            sell_qty = pos["quantity"]
            cost = exit_price * sell_qty * (COMMISSION + TAX)
            pnl = (exit_price - pos["entry_price"]) * sell_qty - cost
            pnl_pct = ((exit_price / pos["entry_price"]) - 1) * 100

            features_without_qs = {k: v for k, v in pos["features"].items() if k != "quality_score"}
            all_trades.append(TradeData(
                code=code, name=pos["name"], date=date,
                method=pos["method"],
                entry_time=pos["entry_time"],
                entry_price=pos["entry_price"],
                exit_price=exit_price,
                pnl=pnl, pnl_pct=pnl_pct,
                exit_reason="장마감",
                quality_score=pos["quality_score"],
                is_win=pnl > 0,
                **features_without_qs
            ))
            capital += exit_price * sell_qty - cost
            del positions[code]

    # 결과 요약
    total_pnl = sum(t.pnl for t in all_trades)
    total_return = total_pnl / INITIAL_CAPITAL * 100
    wins = sum(1 for t in all_trades if t.pnl > 0)
    win_rate = wins / len(all_trades) * 100 if all_trades else 0

    summary = {
        "trades": len(all_trades),
        "wins": wins,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "total_return": total_return,
        "skipped": dict(skipped_reasons),
    }

    return all_trades, summary


def analyze_with_openai(trades: List[TradeData], params: StrategyParams, iteration: int) -> dict:
    """OpenAI로 거래 분석"""

    if len(trades) < 5:
        return None

    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]

    # 승리/패배 거래 통계
    def calc_stats(trade_list):
        if not trade_list:
            return {}
        return {
            "count": len(trade_list),
            "avg_pnl": np.mean([t.pnl for t in trade_list]),
            "avg_pnl_pct": np.mean([t.pnl_pct for t in trade_list]),
            "avg_market_cap": np.mean([t.market_cap for t in trade_list]),
            "avg_inst_buy": np.mean([t.inst_buy for t in trade_list]),
            "avg_daily_change": np.mean([t.daily_change for t in trade_list]),
            "avg_morning_change": np.mean([t.morning_change for t in trade_list]),
            "avg_afternoon_change": np.mean([t.afternoon_change for t in trade_list]),
            "avg_close_strength": np.mean([t.close_strength for t in trade_list]),
            "avg_volume_ratio": np.mean([t.volume_ratio for t in trade_list]),
            "avg_momentum": np.mean([t.momentum for t in trade_list]),
            "avg_quality_score": np.mean([t.quality_score for t in trade_list]),
            "avg_gap_pct": np.mean([t.gap_pct for t in trade_list]),
            "avg_intraday_range": np.mean([t.intraday_range for t in trade_list]),
            "avg_high_tail_pct": np.mean([t.high_tail_pct for t in trade_list]),
            "avg_body_ratio": np.mean([t.body_ratio for t in trade_list]),
            "avg_prev_day_change": np.mean([t.prev_day_change for t in trade_list]),
            "leader_rank_dist": dict(pd.Series([t.leader_rank for t in trade_list]).value_counts()),
            "method_dist": dict(pd.Series([t.method for t in trade_list]).value_counts()),
            "exit_reason_dist": dict(pd.Series([t.exit_reason for t in trade_list]).value_counts()),
        }

    win_stats = calc_stats(wins)
    loss_stats = calc_stats(losses)

    # 상세 거래 샘플 (최대 10개씩)
    win_samples = [t.to_dict() for t in wins[:10]]
    loss_samples = [t.to_dict() for t in losses[:10]]

    prompt = f"""
당신은 한국 주식 단기매매 전략 분석가입니다.

## 현재 전략 파라미터 (iteration {iteration})
{json.dumps(params.to_dict(), indent=2, ensure_ascii=False)}

## 거래 결과 요약
- 총 거래: {len(trades)}건
- 승리: {len(wins)}건 ({len(wins)/len(trades)*100:.1f}%)
- 패배: {len(losses)}건

## 승리 거래 통계
{json.dumps(to_python_type(win_stats), indent=2, ensure_ascii=False)}

## 패배 거래 통계
{json.dumps(to_python_type(loss_stats), indent=2, ensure_ascii=False)}

## 승리 거래 샘플
{json.dumps(to_python_type(win_samples), indent=2, ensure_ascii=False)}

## 패배 거래 샘플
{json.dumps(to_python_type(loss_samples), indent=2, ensure_ascii=False)}

## 분석 요청

1. 승리 거래와 패배 거래의 핵심 차이점을 분석하세요.
2. 패배 거래를 줄이기 위한 새로운 조건을 제안하세요.
3. 승리 거래의 공통점을 기반으로 새로운 진입 조건을 제안하세요.

## 중요 제약사항
- 거래 건수가 최소 15건 이상 유지되어야 합니다.
- 점진적인 변경만 제안하세요 (한 번에 1-2개 파라미터만).
- 새로운 조건 추가 시, 해당 조건이 승리 거래에서 공통적으로 나타나는지 확인하세요.

## 응답 형식 (JSON)
{{
    "analysis": "분석 내용 (한국어)",
    "win_patterns": ["승리 거래 패턴 1", "패턴 2", ...],
    "loss_patterns": ["패배 거래 패턴 1", "패턴 2", ...],
    "recommended_changes": {{
        "파라미터명": 값,
        ...
    }},
    "new_conditions": {{
        "min_morning_change": null 또는 숫자,
        "min_close_strength": null 또는 숫자,
        "max_afternoon_drop": null 또는 숫자,
        "min_volume_ratio": null 또는 숫자,
        "min_momentum": null 또는 숫자,
        "max_leader_rank": null 또는 숫자,
        "min_prev_day_change": null 또는 숫자,
        "max_gap_up": null 또는 숫자,
        "min_intraday_range": null 또는 숫자,
        "max_high_tail": null 또는 숫자,
        "min_body_ratio": null 또는 숫자
    }},
    "expected_impact": "예상 효과 설명",
    "confidence": 0.0~1.0
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a Korean stock trading strategy analyst. Always respond in Korean with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"    OpenAI 오류: {e}")
        return None


def apply_recommendations(params: StrategyParams, recommendations: dict) -> StrategyParams:
    """추천사항을 파라미터에 적용"""
    new_params = StrategyParams(**params.to_dict())

    # 기존 파라미터 변경
    if "recommended_changes" in recommendations:
        for key, value in recommendations["recommended_changes"].items():
            if hasattr(new_params, key) and value is not None:
                setattr(new_params, key, value)

    # 새로운 조건 추가
    if "new_conditions" in recommendations:
        for key, value in recommendations["new_conditions"].items():
            if hasattr(new_params, key):
                setattr(new_params, key, value)

    return new_params


def run_advanced_analysis(max_iterations: int = 15):
    """고급 반복 분석 실행"""

    print("=" * 70)
    print("  OpenAI 고급 반복 분석 v2.0")
    print(f"  최대 반복: {max_iterations}회")
    print("  교차 검증: 20일 / 60일")
    print("=" * 70)

    # 초기 파라미터 (v6.2 기준)
    params = StrategyParams()

    history = []
    best_result = {
        "params": params.to_dict(),
        "total_return_20d": 0,
        "total_return_60d": 0,
        "win_rate_20d": 0,
        "win_rate_60d": 0,
        "iteration": 0,
    }

    for iteration in range(1, max_iterations + 1):
        print(f"\n{'='*70}")
        print(f"  Iteration {iteration}/{max_iterations}")
        print(f"{'='*70}")

        # 20일 시뮬레이션
        print(f"\n  [20일 데이터 시뮬레이션]")
        trades_20d, summary_20d = run_simulation(params, n_days=20)
        print(f"    거래: {summary_20d['trades']}건")
        print(f"    승률: {summary_20d['win_rate']:.1f}%")
        print(f"    수익률: {summary_20d['total_return']:.2f}%")

        # 60일 시뮬레이션
        print(f"\n  [60일 데이터 시뮬레이션]")
        trades_60d, summary_60d = run_simulation(params, n_days=60)
        print(f"    거래: {summary_60d['trades']}건")
        print(f"    승률: {summary_60d['win_rate']:.1f}%")
        print(f"    수익률: {summary_60d['total_return']:.2f}%")

        # 거래 건수 체크
        if summary_60d['trades'] < 10:
            print(f"\n  ⚠️ 거래 건수 부족 ({summary_60d['trades']}건)")
            print(f"  이전 최적 파라미터로 롤백...")
            params = StrategyParams(**best_result["params"])
            continue

        # 최적 결과 갱신 체크
        avg_return = (summary_20d['total_return'] + summary_60d['total_return']) / 2
        avg_wr = (summary_20d['win_rate'] + summary_60d['win_rate']) / 2

        best_avg = (best_result['total_return_20d'] + best_result['total_return_60d']) / 2

        if avg_return > best_avg:
            best_result = {
                "params": params.to_dict(),
                "total_return_20d": summary_20d['total_return'],
                "total_return_60d": summary_60d['total_return'],
                "win_rate_20d": summary_20d['win_rate'],
                "win_rate_60d": summary_60d['win_rate'],
                "iteration": iteration,
            }
            print(f"\n  ✅ 새로운 최적 결과!")
            print(f"    평균 수익률: {avg_return:.2f}%")
            print(f"    평균 승률: {avg_wr:.1f}%")

        # OpenAI 분석 (60일 데이터 기반)
        print(f"\n  [OpenAI 분석 중...]")
        recommendations = analyze_with_openai(trades_60d, params, iteration)

        if recommendations is None:
            print(f"    분석 실패, 다음 반복으로...")
            continue

        print(f"\n  [분석 결과]")
        print(f"    분석: {recommendations.get('analysis', 'N/A')[:100]}...")

        if recommendations.get('win_patterns'):
            print(f"\n    승리 패턴:")
            for pattern in recommendations['win_patterns'][:3]:
                print(f"      - {pattern}")

        if recommendations.get('loss_patterns'):
            print(f"\n    패배 패턴:")
            for pattern in recommendations['loss_patterns'][:3]:
                print(f"      - {pattern}")

        if recommendations.get('recommended_changes'):
            print(f"\n    추천 변경:")
            for k, v in recommendations['recommended_changes'].items():
                print(f"      {k}: {v}")

        if recommendations.get('new_conditions'):
            new_conds = {k: v for k, v in recommendations['new_conditions'].items() if v is not None}
            if new_conds:
                print(f"\n    새 조건:")
                for k, v in new_conds.items():
                    print(f"      {k}: {v}")

        # 기록
        history.append({
            "iteration": iteration,
            "params": params.to_dict(),
            "summary_20d": to_python_type(summary_20d),
            "summary_60d": to_python_type(summary_60d),
            "recommendations": recommendations,
        })

        # 파라미터 업데이트
        confidence = recommendations.get('confidence', 0.5)
        if confidence >= 0.5:
            new_params = apply_recommendations(params, recommendations)

            # 검증: 새 파라미터로 20일 시뮬레이션
            print(f"\n  [새 파라미터 검증 중...]")
            _, test_summary = run_simulation(new_params, n_days=20)

            if test_summary['trades'] >= 10 and test_summary['win_rate'] >= summary_20d['win_rate'] * 0.9:
                params = new_params
                print(f"    ✅ 파라미터 적용 (거래: {test_summary['trades']}건, 승률: {test_summary['win_rate']:.1f}%)")
            else:
                print(f"    ❌ 파라미터 롤백 (거래: {test_summary['trades']}건, 승률: {test_summary['win_rate']:.1f}%)")
        else:
            print(f"\n  신뢰도 부족 ({confidence:.2f}), 파라미터 유지")

        time_mod.sleep(1)  # API 제한

    # 최종 결과
    print(f"\n{'='*70}")
    print(f"  최종 결과")
    print(f"{'='*70}")

    print(f"\n  최적 결과 (Iteration {best_result['iteration']}):")
    print(f"    20일 수익률: {best_result['total_return_20d']:.2f}%")
    print(f"    60일 수익률: {best_result['total_return_60d']:.2f}%")
    print(f"    20일 승률: {best_result['win_rate_20d']:.1f}%")
    print(f"    60일 승률: {best_result['win_rate_60d']:.1f}%")

    print(f"\n  최적 파라미터:")
    for k, v in best_result['params'].items():
        if v is not None:
            print(f"    {k}: {v}")

    # 결과 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"scripts/openai_advanced_result_{timestamp}.json"

    result = {
        "history": history,
        "best_result": best_result,
        "final_params": params.to_dict(),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(to_python_type(result), f, indent=2, ensure_ascii=False)

    print(f"\n  결과 저장: {output_path}")

    return result


if __name__ == "__main__":
    run_advanced_analysis(max_iterations=15)
