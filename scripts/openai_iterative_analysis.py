"""
OpenAI 반복 분석 스크립트

5차례 반복하면서:
1. 승리/패배 거래 특성 추출
2. OpenAI로 패턴 분석
3. 새로운 조건 도출 및 적용
4. 시뮬레이션 재실행
5. 결과 비교 및 개선
"""

import warnings
warnings.filterwarnings("ignore")

import os
import json
import time
from datetime import datetime
from dataclasses import dataclass, asdict, field
from collections import defaultdict
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from openai import OpenAI

load_dotenv()

# OpenAI 클라이언트
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

END_DATE = "20260212"

# 기본 파라미터 (v5 기준)
DEFAULT_PARAMS = {
    "sl_pct": -0.04,        # 손절
    "tp_pct": 0.05,         # 익절
    "tp_partial": 0.70,     # 분매 비율
    "max_positions": 3,     # 최대 보유
    "min_confidence": 0.70, # 최소 확신도
    "min_market_cap": 5000, # 시총 (억)
    "min_inst_buy": 50,     # 기관순매수 최소 (억)
    "max_inst_buy": 200,    # 기관순매수 최대 (억)
    "skip_top_n": 1,        # TOP N 스킵
    "enter_top_n": 4,       # TOP N까지 진입
    "min_daily_change": 6.0, # 당일 등락률 최소
    # 추가 가능한 조건들 (아직 미사용)
    "min_volume_ratio": None,    # 오전 거래량 비율
    "min_momentum": None,        # 최소 모멘텀
    "max_leader_rank": None,     # 최대 리더 순위
    "min_morning_change": None,  # 오전 등락률 최소
    "max_afternoon_drop": None,  # 오후 낙폭 최대
    "min_close_strength": None,  # 종가 강도 최소
}

_kosdaq_set = None


def get_kosdaq_set():
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(END_DATE, market="KOSDAQ"))
    return _kosdaq_set


def code_to_ticker(code):
    return f"{code}{'.KQ' if code in get_kosdaq_set() else '.KS'}"


@dataclass
class Trade:
    """거래 데이터 (분석용 확장 필드 포함)"""
    code: str
    name: str
    method: str                 # 돌파/눌림
    date: str
    entry_time: str
    entry_price: float
    exit_time: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""

    # 기본 지표
    market_cap: float = 0.0      # 시가총액 (억)
    inst_buy: float = 0.0        # 기관순매수 (억)
    daily_change: float = 0.0    # 당일 등락률
    leader_rank: int = 0         # 리더 순위
    entry_hour: int = 0          # 진입 시간

    # 추가 분석 지표
    morning_change: float = 0.0  # 오전(~11시) 등락률
    afternoon_change: float = 0.0  # 오후(12~15시) 등락률
    volume_ratio: float = 0.0    # 오전/전일 거래량 비율
    momentum_score: float = 0.0  # 모멘텀 점수
    close_strength: float = 0.0  # 종가 강도 (고가 대비)
    intraday_range: float = 0.0  # 일중 등락폭
    open_gap: float = 0.0        # 시초갭
    volume_rank: int = 0         # 거래대금 순위
    prev_day_change: float = 0.0 # 전일 등락률
    consecutive_up: int = 0      # 연속 상승일


def get_trading_days(end_date, n_days=20):
    from datetime import timedelta
    end = pd.Timestamp(end_date)
    start = end - timedelta(days=60)
    df = pykrx_stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end_date, "005930")
    dates = [d.strftime("%Y%m%d") for d in df.index]
    return dates[-(n_days + 1):]


def fetch_daily_data(dates):
    """일별 데이터 수집 (확장)"""
    print("  일별 데이터 수집 중...")
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

        # 거래대금 순위
        df["거래대금_순위"] = df["거래대금"].rank(ascending=False)

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
        all_codes |= universe
        time.sleep(0.3)

    return daily_info, all_codes


def fetch_5min_bulk(codes, dates):
    """5분봉 수집"""
    print("  5분봉 수집 중...")
    bars_all = {}
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
                    for d in date_set:
                        day = df[df.index.date == d]
                        if len(day) >= 10:
                            bars_all[code][d.strftime("%Y%m%d")] = day
                except Exception:
                    pass
        except Exception:
            pass

    return bars_all


def select_leaders(bars_all, date, eligible_codes):
    """리더 선정"""
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


def find_breakout(bars):
    """돌파매매"""
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
    """눌림매매"""
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


def simulate_trade(bars, entry_price, entry_idx, params):
    """거래 시뮬레이션"""
    sl = params["sl_pct"]
    tp = params["tp_pct"]
    tp_partial = params["tp_partial"]

    for i in range(entry_idx + 1, len(bars)):
        bar = bars.iloc[i]
        lo_pct = (bar["Low"] / entry_price) - 1
        hi_pct = (bar["High"] / entry_price) - 1

        if lo_pct <= sl:
            return sl * 100, "손절", bars.index[i]
        if hi_pct >= tp:
            return tp * 100 * tp_partial, "1차익절", bars.index[i]

    last = bars.iloc[-1]
    pnl = ((last["Close"] / entry_price) - 1) * 100
    return pnl, "장마감", bars.index[-1]


def calc_extended_features(code, bars, df, prev_df, prev_prev_df):
    """확장 지표 계산"""
    features = {}

    # 오전/오후 등락률
    morning = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
    afternoon = bars[(bars.index.hour >= 12) & (bars.index.hour < 16)]

    if not morning.empty:
        features["morning_change"] = (morning.iloc[-1]["Close"] / morning.iloc[0]["Open"] - 1) * 100
    else:
        features["morning_change"] = 0.0

    if not afternoon.empty and not morning.empty:
        features["afternoon_change"] = (afternoon.iloc[-1]["Close"] / morning.iloc[-1]["Close"] - 1) * 100
    else:
        features["afternoon_change"] = 0.0

    # 종가 강도
    day_high = bars["High"].max()
    day_low = bars["Low"].min()
    day_close = bars.iloc[-1]["Close"]
    if day_high > day_low:
        features["close_strength"] = (day_close - day_low) / (day_high - day_low) * 100
    else:
        features["close_strength"] = 50.0

    # 일중 등락폭
    features["intraday_range"] = (day_high / day_low - 1) * 100 if day_low > 0 else 0.0

    # 시초갭
    if prev_df is not None and code in prev_df.index:
        prev_close = prev_df.loc[code, "종가"]
        if prev_close > 0:
            features["open_gap"] = (bars.iloc[0]["Open"] / prev_close - 1) * 100
        else:
            features["open_gap"] = 0.0
    else:
        features["open_gap"] = 0.0

    # 거래대금 순위
    if code in df.index:
        features["volume_rank"] = int(df.loc[code, "거래대금_순위"])
    else:
        features["volume_rank"] = 100

    # 전일 등락률
    if prev_df is not None and code in prev_df.index:
        features["prev_day_change"] = prev_df.loc[code, "등락률"]
    else:
        features["prev_day_change"] = 0.0

    # 연속 상승일 (간단 추정)
    consecutive = 0
    if prev_df is not None and code in prev_df.index:
        if prev_df.loc[code, "등락률"] > 0:
            consecutive = 1
            if prev_prev_df is not None and code in prev_prev_df.index:
                if prev_prev_df.loc[code, "등락률"] > 0:
                    consecutive = 2
    features["consecutive_up"] = consecutive

    return features


def run_backtest_with_params(bars_all, daily_info, dates, prev_dates, params):
    """파라미터 적용 백테스트"""
    all_trades = []

    for i, date in enumerate(dates):
        prev_date = prev_dates[i]
        info = daily_info[date]
        df = info["df"]
        universe = info["universe"]
        prev_df = daily_info[prev_date]["df"] if prev_date in daily_info else None

        # 2일전 데이터 (연속 상승 계산용)
        prev_prev_date = prev_dates[i-1] if i > 0 else None
        prev_prev_df = daily_info[prev_prev_date]["df"] if prev_prev_date and prev_prev_date in daily_info else None

        # 필터 적용
        eligible = universe.copy()

        # 시총 필터
        cap_filtered = set(df[df["시가총액_억"] >= params["min_market_cap"]].index.tolist())
        eligible = eligible & cap_filtered

        # 기관순매수 필터
        if prev_df is not None:
            inst_range = set(prev_df[
                (prev_df["기관순매수"] >= params["min_inst_buy"]) &
                (prev_df["기관순매수"] <= params["max_inst_buy"])
            ].index.tolist())
            eligible = eligible & inst_range

        leaders = select_leaders(bars_all, date, eligible)

        # TOP N 필터
        skip = params["skip_top_n"]
        enter = params["enter_top_n"]
        leaders_filtered = leaders[skip:skip + enter]

        leader_codes = [s["code"] for s in leaders_filtered]
        vol_median = get_morning_vol_median(bars_all, date, leader_codes)

        for rank_idx, s in enumerate(leaders_filtered):
            code = s["code"]
            rank = skip + rank_idx + 1  # 실제 순위

            if code not in bars_all or date not in bars_all[code]:
                continue
            bars = bars_all[code][date]

            # 당일 등락률 필터
            if code in df.index:
                daily_change = df.loc[code, "등락률"]
                if daily_change < params["min_daily_change"]:
                    continue
            else:
                continue

            # 추가 지표 계산
            ext_features = calc_extended_features(code, bars, df, prev_df, prev_prev_df)

            # 추가 필터 (활성화된 경우)
            if params.get("min_morning_change") is not None:
                if ext_features["morning_change"] < params["min_morning_change"]:
                    continue
            if params.get("max_afternoon_drop") is not None:
                if ext_features["afternoon_change"] < -params["max_afternoon_drop"]:
                    continue
            if params.get("min_close_strength") is not None:
                if ext_features["close_strength"] < params["min_close_strength"]:
                    continue
            if params.get("max_leader_rank") is not None:
                if rank > params["max_leader_rank"]:
                    continue

            # 돌파매매
            entry = find_breakout(bars)
            if entry:
                if entry["confidence"] < params["min_confidence"]:
                    continue
                entry_idx = bars.index.get_loc(entry["time"])
                pnl, reason, exit_time = simulate_trade(bars, entry["price"], entry_idx, params)

                trade = Trade(
                    code=code,
                    name=pykrx_stock.get_market_ticker_name(code) or code,
                    method="돌파",
                    date=date,
                    entry_time=str(entry["time"])[:16],
                    entry_price=entry["price"],
                    exit_time=str(exit_time)[:16],
                    exit_price=entry["price"] * (1 + pnl / 100),
                    pnl_pct=pnl,
                    exit_reason=reason,
                    market_cap=df.loc[code, "시가총액_억"] if code in df.index else 0,
                    inst_buy=prev_df.loc[code, "기관순매수"] if prev_df is not None and code in prev_df.index else 0,
                    daily_change=daily_change,
                    leader_rank=rank,
                    entry_hour=entry["time"].hour,
                    **ext_features
                )
                all_trades.append(trade)

            # 눌림매매
            entry = find_pullback(bars, vol_median)
            if entry:
                if entry["confidence"] < params["min_confidence"]:
                    continue
                entry_idx = bars.index.get_loc(entry["time"])
                pnl, reason, exit_time = simulate_trade(bars, entry["price"], entry_idx, params)

                trade = Trade(
                    code=code,
                    name=pykrx_stock.get_market_ticker_name(code) or code,
                    method="눌림",
                    date=date,
                    entry_time=str(entry["time"])[:16],
                    entry_price=entry["price"],
                    exit_time=str(exit_time)[:16],
                    exit_price=entry["price"] * (1 + pnl / 100),
                    pnl_pct=pnl,
                    exit_reason=reason,
                    market_cap=df.loc[code, "시가총액_억"] if code in df.index else 0,
                    inst_buy=prev_df.loc[code, "기관순매수"] if prev_df is not None and code in prev_df.index else 0,
                    daily_change=daily_change,
                    leader_rank=rank,
                    entry_hour=entry["time"].hour,
                    **ext_features
                )
                all_trades.append(trade)

    return all_trades


def to_python_float(val):
    """numpy float를 Python float로 변환"""
    if pd.isna(val):
        return 0.0
    return float(val)


def analyze_trades_summary(trades: List[Trade]) -> Dict[str, Any]:
    """거래 요약 분석"""
    if not trades:
        return {"error": "No trades"}

    df = pd.DataFrame([asdict(t) for t in trades])
    df["is_win"] = df["pnl_pct"] > 0

    wins = df[df["is_win"]]
    losses = df[~df["is_win"]]

    summary = {
        "total_trades": int(len(df)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": to_python_float(len(wins) / len(df) * 100) if len(df) > 0 else 0.0,
        "total_pnl": to_python_float(df["pnl_pct"].sum()),
        "avg_pnl": to_python_float(df["pnl_pct"].mean()),
        "avg_win": to_python_float(wins["pnl_pct"].mean()) if len(wins) > 0 else 0.0,
        "avg_loss": to_python_float(losses["pnl_pct"].mean()) if len(losses) > 0 else 0.0,
    }

    # 승리 거래 특성
    win_features = {}
    loss_features = {}

    for col in ["market_cap", "inst_buy", "daily_change", "leader_rank",
                "morning_change", "afternoon_change", "close_strength",
                "intraday_range", "open_gap", "volume_rank", "prev_day_change"]:
        if col in df.columns:
            win_features[col] = {
                "mean": to_python_float(wins[col].mean()) if len(wins) > 0 else 0.0,
                "median": to_python_float(wins[col].median()) if len(wins) > 0 else 0.0,
                "min": to_python_float(wins[col].min()) if len(wins) > 0 else 0.0,
                "max": to_python_float(wins[col].max()) if len(wins) > 0 else 0.0,
            }
            loss_features[col] = {
                "mean": to_python_float(losses[col].mean()) if len(losses) > 0 else 0.0,
                "median": to_python_float(losses[col].median()) if len(losses) > 0 else 0.0,
                "min": to_python_float(losses[col].min()) if len(losses) > 0 else 0.0,
                "max": to_python_float(losses[col].max()) if len(losses) > 0 else 0.0,
            }

    summary["win_features"] = win_features
    summary["loss_features"] = loss_features

    # 세그먼트별 성과
    segments = {}

    # 리더 순위별
    for rank in range(1, 11):
        subset = df[df["leader_rank"] == rank]
        if len(subset) > 0:
            segments[f"rank_{rank}"] = {
                "trades": int(len(subset)),
                "win_rate": to_python_float((subset["pnl_pct"] > 0).mean() * 100),
                "total_pnl": to_python_float(subset["pnl_pct"].sum()),
            }

    # 당일 등락률별
    for label, chg_min, chg_max in [("chg_0_6", 0, 6), ("chg_6_10", 6, 10),
                                     ("chg_10_15", 10, 15), ("chg_15_plus", 15, 100)]:
        subset = df[(df["daily_change"] >= chg_min) & (df["daily_change"] < chg_max)]
        if len(subset) > 0:
            segments[label] = {
                "trades": int(len(subset)),
                "win_rate": to_python_float((subset["pnl_pct"] > 0).mean() * 100),
                "total_pnl": to_python_float(subset["pnl_pct"].sum()),
            }

    # 종가 강도별
    for label, strength_min, strength_max in [("close_weak", 0, 40), ("close_mid", 40, 70),
                                               ("close_strong", 70, 100)]:
        subset = df[(df["close_strength"] >= strength_min) & (df["close_strength"] < strength_max)]
        if len(subset) > 0:
            segments[label] = {
                "trades": int(len(subset)),
                "win_rate": to_python_float((subset["pnl_pct"] > 0).mean() * 100),
                "total_pnl": to_python_float(subset["pnl_pct"].sum()),
            }

    summary["segments"] = segments

    # TOP 5 승리/패배 거래
    def convert_record(rec):
        """레코드의 값을 Python 네이티브 타입으로 변환"""
        return {k: (float(v) if isinstance(v, (np.floating, np.integer)) else v)
                for k, v in rec.items()}

    cols = ["name", "date", "pnl_pct", "market_cap", "inst_buy", "daily_change",
            "leader_rank", "morning_change", "close_strength"]
    top5_wins = [convert_record(r) for r in wins.nlargest(5, "pnl_pct")[cols].to_dict("records")]
    top5_losses = [convert_record(r) for r in losses.nsmallest(5, "pnl_pct")[cols].to_dict("records")]
    summary["top5_wins"] = top5_wins
    summary["top5_losses"] = top5_losses

    return summary


def call_openai_analysis(summary: Dict, current_params: Dict, iteration: int) -> Dict:
    """OpenAI API 호출하여 분석 및 새로운 조건 제안받기"""

    system_prompt = """당신은 주식 데이트레이딩 전략 최적화 전문가입니다.

주어진 백테스트 결과를 분석하고, 수익률을 개선할 수 있는 새로운 조건을 제안해주세요.

## 중요 제약 조건
1. **최소 거래 건수 유지**: 반드시 15건 이상의 거래가 유지되도록 조건을 설정하세요
2. **점진적 변경**: 한 번에 1-2개 파라미터만 변경하세요 (급격한 변경 금지)
3. **균형 최적화**: 승률뿐만 아니라 총 수익률과 거래 건수의 균형을 맞추세요
4. **현실적 목표**: 승률 60-70%, 거래 20-30건, 총 수익률 10%+ 목표

## 현재 사용 가능한 파라미터
- min_market_cap: 최소 시가총액 (억원) - 범위: 3000~30000
- min_inst_buy: 최소 기관순매수 (억원) - 범위: 30~100
- max_inst_buy: 최대 기관순매수 (억원) - 범위: 100~300
- skip_top_n: 스킵할 상위 N개 - 범위: 0~2
- enter_top_n: 진입할 종목 수 - 범위: 3~6
- min_daily_change: 최소 당일 등락률 (%) - 범위: 3~10
- min_confidence: 최소 확신도 - 범위: 0.5~0.8
- sl_pct: 손절 비율 - 범위: -0.03~-0.05
- tp_pct: 익절 비율 - 범위: 0.03~0.08

## 추가 가능한 새로운 조건 (None이면 미적용)
- min_morning_change: 최소 오전 등락률 (%) - 범위: 3~10
- max_afternoon_drop: 최대 오후 낙폭 (%) - 범위: -5~0
- min_close_strength: 최소 종가 강도 (0~100) - 범위: 50~80
- max_leader_rank: 최대 리더 순위 - 범위: 3~7

## 응답 형식 (JSON)
{
    "analysis": "승리/패배 거래의 주요 차이점 분석",
    "key_insights": ["인사이트1", "인사이트2", ...],
    "recommended_changes": {
        "파라미터명": 새값 (1-2개만!)
    },
    "new_conditions": {
        "min_morning_change": 값 또는 null,
        "max_afternoon_drop": 값 또는 null,
        "min_close_strength": 값 또는 null,
        "max_leader_rank": 값 또는 null
    },
    "expected_impact": "예상되는 효과",
    "expected_trades": "예상 거래 건수 (최소 15건 이상)",
    "risk_warning": "주의할 점"
}"""

    user_prompt = f"""## 반복 {iteration}/5

### 현재 파라미터
{json.dumps(current_params, indent=2, ensure_ascii=False)}

### 백테스트 결과 요약
- 총 거래: {summary['total_trades']}건
- 승률: {summary['win_rate']:.1f}%
- 총 수익률: {summary['total_pnl']:.2f}%
- 평균 수익: {summary['avg_pnl']:.2f}%
- 승리 평균: {summary['avg_win']:.2f}%
- 패배 평균: {summary['avg_loss']:.2f}%

### 승리 거래 특성 (평균)
{json.dumps({k: round(v['mean'], 2) for k, v in summary['win_features'].items()}, indent=2, ensure_ascii=False)}

### 패배 거래 특성 (평균)
{json.dumps({k: round(v['mean'], 2) for k, v in summary['loss_features'].items()}, indent=2, ensure_ascii=False)}

### 세그먼트별 성과
{json.dumps(summary['segments'], indent=2, ensure_ascii=False)}

### TOP 5 승리 거래
{json.dumps(summary['top5_wins'], indent=2, ensure_ascii=False)}

### TOP 5 패배 거래
{json.dumps(summary['top5_losses'], indent=2, ensure_ascii=False)}

위 데이터를 분석하여:
1. 승리 거래와 패배 거래의 핵심 차이점을 파악하세요
2. 패배 거래를 걸러낼 수 있는 새로운 조건을 제안하세요
3. 승리 거래의 공통점을 강화할 수 있는 조건을 제안하세요
4. 기존 파라미터 수정이 필요하면 함께 제안하세요

JSON 형식으로 응답해주세요."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"  OpenAI API 오류: {e}")
        return None


def apply_recommendations(current_params: Dict, recommendations: Dict) -> Dict:
    """OpenAI 추천을 파라미터에 적용"""
    new_params = current_params.copy()

    # 기존 파라미터 수정
    if "recommended_changes" in recommendations:
        for key, value in recommendations["recommended_changes"].items():
            if key in new_params:
                new_params[key] = value

    # 새로운 조건 추가
    if "new_conditions" in recommendations:
        for key, value in recommendations["new_conditions"].items():
            if key in new_params:
                new_params[key] = value if value is not None else None

    return new_params


def main():
    print("=" * 70)
    print("  OpenAI 반복 분석 (5차례)")
    print("=" * 70)

    # 데이터 수집 (1회만)
    dates_all = get_trading_days(END_DATE, 20)
    prev_dates = dates_all[:-1]
    trade_dates = dates_all[1:]
    print(f"\n  분석 기간: {trade_dates[0]}~{trade_dates[-1]}")

    daily_info, all_codes = fetch_daily_data(dates_all)
    bars_all = fetch_5min_bulk(all_codes, trade_dates)

    # 반복 분석
    current_params = DEFAULT_PARAMS.copy()
    history = []
    best_result = {"total_pnl": 0, "params": current_params.copy(), "iteration": 0}

    for iteration in range(1, 6):
        print(f"\n{'='*70}")
        print(f"  반복 {iteration}/5")
        print("="*70)

        # 백테스트 실행
        print("\n  백테스트 실행 중...")
        trades = run_backtest_with_params(bars_all, daily_info, trade_dates, prev_dates, current_params)

        # 결과 요약
        summary = analyze_trades_summary(trades)

        if "error" in summary or summary.get("total_trades", 0) < 10:
            trade_count = summary.get("total_trades", 0) if "error" not in summary else 0
            print(f"\n  결과: {trade_count}건 (거래 부족)")
            print("  조건이 너무 엄격합니다. 최고 성과 파라미터로 복원합니다.")
            # 최고 성과 파라미터로 복원
            current_params = best_result["params"].copy()
            history.append({
                "iteration": iteration,
                "params": current_params.copy(),
                "summary": {"trades": trade_count, "win_rate": 0, "total_pnl": 0},
                "recommendations": None,
            })
            continue

        # 최고 성과 업데이트
        if summary["total_pnl"] > best_result["total_pnl"] and summary["total_trades"] >= 15:
            best_result = {
                "total_pnl": summary["total_pnl"],
                "params": current_params.copy(),
                "iteration": iteration
            }
            print(f"  ★ 새로운 최고 성과! (+{summary['total_pnl']:.2f}%)")

        print(f"\n  결과: {summary['total_trades']}건, 승률 {summary['win_rate']:.1f}%, "
              f"총 수익률 {summary['total_pnl']:.2f}%")

        # OpenAI 분석
        print("\n  OpenAI 분석 요청 중...")
        recommendations = call_openai_analysis(summary, current_params, iteration)

        if recommendations:
            print(f"\n  [분석 결과]")
            print(f"  {recommendations.get('analysis', 'N/A')}")
            print(f"\n  [핵심 인사이트]")
            for insight in recommendations.get("key_insights", []):
                print(f"    - {insight}")
            print(f"\n  [추천 변경사항]")
            for key, value in recommendations.get("recommended_changes", {}).items():
                print(f"    {key}: {current_params.get(key)} → {value}")
            for key, value in recommendations.get("new_conditions", {}).items():
                if value is not None:
                    print(f"    {key}: {current_params.get(key)} → {value}")
            print(f"\n  [예상 효과] {recommendations.get('expected_impact', 'N/A')}")
            print(f"  [주의사항] {recommendations.get('risk_warning', 'N/A')}")

            # 파라미터 적용
            new_params = apply_recommendations(current_params, recommendations)

            # 기록 저장
            history.append({
                "iteration": iteration,
                "params": current_params.copy(),
                "summary": {
                    "trades": summary["total_trades"],
                    "win_rate": summary["win_rate"],
                    "total_pnl": summary["total_pnl"],
                },
                "recommendations": recommendations,
            })

            # 성과가 크게 하락하면 최고 성과로 복원
            if summary["total_pnl"] < best_result["total_pnl"] * 0.5 and best_result["iteration"] > 0:
                print(f"\n  경고: 성과 하락! 최고 성과 (반복{best_result['iteration']})로 복원")
                current_params = best_result["params"].copy()
            else:
                current_params = new_params
        else:
            print("  OpenAI 분석 실패, 파라미터 유지")
            history.append({
                "iteration": iteration,
                "params": current_params.copy(),
                "summary": {
                    "trades": summary["total_trades"],
                    "win_rate": summary["win_rate"],
                    "total_pnl": summary["total_pnl"],
                },
                "recommendations": None,
            })

    # 최종 결과
    print(f"\n{'='*70}")
    print("  최종 결과")
    print("="*70)

    print("\n  [반복별 성과]")
    for h in history:
        print(f"    반복 {h['iteration']}: {h['summary']['trades']}건, "
              f"승률 {h['summary']['win_rate']:.1f}%, "
              f"수익률 {h['summary']['total_pnl']:.2f}%")

    print(f"\n  [최고 성과: 반복 {best_result['iteration']}, +{best_result['total_pnl']:.2f}%]")
    print("\n  [최고 성과 파라미터]")
    for key, value in best_result["params"].items():
        if value is not None:
            print(f"    {key}: {value}")

    # 결과 저장
    output_file = f"/Users/keullaeseuting/Desktop/gylee/stock/scripts/openai_analysis_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "history": history,
            "best_result": best_result,
            "final_params": best_result["params"],
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  결과 저장: {output_file}")

    # 최고 성과 파라미터 반환
    return best_result["params"]


if __name__ == "__main__":
    main()
