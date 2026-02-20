#!/usr/bin/env python3
"""Opening Gap Reversal Strategy v2 - 확신 점수(Conviction Score) 기반.

핵심 아이디어: "아무 갭다운 종목" → "강한 종목이 갭다운" = 매수 기회

확신 시그널 (각 0 or 1, 총 6점):
  1. prev_bullish:      전일 양봉 (close > open)
  2. prev_vol_surge:    전일 거래량 급증 (vs 20일 평균 2x+)
  3. prev_uptrend:      전일 종가 > 5일 이동평균
  4. prev_strong_close:  전일 윗꼬리 짧음 ((close-low)/(high-low) > 0.7)
  5. hong_strong_pos:   Hong 일봉자리 = 신고가/전고점돌파
  6. ki_high:           끼점수 >= 30

conviction_score = sum(1~6), 높을수록 "오를 확신이 있는 종목"

실행:
  source .venv/bin/activate
  python scripts/backtest_gap_strategy.py          # 그리드 서치
  python scripts/backtest_gap_strategy.py best      # 최적 파라미터 상세 결과
  python scripts/backtest_gap_strategy.py analyze    # 확신 점수별 분포 분석
"""

import sys
import time as time_module
import warnings
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from itertools import product
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


# ══════════════════════════════════════════════════════
#  상수
# ══════════════════════════════════════════════════════
INITIAL_CAPITAL = 5_000_000
COMMISSION = 0.00015   # 매수/매도 각 0.015%
TAX = 0.0023           # 매도세 0.23%
COST_PCT = (COMMISSION * 2 + TAX) * 100  # ~0.26%
POSITION_SIZE = 0.30   # 포지션당 30%
MAX_POSITIONS_PER_DAY = 3


# ══════════════════════════════════════════════════════
#  데이터 로딩
# ══════════════════════════════════════════════════════
def load_data():
    """DB에서 5분봉 + 일봉 + Hong 컨텍스트 로드."""
    engine = get_engine()

    with engine.connect() as conn:
        codes = [r[0] for r in conn.execute(text(
            "SELECT code FROM ohlcv_intraday GROUP BY code HAVING COUNT(*) >= 100"
        )).fetchall()]

    print(f"  종목 수: {len(codes)}")

    # 5분봉
    intraday_data = {}
    with engine.connect() as conn:
        for code in tqdm(codes, desc="  5분봉 로딩", leave=False):
            rows = conn.execute(text(
                "SELECT datetime, open, high, low, close, volume "
                "FROM ohlcv_intraday WHERE code = :code ORDER BY datetime"
            ), {"code": code}).fetchall()
            if rows:
                df = pd.DataFrame(
                    rows, columns=["datetime", "open", "high", "low", "close", "volume"]
                )
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
                df = df.astype({c: float for c in ["open", "high", "low", "close", "volume"]})
                intraday_data[code] = df

    all_dates = sorted(set(d for df in intraday_data.values() for d in df.index.date))

    # ── 일봉 (OHLCV 전체 로드) ──
    daily_start = min(all_dates) - timedelta(days=120) if all_dates else date.today() - timedelta(days=180)
    daily_rows = {}  # {code: [{"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v}]}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT code, date, open, high, low, close, volume
            FROM ohlcv_daily WHERE date >= :start ORDER BY code, date
        """), {"start": daily_start}).fetchall()

    for row in rows:
        code, d, o, h, l, c, v = row
        if isinstance(d, datetime):
            d = d.date()
        if code not in daily_rows:
            daily_rows[code] = []
        daily_rows[code].append({
            "date": d,
            "open": float(o or 0), "high": float(h or 0),
            "low": float(l or 0), "close": float(c or 0),
            "volume": float(v or 0),
        })

    # ── 전일 정보 + 확신 시그널 계산 ──
    prev_day_info = {}  # {code: {current_date: {...}}}

    for code, records in daily_rows.items():
        records.sort(key=lambda x: x["date"])
        prev_day_info[code] = {}

        closes = [r["close"] for r in records]
        volumes = [r["volume"] for r in records]

        for i in range(1, len(records)):
            current_date = records[i]["date"]
            prev = records[i - 1]
            prev_close = prev["close"]

            if prev_close <= 0:
                continue

            # 5일 이동평균 (전일 기준)
            start_ma = max(0, i - 5)
            ma5 = np.mean(closes[start_ma:i]) if i > 0 else prev_close

            # 20일 평균 거래량 (전일 기준)
            start_vol = max(0, i - 20)
            avg_vol_20 = np.mean(volumes[start_vol:i]) if i > 0 else prev["volume"]

            # 확신 시그널들
            prev_bullish = prev_close > prev["open"]

            prev_vol_surge_ratio = prev["volume"] / avg_vol_20 if avg_vol_20 > 0 else 0
            prev_vol_surge = prev_vol_surge_ratio >= 2.0

            prev_uptrend = prev_close > ma5

            range_hl = prev["high"] - prev["low"]
            prev_strong_close = (
                (prev_close - prev["low"]) / range_hl > 0.7
            ) if range_hl > 0 else False

            # 연속 상승일수
            consec_up = 0
            for j in range(i - 1, max(0, i - 6), -1):
                if records[j]["close"] > records[j]["open"]:
                    consec_up += 1
                else:
                    break

            prev_day_info[code][current_date] = {
                "close": prev_close,
                "avg_vol": avg_vol_20,
                # 확신 시그널
                "prev_bullish": prev_bullish,
                "prev_vol_surge": prev_vol_surge,
                "prev_vol_surge_ratio": prev_vol_surge_ratio,
                "prev_uptrend": prev_uptrend,
                "prev_strong_close": prev_strong_close,
                "consec_up": consec_up,
                # 전일 등락률
                "prev_change_pct": (prev_close / records[i - 1]["open"] - 1) * 100
                    if records[i - 1]["open"] > 0 else 0,
            }

    # ── Hong 필터용 daily_context ──
    from src.strategies.data_driven.daily_context import DailyContextLoader
    loader = DailyContextLoader()
    daily_context = loader.load(list(intraday_data.keys()), min(all_dates), max(all_dates))

    return intraday_data, prev_day_info, daily_context, all_dates


# ══════════════════════════════════════════════════════
#  갭 셋업 사전 계산 (확신 점수 포함)
# ══════════════════════════════════════════════════════
def precompute_gap_setups(intraday_data, prev_day_info, daily_context, all_dates):
    """모든 종목/날짜에 대해 갭 트레이드 셋업을 사전 계산 (확신 점수 포함)."""
    setups = []

    for current_date in tqdm(all_dates, desc="  갭 셋업 계산", leave=False):
        for code, df in intraday_data.items():
            day_df = df[df.index.date == current_date]
            if len(day_df) < 3:
                continue

            # 전일 정보
            prev_info = prev_day_info.get(code, {}).get(current_date)
            if not prev_info or prev_info["close"] <= 0:
                continue

            prev_close = prev_info["close"]

            # 갭 계산
            first_open = float(day_df.iloc[0]["open"])
            gap_pct = (first_open - prev_close) / prev_close

            # 빠른 필터: 갭이 0이상이면 스킵 (갭다운만)
            if gap_pct >= 0:
                continue

            # 첫 봉 분석
            first_close = float(day_df.iloc[0]["close"])
            first_bar_bullish = first_close > first_open

            # 거래량 배수 (전일 20일 평균 일간 거래량 → 봉당 환산)
            first_vol = float(day_df.iloc[0]["volume"])
            avg_daily_vol = prev_info["avg_vol"]
            avg_bar_vol = avg_daily_vol / 78.0 if avg_daily_vol > 0 else 0
            vol_ratio = first_vol / avg_bar_vol if avg_bar_vol > 0 else 0.0

            # 바 데이터
            bars = []
            for i in range(len(day_df)):
                row = day_df.iloc[i]
                ts = day_df.index[i]
                bars.append({
                    "time": ts.time() if hasattr(ts, 'time') else ts,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                })

            # VWAP 계산 (bar 1, bar 2)
            vwap_at = {}
            for b in [1, 2]:
                if b < len(bars):
                    slice_bars = bars[:b + 1]
                    tp_sum = sum(
                        (br["high"] + br["low"] + br["close"]) / 3 * br["volume"]
                        for br in slice_bars
                    )
                    vol_sum = sum(br["volume"] for br in slice_bars)
                    vwap_at[b] = tp_sum / vol_sum if vol_sum > 0 else 0

            # ── Hong 컨텍스트 ──
            ctx = daily_context.get(code, {}).get(current_date)
            hong_passes = True  # 기본 Hong 필터
            hong_strong_pos = False
            ki_high = False

            if ctx:
                # 기본 Hong 필터
                if ctx.market_cap_bil < 5000:
                    hong_passes = False
                elif ctx.inst_net_buy_bil is not None and not (50 <= ctx.inst_net_buy_bil <= 200):
                    hong_passes = False
                elif ctx.ki_score < 20:
                    hong_passes = False
                elif ctx.daily_position_type not in {"신고가", "전고점돌파", "빈집"}:
                    hong_passes = False
                elif ctx.daily_trading_value < 5_000_000_000:
                    hong_passes = False

                # 확신 시그널: 강한 일봉자리
                hong_strong_pos = ctx.daily_position_type in ("신고가", "전고점돌파")
                # 확신 시그널: 끼점수 높음
                ki_high = ctx.ki_score >= 30

            # ── 확신 점수 계산 ──
            conviction = 0
            conviction += int(prev_info.get("prev_bullish", False))
            conviction += int(prev_info.get("prev_vol_surge", False))
            conviction += int(prev_info.get("prev_uptrend", False))
            conviction += int(prev_info.get("prev_strong_close", False))
            conviction += int(hong_strong_pos)
            conviction += int(ki_high)

            # 누적 거래대금 (bar 1 기준)
            cum_value_bar1 = sum(
                br["close"] * br["volume"] for br in bars[:2]
            ) if len(bars) >= 2 else 0

            setups.append({
                "code": code,
                "date": current_date,
                "gap_pct": gap_pct,
                "first_bar_bullish": first_bar_bullish,
                "vol_ratio": vol_ratio,
                "bars": bars,
                "vwap_at": vwap_at,
                "hong_passes": hong_passes,
                "cum_value_bar1": cum_value_bar1,
                # 확신 시그널 (개별)
                "prev_bullish": prev_info.get("prev_bullish", False),
                "prev_vol_surge": prev_info.get("prev_vol_surge", False),
                "prev_vol_surge_ratio": prev_info.get("prev_vol_surge_ratio", 0),
                "prev_uptrend": prev_info.get("prev_uptrend", False),
                "prev_strong_close": prev_info.get("prev_strong_close", False),
                "hong_strong_pos": hong_strong_pos,
                "ki_high": ki_high,
                "consec_up": prev_info.get("consec_up", 0),
                # 확신 점수 합산
                "conviction": conviction,
            })

    return setups


# ══════════════════════════════════════════════════════
#  트레이드 시뮬레이션
# ══════════════════════════════════════════════════════
def simulate_trade(setup, entry_bar, sl_pct, tp_pct, exit_time, require_vwap=False):
    """단일 트레이드 시뮬레이션."""
    bars = setup["bars"]
    if entry_bar >= len(bars):
        return None

    entry_price = bars[entry_bar]["close"]
    if entry_price <= 0:
        return None

    # VWAP 체크 (옵션)
    if require_vwap:
        vwap = setup["vwap_at"].get(entry_bar, 0)
        if entry_price < vwap:
            return None

    sl_price = entry_price * (1 - sl_pct)
    tp_price = entry_price * (1 + tp_pct)

    # bar entry_bar+1부터 청산 조건 체크
    for i in range(entry_bar + 1, len(bars)):
        bar = bars[i]
        bar_time = bar["time"]

        # 시간 청산
        if bar_time >= exit_time:
            return _make_result(entry_price, bar["close"], "시간청산", setup)

        # SL (low 터치)
        if bar["low"] <= sl_price:
            return _make_result(entry_price, sl_price, "손절", setup)

        # TP (high 터치)
        if bar["high"] >= tp_price:
            return _make_result(entry_price, tp_price, "익절", setup)

    # 장마감
    if bars:
        return _make_result(entry_price, bars[-1]["close"], "장마감", setup)

    return None


def _make_result(entry_price, exit_price, reason, setup):
    """트레이드 결과 생성."""
    pnl_pct = (exit_price / entry_price - 1) * 100
    net_pnl_pct = pnl_pct - COST_PCT
    return {
        "code": setup["code"],
        "date": setup["date"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gap_pct": setup["gap_pct"],
        "vol_ratio": setup["vol_ratio"],
        "conviction": setup["conviction"],
        "pnl_pct": pnl_pct,
        "net_pnl_pct": net_pnl_pct,
        "reason": reason,
        "win": net_pnl_pct > 0,
    }


# ══════════════════════════════════════════════════════
#  그리드 서치 (확신 점수 포함)
# ══════════════════════════════════════════════════════
def run_with_params(setups, gap_min, gap_max, vol_min, vol_max, sl, tp,
                    exit_time, hong_filter, conviction_min=0,
                    require_hong_strong=False, require_vwap=False):
    """주어진 파라미터로 전략 실행."""
    by_date = defaultdict(list)
    for setup in setups:
        if setup["gap_pct"] < gap_min or setup["gap_pct"] > gap_max:
            continue
        if not setup["first_bar_bullish"]:
            continue
        if setup["vol_ratio"] < vol_min or (vol_max > 0 and setup["vol_ratio"] > vol_max):
            continue
        if hong_filter and not setup["hong_passes"]:
            continue
        if require_hong_strong and not setup["hong_strong_pos"]:
            continue
        if setup["conviction"] < conviction_min:
            continue
        by_date[setup["date"]].append(setup)

    trades = []
    for dt in sorted(by_date.keys()):
        day_setups = by_date[dt]
        # 확신 점수 높은 순 → 갭 큰 순으로 우선순위
        day_setups.sort(key=lambda s: (-s["conviction"], -abs(s["gap_pct"])))

        day_trades = 0
        for setup in day_setups:
            if day_trades >= MAX_POSITIONS_PER_DAY:
                break

            for entry_bar in [1, 2]:
                trade = simulate_trade(setup, entry_bar, sl, tp, exit_time, require_vwap)
                if trade:
                    trades.append(trade)
                    day_trades += 1
                    break

    return trades


def calc_metrics(trades):
    """트레이드 목록에서 메트릭 계산."""
    if not trades:
        return {
            "n_trades": 0, "win_rate": 0, "total_return": 0,
            "avg_pnl": 0, "by_reason": {},
        }

    n = len(trades)
    wins = sum(1 for t in trades if t["win"])
    wr = wins / n * 100

    # 자본금 기반 순차 수익률 계산
    capital = INITIAL_CAPITAL
    for t in sorted(trades, key=lambda x: x["date"]):
        invest = capital * POSITION_SIZE
        pnl = invest * (t["net_pnl_pct"] / 100)
        capital += pnl

    total_return = (capital / INITIAL_CAPITAL - 1) * 100
    avg_pnl = np.mean([t["net_pnl_pct"] for t in trades])

    by_reason = defaultdict(int)
    for t in trades:
        by_reason[t["reason"]] += 1

    return {
        "n_trades": n,
        "win_rate": wr,
        "total_return": total_return,
        "avg_pnl": avg_pnl,
        "by_reason": dict(by_reason),
    }


def grid_search(setups, all_dates, hong_filter=True):
    """파라미터 조합 그리드 서치 (확신 점수 포함)."""
    # IS/OOS 분할 (75%/25%)
    split_idx = int(len(all_dates) * 0.75)
    is_dates = set(all_dates[:split_idx])
    oos_dates = set(all_dates[split_idx:])

    is_setups = [s for s in setups if s["date"] in is_dates]
    oos_setups = [s for s in setups if s["date"] in oos_dates]

    print(f"  IS 기간: {min(is_dates)} ~ {max(is_dates)} ({len(is_dates)}일)")
    print(f"  OOS 기간: {min(oos_dates)} ~ {max(oos_dates)} ({len(oos_dates)}일)")
    print(f"  IS 셋업: {len(is_setups)}건, OOS 셋업: {len(oos_setups)}건")

    # ── 그리드 파라미터 ──
    gap_mins = [-0.05, -0.03, -0.02]
    gap_maxs = [-0.003, -0.005, -0.01]
    vol_mins = [1.0]
    vol_maxs = [0]            # 0 = 상한없음
    sls = [0.015, 0.02, 0.025, 0.03]
    tps = [0.02, 0.03, 0.04, 0.05]
    exit_times = [time(10, 0), time(10, 30), time(11, 0), time(11, 30)]
    conviction_mins = [0, 1, 2, 3, 4]   # ★ 핵심 파라미터
    hong_strong_modes = [False, True]    # ★ Hong 신고가/전고점 필수 여부

    results = []
    combos = list(product(
        gap_mins, gap_maxs, vol_mins, vol_maxs,
        sls, tps, exit_times, conviction_mins, hong_strong_modes,
    ))

    for gmin, gmax, vmin, vmax, sl, tp, et, conv_min, hs_mode in tqdm(combos, desc="  그리드 서치"):
        if gmin >= gmax:
            continue

        is_trades = run_with_params(
            is_setups, gmin, gmax, vmin, vmax, sl, tp, et,
            hong_filter, conviction_min=conv_min,
            require_hong_strong=hs_mode,
        )
        oos_trades = run_with_params(
            oos_setups, gmin, gmax, vmin, vmax, sl, tp, et,
            hong_filter, conviction_min=conv_min,
            require_hong_strong=hs_mode,
        )

        is_m = calc_metrics(is_trades)
        oos_m = calc_metrics(oos_trades)

        results.append({
            "gap_min": gmin, "gap_max": gmax,
            "vol_min": vmin, "vol_max": vmax,
            "sl": sl, "tp": tp, "exit_time": et,
            "conviction_min": conv_min,
            "hong_strong": hs_mode,
            "is": is_m, "oos": oos_m,
        })

    return results, is_dates, oos_dates


# ══════════════════════════════════════════════════════
#  결과 출력
# ══════════════════════════════════════════════════════
def print_grid_results(results, hong_label):
    """그리드 서치 결과 출력."""
    # IS 승률 기준 정렬
    results.sort(key=lambda r: r["is"]["win_rate"], reverse=True)

    # 최소 거래수 5 이상만
    filtered = [r for r in results if r["is"]["n_trades"] >= 5]

    print(f"\n{'━' * 110}")
    print(f"  그리드 서치 결과 (Hong: {hong_label}) - IS 승률 기준 TOP 20")
    print(f"{'━' * 110}")
    print(f"  {'#':>3} {'Gap범위':>12} {'SL':>5} {'TP':>5} {'Exit':>6} {'Conv':>4} {'HS':>3}"
          f" | {'IS거래':>5} {'IS승률':>7} {'IS수익':>8} {'IS평균':>7}"
          f" | {'OOS거래':>6} {'OOS승률':>7} {'OOS수익':>8}")
    print(f"  {'─' * 110}")

    for i, r in enumerate(filtered[:20]):
        et_str = f"{r['exit_time'].hour}:{r['exit_time'].minute:02d}"
        gap_str = f"{r['gap_min']*100:.0f}~{r['gap_max']*100:.1f}%"
        hs_str = "Y" if r.get("hong_strong", False) else "N"
        print(
            f"  {i+1:3d} {gap_str:>12} "
            f"{r['sl']*100:>4.1f}% {r['tp']*100:>4.1f}% {et_str:>6} {r['conviction_min']:>4d} "
            f"{hs_str:>3}"
            f" | {r['is']['n_trades']:>5d} {r['is']['win_rate']:>6.1f}% "
            f"{r['is']['total_return']:>+7.2f}% {r['is']['avg_pnl']:>+6.2f}%"
            f" | {r['oos']['n_trades']:>5d} {r['oos']['win_rate']:>7.1f}% "
            f"{r['oos']['total_return']:>+7.2f}%"
        )

    # ── IS 수익률 기준 TOP 10 ──
    by_return = sorted(filtered, key=lambda r: r["is"]["total_return"], reverse=True)
    print(f"\n{'━' * 110}")
    print(f"  IS 수익률 기준 TOP 10")
    print(f"{'━' * 110}")
    for i, r in enumerate(by_return[:10]):
        et_str = f"{r['exit_time'].hour}:{r['exit_time'].minute:02d}"
        gap_str = f"{r['gap_min']*100:.0f}~{r['gap_max']*100:.1f}%"
        hs_str = "HS" if r.get("hong_strong", False) else ""
        oos_drop = ""
        if r["is"]["win_rate"] > 0 and r["oos"]["n_trades"] >= 3:
            drop = (r["is"]["win_rate"] - r["oos"]["win_rate"]) / r["is"]["win_rate"] * 100
            oos_drop = f"(WR{drop:+.0f}%)"
        print(
            f"  {i+1:3d} {gap_str:>12} SL{r['sl']*100:.1f}% TP{r['tp']*100:.1f}% "
            f"@{et_str} Conv>={r['conviction_min']} {hs_str}"
            f" | IS: {r['is']['n_trades']}건 WR={r['is']['win_rate']:.1f}% "
            f"Ret={r['is']['total_return']:+.2f}%"
            f" | OOS: {r['oos']['n_trades']}건 WR={r['oos']['win_rate']:.1f}% "
            f"Ret={r['oos']['total_return']:+.2f}% {oos_drop}"
        )

    # ── OOS 안정성 확인 ──
    stable = [
        r for r in filtered
        if r["is"]["win_rate"] >= 55
        and r["oos"]["n_trades"] >= 3
        and r["oos"]["win_rate"] >= r["is"]["win_rate"] * 0.7
        and r["oos"]["total_return"] > -5  # OOS 수익률 -5% 이상
    ]
    stable.sort(key=lambda r: r["is"]["total_return"], reverse=True)

    print(f"\n{'━' * 110}")
    print(f"  OOS 안정 조합 (IS WR>=55%, OOS WR>=IS*0.7, OOS Ret>-5%) - {len(stable)}건")
    print(f"{'━' * 110}")
    for i, r in enumerate(stable[:15]):
        et_str = f"{r['exit_time'].hour}:{r['exit_time'].minute:02d}"
        hs_str = "HS" if r.get("hong_strong", False) else ""
        print(
            f"  {i+1:3d} gap=[{r['gap_min']*100:.0f}%,{r['gap_max']*100:.1f}%] "
            f"SL{r['sl']*100:.1f}% TP{r['tp']*100:.1f}% @{et_str} "
            f"Conv>={r['conviction_min']} {hs_str}"
            f" | IS: {r['is']['n_trades']}건 WR={r['is']['win_rate']:.1f}% "
            f"Ret={r['is']['total_return']:+.2f}%"
            f" | OOS: {r['oos']['n_trades']}건 WR={r['oos']['win_rate']:.1f}% "
            f"Ret={r['oos']['total_return']:+.2f}%"
        )

    # ── Hong Strong / Conviction 조합별 요약 ──
    print(f"\n{'━' * 110}")
    print(f"  Hong Strong + 확신점수 조합별 성과 요약 (IS 기준, 거래수 5건+)")
    print(f"{'━' * 110}")
    for hs in [False, True]:
        hs_label = "Hong Strong=Y" if hs else "Hong Strong=N"
        hs_results = [r for r in filtered if r.get("hong_strong", False) == hs]
        if not hs_results:
            continue
        print(f"\n  [{hs_label}]")
        for conv in sorted(set(r["conviction_min"] for r in hs_results)):
            conv_results = [r for r in hs_results if r["conviction_min"] == conv]
            if not conv_results:
                continue
            best_wr = max(conv_results, key=lambda r: r["is"]["win_rate"])
            best_ret = max(conv_results, key=lambda r: r["is"]["total_return"])
            avg_wr = np.mean([r["is"]["win_rate"] for r in conv_results])
            avg_trades = np.mean([r["is"]["n_trades"] for r in conv_results])
            print(
                f"    Conv>={conv}: {len(conv_results):3d}개 조합 | "
                f"평균 IS WR={avg_wr:.1f}%, 평균 거래수={avg_trades:.0f}"
                f" | 최고 WR={best_wr['is']['win_rate']:.1f}% "
                f"(Ret={best_wr['is']['total_return']:+.2f}%)"
                f" | 최고 Ret={best_ret['is']['total_return']:+.2f}% "
                f"(WR={best_ret['is']['win_rate']:.1f}%)"
            )

    if stable:
        best = stable[0]
        print(f"\n  >>> 최적 파라미터 <<<")
        print(f"  gap_min={best['gap_min']}, gap_max={best['gap_max']}")
        print(f"  SL={best['sl']}, TP={best['tp']}, "
              f"exit_time={best['exit_time']}, conviction_min={best['conviction_min']}")
        print(f"  hong_strong={best.get('hong_strong', False)}")
        print(f"  IS: {best['is']['n_trades']}건, WR={best['is']['win_rate']:.1f}%, "
              f"Ret={best['is']['total_return']:+.2f}%")
        print(f"  OOS: {best['oos']['n_trades']}건, WR={best['oos']['win_rate']:.1f}%, "
              f"Ret={best['oos']['total_return']:+.2f}%")

    return stable[0] if stable else (filtered[0] if filtered else None)


def print_trade_detail(trades, label):
    """트레이드 상세 출력."""
    if not trades:
        print(f"\n  [{label}] 거래 없음")
        return

    print(f"\n{'━' * 100}")
    print(f"  [{label}] 트레이드 상세 ({len(trades)}건)")
    print(f"{'━' * 100}")
    print(f"  {'날짜':>12} {'종목':>8} {'갭':>7} {'볼비':>5} {'확신':>3} "
          f"{'진입가':>10} {'청산가':>10} {'수익률':>7} {'순수익':>7} {'사유':>8}")
    print(f"  {'─' * 96}")

    for t in sorted(trades, key=lambda x: x["date"]):
        print(
            f"  {str(t['date']):>12} {t['code']:>8} {t['gap_pct']*100:>+6.2f}% "
            f"{t['vol_ratio']:>4.1f}x {t['conviction']:>3d} "
            f"{t['entry_price']:>10,.0f} {t['exit_price']:>10,.0f} "
            f"{t['pnl_pct']:>+6.2f}% {t['net_pnl_pct']:>+6.2f}% {t['reason']:>8}"
        )

    wins = sum(1 for t in trades if t["win"])
    total_pnl = sum(t["net_pnl_pct"] for t in trades)
    avg_pnl = total_pnl / len(trades) if trades else 0
    print(f"\n  승률: {wins}/{len(trades)} = {wins/len(trades)*100:.1f}%")
    print(f"  평균 순수익: {avg_pnl:+.2f}%")
    print(f"  합계 순수익: {total_pnl:+.2f}%")


def run_full_backtest(setups, all_dates, params, hong_filter=True):
    """최적 파라미터로 전체 기간 백테스트 (자본금 추적)."""
    all_trades = run_with_params(
        setups,
        params["gap_min"], params["gap_max"],
        params.get("vol_min", 1.0), params.get("vol_max", 0),
        params["sl"], params["tp"], params["exit_time"],
        hong_filter,
        conviction_min=params.get("conviction_min", 0),
        require_hong_strong=params.get("hong_strong", False),
    )

    if not all_trades:
        print("  거래 없음!")
        return

    # 자본금 추적 시뮬레이션
    capital = float(INITIAL_CAPITAL)
    equity_curve = [capital]
    peak = capital
    max_dd = 0

    by_date_trades = defaultdict(list)
    for t in all_trades:
        by_date_trades[t["date"]].append(t)

    for dt in sorted(by_date_trades.keys()):
        day_trades = by_date_trades[dt]
        for t in day_trades:
            invest = capital * POSITION_SIZE
            pnl = invest * (t["net_pnl_pct"] / 100)
            capital += pnl

        equity_curve.append(capital)
        if capital > peak:
            peak = capital
        dd = (capital - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    total_return = (capital / INITIAL_CAPITAL - 1) * 100
    n_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t["win"])
    wr = wins / n_trades * 100 if n_trades else 0
    avg_pnl = np.mean([t["net_pnl_pct"] for t in all_trades])

    n_days = len(all_dates)
    daily_ret = total_return / n_days if n_days else 0
    monthly = daily_ret * 22

    print(f"\n{'━' * 70}")
    print(f"  전체 기간 백테스트 결과")
    print(f"{'━' * 70}")
    print(f"  기간: {min(all_dates)} ~ {max(all_dates)} ({n_days}일)")
    print(f"  초기자금: {INITIAL_CAPITAL:>14,}원")
    print(f"  최종자금: {capital:>14,.0f}원")
    print(f"  총수익률: {total_return:>+13.2f}%")
    print(f"  거래수:   {n_trades:>14}건")
    print(f"  승률:     {wr:>13.1f}%  ({wins}W / {n_trades - wins}L)")
    print(f"  평균수익: {avg_pnl:>+13.2f}%/건")
    print(f"  MDD:      {max_dd:>13.2f}%")
    print(f"  일평균:   {daily_ret:>+13.3f}%")
    print(f"  월 환산:  {monthly:>+13.2f}%")

    # 청산사유별
    by_reason = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for t in all_trades:
        by_reason[t["reason"]]["count"] += 1
        by_reason[t["reason"]]["pnl"] += t["net_pnl_pct"]

    print(f"\n  [청산사유별]")
    for reason in ["익절", "손절", "시간청산", "장마감"]:
        if reason in by_reason:
            r = by_reason[reason]
            avg = r["pnl"] / r["count"] if r["count"] else 0
            print(f"  {reason:8s}: {r['count']:4d}건 | 합계 {r['pnl']:>+8.2f}% | 평균 {avg:>+6.2f}%")

    # 확신 점수별 승률
    conv_stats = defaultdict(lambda: {"wins": 0, "total": 0})
    for t in all_trades:
        c = t["conviction"]
        conv_stats[c]["total"] += 1
        if t["win"]:
            conv_stats[c]["wins"] += 1

    print(f"\n  [확신점수별 승률]")
    for c in sorted(conv_stats.keys()):
        s = conv_stats[c]
        wr_c = s["wins"] / s["total"] * 100 if s["total"] > 0 else 0
        print(f"    Conv={c}: {s['total']:3d}건, 승률 {wr_c:.1f}% ({s['wins']}W)")

    # 트레이드 상세
    print_trade_detail(all_trades, "전체")

    return all_trades


# ══════════════════════════════════════════════════════
#  확신 점수 분포 분석
# ══════════════════════════════════════════════════════
def analyze_conviction(setups, all_dates):
    """확신 점수별 셋업 분포 및 단순 수익률 분석."""
    gap_down_bullish = [s for s in setups if s["gap_pct"] < 0 and s["first_bar_bullish"]]

    print(f"\n{'━' * 90}")
    print(f"  확신 점수(Conviction) 분포 분석 (갭다운 + 첫봉양봉 셋업)")
    print(f"{'━' * 90}")
    print(f"  전체 셋업: {len(gap_down_bullish)}건")

    # 확신 점수별 분포
    print(f"\n  [확신 점수 분포]")
    for conv in range(7):
        count = sum(1 for s in gap_down_bullish if s["conviction"] == conv)
        pct = count / len(gap_down_bullish) * 100 if gap_down_bullish else 0
        print(f"    Conv={conv}: {count:5d}건 ({pct:.1f}%)")

    # 확신 점수별 수익률 (간단: bar 1 진입 → bar 6 (30분 후) 수익률)
    print(f"\n  [확신 점수별 30분 후 수익률]")
    for conv in range(7):
        conv_setups = [s for s in gap_down_bullish if s["conviction"] >= conv]
        if not conv_setups:
            continue

        returns_30m = []
        for s in conv_setups:
            if len(s["bars"]) >= 7:
                entry = s["bars"][1]["close"]
                exit30 = s["bars"][6]["close"]
                if entry > 0:
                    returns_30m.append((exit30 / entry - 1) * 100)

        if returns_30m:
            win_pct = sum(1 for r in returns_30m if r > 0) / len(returns_30m) * 100
            print(
                f"    Conv>={conv}: {len(returns_30m):4d}건 | "
                f"양봉확률={win_pct:.1f}% | "
                f"평균={np.mean(returns_30m):+.3f}% | "
                f"중앙={np.median(returns_30m):+.3f}%"
            )

    # 개별 시그널별 효과
    print(f"\n  [개별 시그널별 30분 후 양봉 확률]")
    signals = [
        ("prev_bullish", "전일 양봉"),
        ("prev_vol_surge", "전일 거래량 2x+"),
        ("prev_uptrend", "전일 > 5일선"),
        ("prev_strong_close", "전일 강한 종가"),
        ("hong_strong_pos", "Hong 신고가/전고점"),
        ("ki_high", "끼점수 30+"),
    ]

    for key, label in signals:
        with_signal = [s for s in gap_down_bullish if s.get(key, False)]
        without_signal = [s for s in gap_down_bullish if not s.get(key, False)]

        for subset, slabel in [(with_signal, "O"), (without_signal, "X")]:
            rets = []
            for s in subset:
                if len(s["bars"]) >= 7:
                    entry = s["bars"][1]["close"]
                    exit30 = s["bars"][6]["close"]
                    if entry > 0:
                        rets.append((exit30 / entry - 1) * 100)
            if rets:
                win_pct = sum(1 for r in rets if r > 0) / len(rets) * 100
                print(
                    f"    {label:15s} [{slabel}]: {len(rets):4d}건, "
                    f"양봉={win_pct:.1f}%, 평균={np.mean(rets):+.3f}%"
                )


# ══════════════════════════════════════════════════════
#  뉴스 점수 사전 계산
# ══════════════════════════════════════════════════════
def precompute_news_scores(setups, cache_path="cache/news_scores_backtest.json"):
    """Hong Strong 갭 셋업 종목의 뉴스 점수 사전 계산 (캐시 지원).

    1. Hong Strong + 갭다운 + 첫봉양봉 셋업만 대상
    2. 네이버 뉴스 크롤링 (종목별 전체 → 날짜별 그룹핑)
    3. GPT-4o-mini 감성분석
    4. JSON 파일로 캐시

    Returns:
        {code: {date: score}} - score: -1.0 ~ +1.0
    """
    import json
    from src.news.naver_scraper import NaverNewsScraper
    from src.news.sentiment import NewsSentimentAnalyzer

    cache_file = Path(cache_path)

    # 캐시 로드
    cached = {}
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)

    # Hong Strong + 갭다운 + 첫봉양봉 셋업 추출
    hs_setups = [
        s for s in setups
        if s["hong_strong_pos"] and s["gap_pct"] < 0 and s["first_bar_bullish"]
    ]

    # 종목/날짜 조합 추출
    code_dates = {}  # {code: set(date_str)}
    for s in hs_setups:
        code = s["code"]
        d_str = str(s["date"])
        if code not in code_dates:
            code_dates[code] = set()
        code_dates[code].add(d_str)

    # 캐시 안 된 것만 추출
    to_fetch = {}
    for code, dates in code_dates.items():
        for d_str in dates:
            cache_key = f"{code}_{d_str}"
            if cache_key not in cached:
                if code not in to_fetch:
                    to_fetch[code] = set()
                to_fetch[code].add(d_str)

    total_cached = sum(
        1 for s in hs_setups
        if f"{s['code']}_{s['date']}" in cached
    )
    total_needed = sum(len(d) for d in to_fetch.values())

    print(f"\n  [뉴스 점수 계산]")
    print(f"  Hong Strong 셋업: {len(hs_setups)}건 (종목 {len(code_dates)}개)")
    print(f"  캐시 히트: {total_cached}건, 신규 크롤링: {total_needed}건")

    if not to_fetch:
        print(f"  → 전체 캐시 완료!")
    else:
        scraper = NaverNewsScraper(delay=0.2)
        analyzer = NewsSentimentAnalyzer(model="gpt-4o-mini")

        for code in tqdm(list(to_fetch.keys()), desc="  뉴스 수집+분석"):
            target_dates = to_fetch[code]

            # 종목 뉴스 전체 가져오기 (충분한 페이지)
            articles = scraper.fetch_news(
                code, max_pages=10, max_articles=200
            )

            # 날짜별 그룹핑
            by_date = defaultdict(list)
            for a in articles:
                by_date[str(a.date)].append(a.title)

            # 필요한 날짜만 GPT 분석
            for d_str in target_dates:
                cache_key = f"{code}_{d_str}"
                headlines = by_date.get(d_str, [])

                if headlines:
                    score, reason = analyzer.analyze_headlines(
                        headlines[:15],
                        stock_code=code,
                        target_date=d_str,
                    )
                else:
                    score = 0.0  # 뉴스 없음 = 중립

                cached[cache_key] = score

        # 캐시 저장
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(cached, f, ensure_ascii=False, indent=2)
        print(f"  뉴스 분석 완료 → {cache_path} ({len(cached)}건)")

    # setup에 news_score 추가
    for s in setups:
        cache_key = f"{s['code']}_{s['date']}"
        s["news_score"] = cached.get(cache_key, 0.0)

    # 뉴스 점수 분포 출력
    hs_scores = [s["news_score"] for s in hs_setups]
    if hs_scores:
        pos = sum(1 for sc in hs_scores if sc > 0)
        neg = sum(1 for sc in hs_scores if sc < 0)
        neu = sum(1 for sc in hs_scores if sc == 0)
        print(f"\n  [뉴스 점수 분포 (Hong Strong 셋업)]")
        print(f"    긍정(>0): {pos}건, 중립(=0): {neu}건, 부정(<0): {neg}건")
        print(f"    평균: {np.mean(hs_scores):+.3f}, 중앙: {np.median(hs_scores):+.3f}")

        # 뉴스 점수대별 30분 후 수익률
        print(f"\n  [뉴스 점수별 30분 후 양봉 확률]")
        for threshold_label, lo, hi in [
            ("부정 (<-0.3)", -1.0, -0.3),
            ("약부정 (-0.3~0)", -0.3, 0.0),
            ("중립 (=0)", -0.001, 0.001),
            ("약긍정 (0~0.3)", 0.0, 0.3),
            ("긍정 (>=0.3)", 0.3, 1.01),
        ]:
            subset = [s for s in hs_setups if lo <= s["news_score"] < hi]
            rets = []
            for s in subset:
                if len(s["bars"]) >= 7:
                    entry = s["bars"][1]["close"]
                    exit30 = s["bars"][6]["close"]
                    if entry > 0:
                        rets.append((exit30 / entry - 1) * 100)
            if rets:
                wp = sum(1 for r in rets if r > 0) / len(rets) * 100
                print(f"    {threshold_label:18s}: {len(rets):4d}건, "
                      f"양봉={wp:.1f}%, 평균={np.mean(rets):+.3f}%")

    return cached


def grid_search_with_news(setups, all_dates, hong_filter=True):
    """뉴스 점수 포함 그리드 서치."""
    split_idx = int(len(all_dates) * 0.75)
    is_dates = set(all_dates[:split_idx])
    oos_dates = set(all_dates[split_idx:])

    is_setups = [s for s in setups if s["date"] in is_dates]
    oos_setups = [s for s in setups if s["date"] in oos_dates]

    print(f"  IS 기간: {min(is_dates)} ~ {max(is_dates)} ({len(is_dates)}일)")
    print(f"  OOS 기간: {min(oos_dates)} ~ {max(oos_dates)} ({len(oos_dates)}일)")

    # 그리드 (Hong Strong ON 고정 + 뉴스 점수)
    gap_mins = [-0.05, -0.03, -0.02]
    gap_maxs = [-0.003, -0.005, -0.01]
    sls = [0.015, 0.02, 0.025, 0.03]
    tps = [0.02, 0.03, 0.04, 0.05]
    exit_times = [time(10, 0), time(10, 30), time(11, 0), time(11, 30)]
    news_mins = [0.0, 0.1, 0.2, 0.3, 0.5]  # ★ 뉴스 점수 최소값

    results = []
    combos = list(product(
        gap_mins, gap_maxs, [1.0], [0],
        sls, tps, exit_times, news_mins,
    ))

    for gmin, gmax, vmin, vmax, sl, tp, et, news_min in tqdm(combos, desc="  뉴스 그리드"):
        if gmin >= gmax:
            continue

        is_trades = run_with_params_news(
            is_setups, gmin, gmax, vmin, vmax, sl, tp, et,
            hong_filter, require_hong_strong=True, min_news_score=news_min,
        )
        oos_trades = run_with_params_news(
            oos_setups, gmin, gmax, vmin, vmax, sl, tp, et,
            hong_filter, require_hong_strong=True, min_news_score=news_min,
        )

        is_m = calc_metrics(is_trades)
        oos_m = calc_metrics(oos_trades)

        results.append({
            "gap_min": gmin, "gap_max": gmax,
            "vol_min": vmin, "vol_max": vmax,
            "sl": sl, "tp": tp, "exit_time": et,
            "conviction_min": 0,
            "hong_strong": True,
            "news_min": news_min,
            "is": is_m, "oos": oos_m,
        })

    return results, is_dates, oos_dates


def run_with_params_news(setups, gap_min, gap_max, vol_min, vol_max, sl, tp,
                         exit_time, hong_filter, require_hong_strong=True,
                         min_news_score=0.0):
    """뉴스 점수 포함 전략 실행."""
    by_date = defaultdict(list)
    for setup in setups:
        if setup["gap_pct"] < gap_min or setup["gap_pct"] > gap_max:
            continue
        if not setup["first_bar_bullish"]:
            continue
        if setup["vol_ratio"] < vol_min or (vol_max > 0 and setup["vol_ratio"] > vol_max):
            continue
        if hong_filter and not setup["hong_passes"]:
            continue
        if require_hong_strong and not setup["hong_strong_pos"]:
            continue
        if min_news_score > 0 and setup.get("news_score", 0) < min_news_score:
            continue
        by_date[setup["date"]].append(setup)

    trades = []
    for dt in sorted(by_date.keys()):
        day_setups = by_date[dt]
        # 뉴스 점수 높은 순 → 갭 큰 순
        day_setups.sort(key=lambda s: (-s.get("news_score", 0), -abs(s["gap_pct"])))

        day_trades = 0
        for setup in day_setups:
            if day_trades >= MAX_POSITIONS_PER_DAY:
                break
            for entry_bar in [1, 2]:
                trade = simulate_trade(setup, entry_bar, sl, tp, exit_time)
                if trade:
                    trade["news_score"] = setup.get("news_score", 0)
                    trades.append(trade)
                    day_trades += 1
                    break

    return trades


def print_news_grid_results(results, setups=None):
    """뉴스 그리드 결과 출력."""
    filtered = [r for r in results if r["is"]["n_trades"] >= 3]
    if not filtered:
        print("  거래수 3건+ 조합 없음")
        return None

    # 뉴스 점수별 요약
    print(f"\n{'━' * 100}")
    print(f"  뉴스 점수 레벨별 성과 요약 (Hong Strong ON, IS 기준)")
    print(f"{'━' * 100}")

    for news_min in sorted(set(r["news_min"] for r in filtered)):
        nm_results = [r for r in filtered if r["news_min"] == news_min]
        if not nm_results:
            continue
        best_wr = max(nm_results, key=lambda r: r["is"]["win_rate"])
        best_ret = max(nm_results, key=lambda r: r["is"]["total_return"])
        avg_wr = np.mean([r["is"]["win_rate"] for r in nm_results])
        avg_trades = np.mean([r["is"]["n_trades"] for r in nm_results])
        print(
            f"  news>={news_min:.1f}: {len(nm_results):3d}개 조합 | "
            f"평균 거래={avg_trades:.0f}, 평균 WR={avg_wr:.1f}%"
            f" | 최고 WR={best_wr['is']['win_rate']:.1f}% "
            f"(거래 {best_wr['is']['n_trades']}건)"
            f" | 최고 Ret={best_ret['is']['total_return']:+.2f}%"
        )

    # IS 승률 기준 TOP 20
    filtered.sort(key=lambda r: r["is"]["win_rate"], reverse=True)

    print(f"\n{'━' * 110}")
    print(f"  뉴스 그리드 - IS 승률 기준 TOP 20")
    print(f"{'━' * 110}")
    print(f"  {'#':>3} {'Gap범위':>12} {'SL':>5} {'TP':>5} {'Exit':>6} {'News':>5}"
          f" | {'IS거래':>5} {'IS승률':>7} {'IS수익':>8} {'IS평균':>7}"
          f" | {'OOS거래':>6} {'OOS승률':>7} {'OOS수익':>8}")
    print(f"  {'─' * 108}")

    for i, r in enumerate(filtered[:20]):
        et_str = f"{r['exit_time'].hour}:{r['exit_time'].minute:02d}"
        gap_str = f"{r['gap_min']*100:.0f}~{r['gap_max']*100:.1f}%"
        print(
            f"  {i+1:3d} {gap_str:>12} "
            f"{r['sl']*100:>4.1f}% {r['tp']*100:>4.1f}% {et_str:>6} "
            f"{r['news_min']:>5.1f}"
            f" | {r['is']['n_trades']:>5d} {r['is']['win_rate']:>6.1f}% "
            f"{r['is']['total_return']:>+7.2f}% {r['is']['avg_pnl']:>+6.2f}%"
            f" | {r['oos']['n_trades']:>5d} {r['oos']['win_rate']:>7.1f}% "
            f"{r['oos']['total_return']:>+7.2f}%"
        )

    # IS 수익률 기준 TOP 10
    by_return = sorted(filtered, key=lambda r: r["is"]["total_return"], reverse=True)
    print(f"\n{'━' * 110}")
    print(f"  IS 수익률 기준 TOP 10")
    print(f"{'━' * 110}")
    for i, r in enumerate(by_return[:10]):
        et_str = f"{r['exit_time'].hour}:{r['exit_time'].minute:02d}"
        gap_str = f"{r['gap_min']*100:.0f}~{r['gap_max']*100:.1f}%"
        print(
            f"  {i+1:3d} {gap_str:>12} SL{r['sl']*100:.1f}% TP{r['tp']*100:.1f}% "
            f"@{et_str} News>={r['news_min']:.1f}"
            f" | IS: {r['is']['n_trades']}건 WR={r['is']['win_rate']:.1f}% "
            f"Ret={r['is']['total_return']:+.2f}%"
            f" | OOS: {r['oos']['n_trades']}건 WR={r['oos']['win_rate']:.1f}% "
            f"Ret={r['oos']['total_return']:+.2f}%"
        )

    # OOS 안정 조합
    stable = [
        r for r in filtered
        if r["is"]["win_rate"] >= 55
        and r["oos"]["n_trades"] >= 2
        and r["oos"]["win_rate"] >= r["is"]["win_rate"] * 0.65
        and r["oos"]["total_return"] > -10
    ]
    stable.sort(key=lambda r: r["is"]["total_return"], reverse=True)

    print(f"\n{'━' * 110}")
    print(f"  OOS 안정 조합 (IS WR>=55%, OOS WR>=IS*0.65) - {len(stable)}건")
    print(f"{'━' * 110}")
    for i, r in enumerate(stable[:15]):
        et_str = f"{r['exit_time'].hour}:{r['exit_time'].minute:02d}"
        print(
            f"  {i+1:3d} gap=[{r['gap_min']*100:.0f}%,{r['gap_max']*100:.1f}%] "
            f"SL{r['sl']*100:.1f}% TP{r['tp']*100:.1f}% @{et_str} "
            f"News>={r['news_min']:.1f}"
            f" | IS: {r['is']['n_trades']}건 WR={r['is']['win_rate']:.1f}% "
            f"Ret={r['is']['total_return']:+.2f}%"
            f" | OOS: {r['oos']['n_trades']}건 WR={r['oos']['win_rate']:.1f}% "
            f"Ret={r['oos']['total_return']:+.2f}%"
        )

    if stable:
        best = stable[0]
        print(f"\n  >>> 뉴스 최적 파라미터 <<<")
        print(f"  gap=[{best['gap_min']}, {best['gap_max']}], "
              f"SL={best['sl']}, TP={best['tp']}, exit={best['exit_time']}")
        print(f"  news_min={best['news_min']}, hong_strong=True")
        print(f"  IS: {best['is']['n_trades']}건, WR={best['is']['win_rate']:.1f}%, "
              f"Ret={best['is']['total_return']:+.2f}%")
        print(f"  OOS: {best['oos']['n_trades']}건, WR={best['oos']['win_rate']:.1f}%, "
              f"Ret={best['oos']['total_return']:+.2f}%")

        # 최적 파라미터로 전체 기간 백테스트
        best_params = {
            "gap_min": best["gap_min"], "gap_max": best["gap_max"],
            "sl": best["sl"], "tp": best["tp"],
            "exit_time": best["exit_time"],
            "hong_strong": True,
            "news_min": best["news_min"],
        }
        print(f"\n  뉴스 최적 파라미터 전체 백테스트...")
        all_trades = run_with_params_news(
            setups,
            best_params["gap_min"], best_params["gap_max"],
            1.0, 0, best_params["sl"], best_params["tp"],
            best_params["exit_time"], hong_filter=False,
            require_hong_strong=True, min_news_score=best_params["news_min"],
        )
        if all_trades:
            m = calc_metrics(all_trades)
            # 자본금 추적
            capital = float(INITIAL_CAPITAL)
            peak = capital
            max_dd = 0
            for t in sorted(all_trades, key=lambda x: x["date"]):
                invest = capital * POSITION_SIZE
                pnl = invest * (t["net_pnl_pct"] / 100)
                capital += pnl
                if capital > peak:
                    peak = capital
                dd = (capital - peak) / peak * 100
                if dd < max_dd:
                    max_dd = dd

            total_return = (capital / INITIAL_CAPITAL - 1) * 100
            print(f"\n  전체 기간: {m['n_trades']}건, WR={m['win_rate']:.1f}%, "
                  f"Ret={total_return:+.2f}%, MDD={max_dd:.2f}%")

            # 뉴스 점수별 승률
            print(f"\n  [뉴스 점수대별 승률]")
            for lo, hi, label in [
                (0.0, 0.2, "0.0~0.2"),
                (0.2, 0.4, "0.2~0.4"),
                (0.4, 0.6, "0.4~0.6"),
                (0.6, 1.01, "0.6~1.0"),
            ]:
                subset = [t for t in all_trades if lo <= t.get("news_score", 0) < hi]
                if subset:
                    w = sum(1 for t in subset if t["win"])
                    wr = w / len(subset) * 100
                    print(f"    news {label}: {len(subset):3d}건, WR={wr:.1f}%")

    return stable[0] if stable else None


# ══════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "grid"
    hong_filter = mode not in ("no-hong",)

    print("=" * 70)
    print("  Opening Gap Reversal Strategy v2 - 확신 점수 기반")
    print(f"  자본금: {INITIAL_CAPITAL:,}원 | 포지션: {POSITION_SIZE:.0%}")
    print(f"  비용: {COST_PCT:.2f}%/건 | Hong 필터: {'ON' if hong_filter else 'OFF'}")
    print("=" * 70)

    print("\n  데이터 로딩...")
    t0 = time_module.time()
    intraday_data, prev_day_info, daily_context, all_dates = load_data()
    print(f"  5분봉: {len(intraday_data)}종목, {len(all_dates)}일")
    print(f"  로딩: {time_module.time() - t0:.1f}초")

    print("\n  갭 셋업 사전 계산...")
    t0 = time_module.time()
    setups = precompute_gap_setups(intraday_data, prev_day_info, daily_context, all_dates)
    gap_down_setups = [s for s in setups if s["gap_pct"] < 0]
    bullish_setups = [s for s in gap_down_setups if s["first_bar_bullish"]]
    print(f"  전체 갭다운 셋업: {len(gap_down_setups)}건")
    print(f"  첫봉 양봉 셋업: {len(bullish_setups)}건")
    print(f"  계산: {time_module.time() - t0:.1f}초")

    # 갭/볼륨/확신 분포 출력
    gaps = [s["gap_pct"] for s in gap_down_setups]
    convictions = [s["conviction"] for s in bullish_setups]

    if gaps:
        print(f"\n  [갭 분포]")
        for threshold in [-0.01, -0.02, -0.03, -0.05, -0.07]:
            count = sum(1 for g in gaps if g <= threshold)
            print(f"    {threshold*100:+.0f}% 이하: {count}건")

    if convictions:
        print(f"\n  [확신 점수 분포 (갭다운+양봉)]")
        for c in range(7):
            count = sum(1 for cv in convictions if cv == c)
            pct = count / len(convictions) * 100
            print(f"    Conv={c}: {count:5d}건 ({pct:.1f}%)")

    if mode == "news":
        # 뉴스 점수 사전 계산
        print(f"\n  뉴스 점수 사전 계산...")
        t0 = time_module.time()
        precompute_news_scores(setups)
        print(f"  뉴스 계산: {time_module.time() - t0:.1f}초")

        # 뉴스 포함 그리드 서치
        print(f"\n  뉴스 그리드 서치 시작...")
        t0 = time_module.time()
        results, is_dates, oos_dates = grid_search_with_news(
            setups, all_dates, hong_filter=False
        )
        print(f"  완료: {time_module.time() - t0:.1f}초, {len(results)}개 조합")

        print_news_grid_results(results, setups)

    elif mode == "analyze":
        analyze_conviction(setups, all_dates)

    elif mode == "best":
        # 최적 파라미터 수동 지정 (그리드 서치 결과에서 복사)
        best_params = {
            "gap_min": -0.03, "gap_max": -0.005,
            "sl": 0.02, "tp": 0.04,
            "exit_time": time(10, 30),
            "conviction_min": 3,
        }
        print(f"\n  최적 파라미터로 전체 기간 백테스트...")
        print(f"  conviction_min={best_params['conviction_min']}")
        run_full_backtest(setups, all_dates, best_params, hong_filter)

    else:
        # 그리드 서치
        print(f"\n  그리드 서치 시작...")
        t0 = time_module.time()
        results, is_dates, oos_dates = grid_search(setups, all_dates, hong_filter)
        print(f"  완료: {time_module.time() - t0:.1f}초, {len(results)}개 조합")

        best = print_grid_results(results, "ON" if hong_filter else "OFF")

        if best:
            best_params = {
                "gap_min": best["gap_min"], "gap_max": best["gap_max"],
                "vol_max": best["vol_max"], "sl": best["sl"], "tp": best["tp"],
                "exit_time": best["exit_time"],
                "conviction_min": best["conviction_min"],
                "hong_strong": best.get("hong_strong", False),
            }
            print(f"\n  최적 파라미터로 전체 기간 백테스트...")
            run_full_backtest(setups, all_dates, best_params, hong_filter)

        # Hong 필터 OFF + hong_strong 필터로도 테스트
        if hong_filter:
            print(f"\n\n{'=' * 70}")
            print(f"  [비교] Hong 필터 OFF 그리드 서치")
            print(f"{'=' * 70}")
            t0 = time_module.time()
            results_no_hong, _, _ = grid_search(setups, all_dates, hong_filter=False)
            print(f"  완료: {time_module.time() - t0:.1f}초")
            best_no_hong = print_grid_results(results_no_hong, "OFF")

            if best_no_hong:
                best_params_nh = {
                    "gap_min": best_no_hong["gap_min"],
                    "gap_max": best_no_hong["gap_max"],
                    "vol_max": best_no_hong["vol_max"],
                    "sl": best_no_hong["sl"], "tp": best_no_hong["tp"],
                    "exit_time": best_no_hong["exit_time"],
                    "conviction_min": best_no_hong["conviction_min"],
                    "hong_strong": best_no_hong.get("hong_strong", False),
                }
                print(f"\n  Hong OFF 최적 파라미터 전체 백테스트...")
                run_full_backtest(setups, all_dates, best_params_nh, hong_filter=False)


if __name__ == "__main__":
    main()
