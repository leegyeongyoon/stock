"""
2026-02-12 백테스트: 조기 돌파 (9:30 진입 가능)

비교:
  기존(V1): 돌파 window 9:30~11:00, 5봉 lookback → 최빠른 진입 9:55
  조기(V2): 9:00~9:30을 lookback으로 포함 → 9:30부터 진입 가능

동일 조건:
  유니버스: 당일 거래대금 TOP100 + 등락률 +3% (합집합)
  주도주: 9:00~9:30 모멘텀 TOP20
  눌림: 13:00~14:30, 오전고점 98% + 반등
  SL -4%, TP +5%
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from dataclasses import dataclass

TARGET_DATE = "20260212"
PREV_DATE = "20260211"

SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70

_kosdaq_set = None

def get_kosdaq_set():
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(TARGET_DATE, market="KOSDAQ"))
    return _kosdaq_set

def code_to_ticker(code):
    return f"{code}{'.KQ' if code in get_kosdaq_set() else '.KS'}"


@dataclass
class Trade:
    code: str
    name: str
    method: str
    entry_time: str
    entry_price: float
    exit_time: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""


def fetch_universe():
    """당일 거래대금 TOP100 + 등락률 +3% 합집합"""
    print("=" * 60)
    print("  1. 유니버스 (당일 TOP100 + 강세 3%+)")
    print("=" * 60)

    df = pykrx_stock.get_market_ohlcv_by_ticker(TARGET_DATE, market="ALL")
    df = df[df["거래량"] > 0]

    top100 = set(df.nlargest(100, "거래대금").index.tolist())
    strong = set(df[df["등락률"] >= 3.0].index.tolist())
    universe = top100 | strong

    print(f"  TOP100 거래대금: {len(top100)}개")
    print(f"  등락률 +3%+:     {len(strong)}개")
    print(f"  합집합:           {len(universe)}개")

    df_prev = pykrx_stock.get_market_ohlcv_by_ticker(PREV_DATE, market="ALL")
    return list(universe), df, df_prev


def fetch_5min(codes):
    """5분봉 수집"""
    print("\n" + "=" * 60)
    print("  2. 5분봉 수집")
    print("=" * 60)

    bars_dict = {}
    failed = 0
    batch_size = 20

    for bs in range(0, len(codes), batch_size):
        batch = codes[bs:bs + batch_size]
        tickers = [code_to_ticker(c) for c in batch]

        try:
            data = yf.download(" ".join(tickers), period="5d", interval="5m",
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

                    day = df[df.index.date == pd.Timestamp("2026-02-12").date()]
                    if len(day) >= 10:
                        bars_dict[code] = day
                except Exception:
                    failed += 1
        except Exception:
            failed += len(batch)

        done = bs + len(batch)
        if (done // batch_size) % 10 == 0 and done > 0:
            print(f"    {done}/{len(codes)} ({len(bars_dict)}개)")

    print(f"  완료: {len(bars_dict)}개 성공, {failed}개 실패")
    return bars_dict


def select_leaders(bars_dict, df_market):
    """9:00~9:30 모멘텀 TOP20"""
    print("\n" + "=" * 60)
    print("  3. 주도주 TOP20 (9:00~9:30 모멘텀)")
    print("=" * 60)

    scores = []
    for code, df in bars_dict.items():
        morning = df[(df.index.hour == 9) & (df.index.minute < 30)]
        if len(morning) < 2:
            continue

        vol_sum = morning["Volume"].sum()
        pchg = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
        momentum = vol_sum * max(pchg, 0)

        name = pykrx_stock.get_market_ticker_name(code) or code
        scores.append({"code": code, "name": name, "momentum": momentum, "pchg": pchg})

    scores.sort(key=lambda x: x["momentum"], reverse=True)
    leaders = scores[:20]

    print(f"  TOP 10:")
    for i, s in enumerate(leaders[:10], 1):
        print(f"    {i:2d}. {s['name']:12s} | 오전 {s['pchg']:+.1f}%")

    return {s["code"]: s for s in leaders}


def find_breakout_v1(bars):
    """기존 돌파: 9:30~11:00만 사용, 최빠른 진입 ~9:55"""
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
                return {"price": bar["Close"], "time": window.index[i]}
    return None


def find_breakout_early(bars):
    """조기 돌파: 9:00~11:00 전체, 9:00~9:30을 lookback으로 활용

    9:00~9:30 봉 = lookback (5~6봉)
    9:30부터 = 돌파 진입 가능

    즉, 9:30 봉이 9:00~9:25의 5봉 고점을 돌파하면 바로 진입
    """
    # 전체 오전 봉 (9:00~11:00)
    window = bars[
        (bars.index.hour == 9) |
        (bars.index.hour == 10)
    ]
    if len(window) < 6:
        return None

    # 9:30 이후 봉만 진입 후보 (9:00~9:30은 lookback 전용)
    for i in range(5, len(window)):
        bar = window.iloc[i]
        bar_time = window.index[i]

        # 9:30 이전은 진입 안함 (lookback용)
        if bar_time.hour == 9 and bar_time.minute < 30:
            continue

        ph = window["High"].iloc[i-5:i].max()
        if bar["High"] > ph and bar["Close"] > ph:
            av = window["Volume"].iloc[i-5:i].mean()
            if av > 0 and bar["Volume"] >= av * 1.2:
                return {"price": bar["Close"], "time": bar_time}
    return None


def find_pullback(bars):
    """눌림: 13:00~14:30"""
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
        if (prev["Low"] <= mh * 0.98 and
            bar["Close"] > prev["Close"] and
            bar["Close"] > r50 and
            bar["Low"] > ml):
            return {"price": bar["Close"], "time": window.index[i]}
    return None


def simulate(bars, entry, method, code, name):
    ep, et = entry["price"], entry["time"]
    after = bars[bars.index > et]
    trade = Trade(code=code, name=name, method=method,
                  entry_time=str(et)[:16], entry_price=ep)

    for ts, bar in after.iterrows():
        lo = (bar["Low"] / ep) - 1
        hi = (bar["High"] / ep) - 1
        if lo <= SL_PCT:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = ep * (1 + SL_PCT)
            trade.pnl_pct = SL_PCT * 100
            trade.exit_reason = "손절-4%"
            return trade
        if hi >= TP_PCT:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = ep * (1 + TP_PCT * TP_PARTIAL)
            trade.pnl_pct = TP_PCT * TP_PARTIAL * 100
            trade.exit_reason = "익절+5%"
            return trade

    if len(after) > 0:
        last = after.iloc[-1]
        trade.exit_time = str(after.index[-1])[:16]
        trade.exit_price = last["Close"]
        trade.pnl_pct = ((last["Close"] / ep) - 1) * 100
        trade.exit_reason = "장마감"
    return trade


def run_strategy(bars_dict, leaders, version, breakout_fn):
    """돌파+눌림 실행"""
    leader_codes = set(leaders.keys())
    all_trades = []
    traded = set()

    # 돌파
    for code in leader_codes:
        if code in traded or code not in bars_dict:
            continue
        bars = bars_dict[code]
        entry = breakout_fn(bars)
        if entry:
            name = leaders[code]["name"]
            trade = simulate(bars, entry, "돌파", code, name)
            all_trades.append(trade)
            traded.add(code)

    # 눌림
    for code in leader_codes:
        if code in traded or code not in bars_dict:
            continue
        bars = bars_dict[code]
        entry = find_pullback(bars)
        if entry:
            name = leaders[code]["name"]
            trade = simulate(bars, entry, "눌림", code, name)
            all_trades.append(trade)
            traded.add(code)

    return all_trades


def print_result(trades, label):
    print(f"\n{'─'*65}")
    print(f"  {label}")
    print(f"{'─'*65}")

    if not trades:
        print("  매매 없음")
        return

    total = len(trades)
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    total_pnl = sum(t.pnl_pct for t in trades)

    print(f"  전체: {total}건 | {wins}W {total-wins}L | "
          f"WR {wins/total*100:.0f}% | 합계 {total_pnl:+.2f}%")

    for m in ["돌파", "눌림"]:
        ts = [t for t in trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl_pct > 0)
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | {mp:+.2f}%")

    print(f"\n  {'#':>2} {'방법':4s} {'종목':12s} {'진입':>6s} {'청산':>6s} {'수익률':>8s} {'사유'}")
    print(f"  {'─'*60}")
    for i, t in enumerate(trades, 1):
        mkt = "KQ" if t.code in get_kosdaq_set() else "KS"
        print(f"  {i:2d} {t.method:4s} {t.name:12s} {t.entry_time[11:]:>6s} "
              f"{t.exit_time[11:]:>6s} {t.pnl_pct:+6.2f}% {t.exit_reason} [{mkt}]")


def main():
    codes, df_market, df_prev = fetch_universe()
    bars_dict = fetch_5min(codes)
    leaders = select_leaders(bars_dict, df_market)

    print("\n" + "=" * 65)
    print("  4. 비교: 기존 돌파(9:55+) vs 조기 돌파(9:30+)")
    print("=" * 65)

    # V1: 기존 (9:30~11:00 window, 진입 9:55+)
    trades_v1 = run_strategy(bars_dict, leaders, "V1", find_breakout_v1)
    print_result(trades_v1, "V1 기존 돌파 (최빠른 진입 ~9:55)")

    # V2: 조기 (9:00~11:00 window, 9:00~9:30 lookback, 진입 9:30+)
    trades_v2 = run_strategy(bars_dict, leaders, "V2", find_breakout_early)
    print_result(trades_v2, "V2 조기 돌파 (9:00 lookback → 진입 9:30+)")

    # 비교
    print("\n" + "=" * 65)
    print("  5. 비교 요약")
    print("=" * 65)

    for label, trades in [("V1 기존(9:55+)", trades_v1), ("V2 조기(9:30+)", trades_v2)]:
        if trades:
            total = len(trades)
            wins = sum(1 for t in trades if t.pnl_pct > 0)
            pnl = sum(t.pnl_pct for t in trades)
            dolpa = [t for t in trades if t.method == "돌파"]
            d_pnl = sum(t.pnl_pct for t in dolpa)
            print(f"  {label}: {total}건 | {wins}W {total-wins}L | "
                  f"WR {wins/total*100:.0f}% | 합계 {pnl:+.2f}% (돌파만 {d_pnl:+.2f}%)")
        else:
            print(f"  {label}: 매매 없음")

    # 진입 시간 비교
    print(f"\n  돌파 진입 시간 비교:")
    v1_dolpa = [t for t in trades_v1 if t.method == "돌파"]
    v2_dolpa = [t for t in trades_v2 if t.method == "돌파"]

    all_codes = set(t.code for t in v1_dolpa) | set(t.code for t in v2_dolpa)
    v1_map = {t.code: t for t in v1_dolpa}
    v2_map = {t.code: t for t in v2_dolpa}

    for code in sorted(all_codes):
        t1 = v1_map.get(code)
        t2 = v2_map.get(code)
        name = (t1 or t2).name
        e1 = t1.entry_time[11:] if t1 else "─────"
        e2 = t2.entry_time[11:] if t2 else "─────"
        p1 = f"{t1.pnl_pct:+.2f}%" if t1 else "  ───"
        p2 = f"{t2.pnl_pct:+.2f}%" if t2 else "  ───"
        diff = ""
        if t1 and t2:
            d = t2.pnl_pct - t1.pnl_pct
            diff = f"  (차이 {d:+.2f}%)"
        elif t2 and not t1:
            diff = "  (V2에서만 진입)"
        elif t1 and not t2:
            diff = "  (V1에서만 진입)"
        print(f"    {name:12s} | V1 {e1} {p1} | V2 {e2} {p2}{diff}")


if __name__ == "__main__":
    main()
