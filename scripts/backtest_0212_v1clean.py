"""
2026-02-12 백테스트: V1 조건 원복 (시초가X, 2연패정지X)

V1 원본 조건:
  유니버스: 당일 거래대금 TOP100 + 등락률 +3% (합집합)
  주도주: 9:00~9:30 모멘텀 TOP20
  돌파: 9:30~11:00, 5봉고점 돌파 + 거래량 1.2x
  눌림: 13:00~14:30, 오전고점 98% 눌림 + 반등
  SL -4%, TP +5%

변경점: 시초가매매 제거, 2연패 정지 제거
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
    """당일 거래대금 TOP100 + 등락률 +3% 합집합 (V1 조건)"""
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
    """5분봉 수집 (KOSDAQ .KQ 지원)"""
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
    """9:00~9:30 모멘텀 TOP20 (V1 조건)"""
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


def find_breakout(bars):
    """돌파: 9:30~11:00, 5봉고점 + 거래량 1.2x (V1 조건)"""
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


def find_pullback(bars):
    """눌림: 13:00~14:30, 오전고점 98% + 반등 (V1 조건)"""
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


def main():
    codes, df_market, df_prev = fetch_universe()
    bars_dict = fetch_5min(codes)
    leaders = select_leaders(bars_dict, df_market)
    leader_codes = set(leaders.keys())

    print("\n" + "=" * 60)
    print("  4. 매매 실행 (돌파+눌림, 시초가X, 2연패X)")
    print("=" * 60)

    all_trades = []
    traded = set()

    # 돌파 (9:30~11:00)
    print(f"\n  [A] 돌파매매 (9:30~11:00)")
    for code in leader_codes:
        if code in traded or code not in bars_dict:
            continue
        bars = bars_dict[code]
        entry = find_breakout(bars)
        if entry:
            name = leaders[code]["name"]
            trade = simulate(bars, entry, "돌파", code, name)
            all_trades.append(trade)
            traded.add(code)
            w = "W" if trade.pnl_pct > 0 else "L"
            print(f"    {w} {name:12s} | {trade.entry_time[11:]}→{trade.exit_time[11:]} | "
                  f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")

    # 눌림 (13:00~14:30)
    print(f"\n  [B] 눌림매매 (13:00~14:30)")
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
            w = "W" if trade.pnl_pct > 0 else "L"
            print(f"    {w} {name:12s} | {trade.entry_time[11:]}→{trade.exit_time[11:]} | "
                  f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")

    # 결과
    print("\n" + "=" * 70)
    print("  결과 요약: 2026-02-12")
    print("=" * 70)

    if not all_trades:
        print("  매매 없음")
        return

    total = len(all_trades)
    wins = sum(1 for t in all_trades if t.pnl_pct > 0)
    total_pnl = sum(t.pnl_pct for t in all_trades)

    print(f"\n  전체: {total}건 | {wins}W {total-wins}L | "
          f"WR {wins/total*100:.0f}% | 합계 {total_pnl:+.2f}%")

    for m in ["돌파", "눌림"]:
        ts = [t for t in all_trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl_pct > 0)
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | {mp:+.2f}%")

    print(f"\n  상세:")
    print(f"  {'#':>2} {'방법':4s} {'종목':12s} {'진입':>6s} {'청산':>6s} {'수익률':>8s} {'사유'}")
    print(f"  {'─'*60}")
    for i, t in enumerate(all_trades, 1):
        print(f"  {i:2d} {t.method:4s} {t.name:12s} {t.entry_time[11:]:>6s} "
              f"{t.exit_time[11:]:>6s} {t.pnl_pct:+6.2f}% {t.exit_reason}")


if __name__ == "__main__":
    main()
