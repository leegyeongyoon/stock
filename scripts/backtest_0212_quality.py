"""
2026-02-12 백테스트: 잡주 필터링 (시가총액/거래대금 기준)

비교:
  A) 현재: TOP100+강세 합집합 → TOP20 모멘텀 (잡주 포함)
  B) 거래대금 TOP50만
  C) 시가총액 3000억+
  D) 시가총액 5000억+
  E) 거래대금 TOP30 + 시가총액 3000억+
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


def fetch_data():
    """유니버스 + 시가총액 데이터"""
    print("=" * 65)
    print("  1. 데이터 수집")
    print("=" * 65)

    df_ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(TARGET_DATE, market="ALL")
    df_ohlcv = df_ohlcv[df_ohlcv["거래량"] > 0]

    # 시가총액 가져오기
    df_cap = pykrx_stock.get_market_cap_by_ticker(TARGET_DATE, market="ALL")

    # 이미 시가총액 컬럼이 있으면 제거 후 합치기
    if "시가총액" in df_ohlcv.columns:
        df = df_ohlcv.copy()
        df["시가총액"] = df_cap["시가총액"]
    else:
        df = df_ohlcv.join(df_cap[["시가총액"]], how="left")
    df["시가총액_억"] = df["시가총액"] / 1e8

    print(f"  전체 종목: {len(df)}개")
    print(f"  거래대금 TOP10:")
    top10 = df.nlargest(10, "거래대금")
    for i, (code, row) in enumerate(top10.iterrows(), 1):
        name = pykrx_stock.get_market_ticker_name(code) or code
        mkt = "KQ" if code in get_kosdaq_set() else "KS"
        print(f"    {i:2d}. {name:12s} [{mkt}] 거래대금 {row['거래대금']/1e8:,.0f}억 "
              f"시총 {row['시가총액_억']:,.0f}억 등락 {row['등락률']:+.1f}%")

    return df


def fetch_5min(codes):
    """5분봉 수집"""
    print("\n" + "=" * 65)
    print("  2. 5분봉 수집")
    print("=" * 65)

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


def select_leaders(bars_dict, eligible_codes, df_data, label=""):
    """모멘텀 TOP20 (eligible_codes 중에서)"""
    scores = []
    for code, bars in bars_dict.items():
        if code not in eligible_codes:
            continue
        morning = bars[(bars.index.hour == 9) & (bars.index.minute < 30)]
        if len(morning) < 2:
            continue

        vol_sum = morning["Volume"].sum()
        pchg = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
        momentum = vol_sum * max(pchg, 0)

        name = pykrx_stock.get_market_ticker_name(code) or code
        cap = df_data.loc[code, "시가총액_억"] if code in df_data.index else 0
        vol_krw = df_data.loc[code, "거래대금"] / 1e8 if code in df_data.index else 0
        mkt = "KQ" if code in get_kosdaq_set() else "KS"
        scores.append({
            "code": code, "name": name, "momentum": momentum,
            "pchg": pchg, "cap": cap, "vol_krw": vol_krw, "mkt": mkt
        })

    scores.sort(key=lambda x: x["momentum"], reverse=True)
    leaders = scores[:20]
    return {s["code"]: s for s in leaders}


def find_breakout(bars):
    """돌파: 9:30~11:00, 5봉고점 + 거래량 1.2x"""
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


def run_strategy(bars_dict, leaders, df_data):
    """돌파+눌림 실행"""
    leader_codes = set(leaders.keys())
    all_trades = []
    traded = set()

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


def print_result(trades, leaders, label):
    print(f"\n{'━'*65}")
    print(f"  {label}")
    print(f"{'━'*65}")

    # 리더 목록
    leader_list = sorted(leaders.values(), key=lambda x: x["momentum"], reverse=True)
    print(f"  선정 종목 ({len(leader_list)}개):")
    for i, s in enumerate(leader_list[:10], 1):
        print(f"    {i:2d}. {s['name']:12s} [{s['mkt']}] "
              f"시총 {s['cap']:,.0f}억 거래대금 {s['vol_krw']:,.0f}억 오전 {s['pchg']:+.1f}%")
    if len(leader_list) > 10:
        print(f"    ... +{len(leader_list)-10}개 더")

    if not trades:
        print("  → 매매 없음")
        return

    total = len(trades)
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    total_pnl = sum(t.pnl_pct for t in trades)

    print(f"\n  결과: {total}건 | {wins}W {total-wins}L | "
          f"WR {wins/total*100:.0f}% | 합계 {total_pnl:+.2f}%")

    for m in ["돌파", "눌림"]:
        ts = [t for t in trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl_pct > 0)
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | {mp:+.2f}%")

    print(f"\n  {'#':>2} {'방법':4s} {'종목':12s} {'시총':>7s} {'진입':>6s} {'청산':>6s} {'수익률':>8s} {'사유'}")
    print(f"  {'─'*65}")
    for i, t in enumerate(trades, 1):
        mkt = "KQ" if t.code in get_kosdaq_set() else "KS"
        cap = leaders[t.code]["cap"] if t.code in leaders else 0
        cap_str = f"{cap:,.0f}억" if cap > 0 else "?"
        print(f"  {i:2d} {t.method:4s} {t.name:12s} {cap_str:>7s} {t.entry_time[11:]:>6s} "
              f"{t.exit_time[11:]:>6s} {t.pnl_pct:+6.2f}% {t.exit_reason} [{mkt}]")


def main():
    df_data = fetch_data()

    # 전체 유니버스 (5분봉 수집용)
    top100 = set(df_data.nlargest(100, "거래대금").index.tolist())
    strong = set(df_data[df_data["등락률"] >= 3.0].index.tolist())
    all_universe = list(top100 | strong)
    print(f"\n  유니버스 합집합: {len(all_universe)}개")

    bars_dict = fetch_5min(all_universe)

    # === 필터별 유니버스 정의 ===
    filters = {}

    # A) 현재 (무필터)
    filters["A) 현재 (TOP100+강세 무필터)"] = set(all_universe)

    # B) 거래대금 TOP50만
    top50 = set(df_data.nlargest(50, "거래대금").index.tolist())
    filters["B) 거래대금 TOP50"] = top50 | strong

    # C) 시가총액 3000억+
    cap3000 = set(df_data[df_data["시가총액_억"] >= 3000].index.tolist())
    filters["C) 시총 3000억+"] = cap3000 & set(all_universe)

    # D) 시가총액 5000억+
    cap5000 = set(df_data[df_data["시가총액_억"] >= 5000].index.tolist())
    filters["D) 시총 5000억+"] = cap5000 & set(all_universe)

    # E) 거래대금 TOP30 + 시가총액 1000억+
    top30 = set(df_data.nlargest(30, "거래대금").index.tolist())
    cap1000 = set(df_data[df_data["시가총액_억"] >= 1000].index.tolist())
    filters["E) TOP30 + 시총 1000억+"] = (top30 & cap1000) | (strong & cap1000)

    # F) 거래대금 TOP50 + 시가총액 500억+
    cap500 = set(df_data[df_data["시가총액_억"] >= 500].index.tolist())
    filters["F) TOP50 + 시총 500억+"] = (top50 & cap500) | (strong & cap500)

    # G) 시가총액 1000억+ (폭넓게)
    cap1000_all = set(df_data[df_data["시가총액_억"] >= 1000].index.tolist())
    filters["G) 시총 1000억+"] = cap1000_all & set(all_universe)

    print("\n" + "=" * 65)
    print("  3. 필터별 백테스트")
    print("=" * 65)

    summary = []

    for label, eligible in filters.items():
        leaders = select_leaders(bars_dict, eligible, df_data, label)
        trades = run_strategy(bars_dict, leaders, df_data)
        print_result(trades, leaders, label)

        if trades:
            total = len(trades)
            wins = sum(1 for t in trades if t.pnl_pct > 0)
            pnl = sum(t.pnl_pct for t in trades)
            summary.append((label, len(eligible), len(leaders), total, wins, pnl))
        else:
            summary.append((label, len(eligible), len(leaders), 0, 0, 0))

    # 최종 비교
    print("\n" + "=" * 65)
    print("  4. 최종 비교")
    print("=" * 65)
    print(f"  {'필터':30s} {'풀':>4s} {'리더':>4s} {'매매':>4s} {'W':>3s} {'L':>3s} {'WR':>5s} {'합계':>8s}")
    print(f"  {'─'*65}")
    for label, pool, leaders, total, wins, pnl in summary:
        wr = f"{wins/total*100:.0f}%" if total > 0 else "─"
        print(f"  {label:30s} {pool:4d} {leaders:4d} {total:4d} {wins:3d} {total-wins:3d} {wr:>5s} {pnl:+8.2f}%")


if __name__ == "__main__":
    main()
