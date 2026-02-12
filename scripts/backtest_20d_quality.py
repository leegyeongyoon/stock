"""
20일 백테스트: 시총 5000억+ 필터 vs 무필터

방법:
  1) 최근 20 거래일 추출
  2) 각 날짜별 유니버스(TOP100+강세) + 시가총액 조회
  3) 5분봉 일괄 수집 (yfinance period=1mo)
  4) 각 날짜별:
     - 무필터 TOP20 모멘텀 → 돌파+눌림
     - 시총 5000억+ TOP20 모멘텀 → 돌파+눌림
  5) 결과 비교
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from dataclasses import dataclass, field
from datetime import datetime
import time

END_DATE = "20260212"

SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70

_kosdaq_set = None

def get_kosdaq_set(date=None):
    global _kosdaq_set
    if _kosdaq_set is None:
        d = date or END_DATE
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(d, market="KOSDAQ"))
    return _kosdaq_set

def code_to_ticker(code):
    return f"{code}{'.KQ' if code in get_kosdaq_set() else '.KS'}"


@dataclass
class Trade:
    code: str
    name: str
    method: str
    date: str
    entry_time: str
    entry_price: float
    cap_bil: float = 0.0
    exit_time: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    market: str = ""


def get_trading_days(end_date, n_days=20):
    """최근 n 거래일 추출"""
    # 넉넉하게 40일치 가져와서 거래일 필터
    from datetime import timedelta
    end = pd.Timestamp(end_date)
    start = end - timedelta(days=60)
    start_str = start.strftime("%Y%m%d")

    df = pykrx_stock.get_market_ohlcv_by_date(start_str, end_date, "005930")  # 삼성전자
    dates = [d.strftime("%Y%m%d") for d in df.index]
    return dates[-n_days:]


def fetch_daily_data(dates):
    """각 날짜별 OHLCV + 시가총액 + 유니버스 수집"""
    print("=" * 65)
    print("  1. 일별 데이터 수집")
    print("=" * 65)

    daily_info = {}
    all_codes = set()

    for i, date in enumerate(dates):
        df_ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(date, market="ALL")
        df_ohlcv = df_ohlcv[df_ohlcv["거래량"] > 0]

        df_cap = pykrx_stock.get_market_cap_by_ticker(date, market="ALL")

        # 합치기
        if "시가총액" in df_ohlcv.columns:
            df = df_ohlcv.copy()
            df["시가총액"] = df_cap["시가총액"]
        else:
            df = df_ohlcv.join(df_cap[["시가총액"]], how="left")
        df["시가총액_억"] = df["시가총액"] / 1e8

        # 유니버스
        top100 = set(df.nlargest(100, "거래대금").index.tolist())
        strong = set(df[df["등락률"] >= 3.0].index.tolist())
        universe = top100 | strong

        # 시총 5000억+ 필터
        cap5000 = set(df[df["시가총액_억"] >= 5000].index.tolist())

        daily_info[date] = {
            "df": df,
            "universe": universe,
            "cap5000": cap5000,
        }
        all_codes |= universe

        print(f"    {date}: 유니버스 {len(universe)}개, 시총5000억+ {len(cap5000 & universe)}개")
        time.sleep(0.3)

    print(f"\n  전체 유니크 코드: {len(all_codes)}개")
    return daily_info, all_codes


def fetch_5min_bulk(codes, dates):
    """5분봉 일괄 수집"""
    print("\n" + "=" * 65)
    print("  2. 5분봉 일괄 수집")
    print("=" * 65)

    bars_all = {}  # {code: {date_str: df}}
    failed = 0
    batch_size = 20
    code_list = list(codes)

    # 날짜 범위
    date_set = set()
    for d in dates:
        date_set.add(pd.Timestamp(d).date())

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

                    # 날짜별로 분리
                    bars_all[code] = {}
                    for d in date_set:
                        day = df[df.index.date == d]
                        if len(day) >= 10:
                            d_str = d.strftime("%Y%m%d")
                            bars_all[code][d_str] = day
                except Exception:
                    failed += 1
        except Exception:
            failed += len(batch)

        done = bs + len(batch)
        if (done // batch_size) % 10 == 0 and done > 0:
            print(f"    {done}/{len(code_list)}...")

    total_bars = sum(len(v) for v in bars_all.values())
    print(f"  완료: {len(bars_all)}개 종목, {total_bars}개 일별 데이터, {failed}개 실패")
    return bars_all


def select_leaders(bars_all, date, eligible_codes):
    """해당 날짜의 9:00~9:30 모멘텀 TOP20"""
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
    return [s["code"] for s in scores[:20]]


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


def simulate(bars, entry, method, code, name, date, cap, market):
    ep, et = entry["price"], entry["time"]
    after = bars[bars.index > et]
    trade = Trade(code=code, name=name, method=method, date=date,
                  entry_time=str(et)[:16], entry_price=ep,
                  cap_bil=cap, market=market)

    for ts, bar in after.iterrows():
        lo = (bar["Low"] / ep) - 1
        hi = (bar["High"] / ep) - 1
        if lo <= SL_PCT:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = ep * (1 + SL_PCT)
            trade.pnl_pct = SL_PCT * 100
            trade.exit_reason = "손절"
            return trade
        if hi >= TP_PCT:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = ep * (1 + TP_PCT * TP_PARTIAL)
            trade.pnl_pct = TP_PCT * TP_PARTIAL * 100
            trade.exit_reason = "익절"
            return trade

    if len(after) > 0:
        last = after.iloc[-1]
        trade.exit_time = str(after.index[-1])[:16]
        trade.exit_price = last["Close"]
        trade.pnl_pct = ((last["Close"] / ep) - 1) * 100
        trade.exit_reason = "장마감"
    return trade


def run_one_day(bars_all, daily_info, date, use_cap_filter):
    """특정 날짜에 전략 실행"""
    info = daily_info[date]
    df = info["df"]
    universe = info["universe"]

    if use_cap_filter:
        eligible = universe & info["cap5000"]
    else:
        eligible = universe

    leaders = select_leaders(bars_all, date, eligible)
    if not leaders:
        return []

    trades = []
    traded = set()

    # 돌파
    for code in leaders:
        if code in traded or code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        entry = find_breakout(bars)
        if entry:
            name = pykrx_stock.get_market_ticker_name(code) or code
            cap = df.loc[code, "시가총액_억"] if code in df.index else 0
            mkt = "KQ" if code in get_kosdaq_set() else "KS"
            trade = simulate(bars, entry, "돌파", code, name, date, cap, mkt)
            trades.append(trade)
            traded.add(code)

    # 눌림
    for code in leaders:
        if code in traded or code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        entry = find_pullback(bars)
        if entry:
            name = pykrx_stock.get_market_ticker_name(code) or code
            cap = df.loc[code, "시가총액_억"] if code in df.index else 0
            mkt = "KQ" if code in get_kosdaq_set() else "KS"
            trade = simulate(bars, entry, "눌림", code, name, date, cap, mkt)
            trades.append(trade)
            traded.add(code)

    return trades


def print_summary(all_trades, label):
    """전체 요약"""
    print(f"\n{'━'*65}")
    print(f"  {label}")
    print(f"{'━'*65}")

    if not all_trades:
        print("  매매 없음")
        return

    total = len(all_trades)
    wins = sum(1 for t in all_trades if t.pnl_pct > 0)
    losses = total - wins
    total_pnl = sum(t.pnl_pct for t in all_trades)
    avg_pnl = total_pnl / total
    wr = wins / total * 100

    print(f"  전체: {total}건 | {wins}W {losses}L | WR {wr:.1f}% | "
          f"합계 {total_pnl:+.2f}% | 평균 {avg_pnl:+.2f}%")

    # 방법별
    for m in ["돌파", "눌림"]:
        ts = [t for t in all_trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl_pct > 0)
            mp = sum(t.pnl_pct for t in ts)
            ma = mp / len(ts)
            print(f"  {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | "
                  f"WR {mw/len(ts)*100:.1f}% | 합계 {mp:+.2f}% | 평균 {ma:+.2f}%")

    # 시장별
    for mkt in ["KS", "KQ"]:
        ts = [t for t in all_trades if t.market == mkt]
        if ts:
            mw = sum(1 for t in ts if t.pnl_pct > 0)
            mp = sum(t.pnl_pct for t in ts)
            mkt_name = "코스피" if mkt == "KS" else "코스닥"
            print(f"  {mkt_name}: {len(ts)}건 | {mw}W {len(ts)-mw}L | "
                  f"WR {mw/len(ts)*100:.1f}% | 합계 {mp:+.2f}%")

    # 날짜별
    dates = sorted(set(t.date for t in all_trades))
    print(f"\n  날짜별:")
    print(f"  {'날짜':10s} {'건수':>4s} {'W':>3s} {'L':>3s} {'WR':>5s} {'합계':>8s}")
    print(f"  {'─'*40}")
    for d in dates:
        ts = [t for t in all_trades if t.date == d]
        dw = sum(1 for t in ts if t.pnl_pct > 0)
        dp = sum(t.pnl_pct for t in ts)
        d_fmt = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        print(f"  {d_fmt:10s} {len(ts):4d} {dw:3d} {len(ts)-dw:3d} "
              f"{dw/len(ts)*100:4.0f}% {dp:+8.2f}%")

    # 청산 사유별
    print(f"\n  청산 사유별:")
    for reason in ["익절", "손절", "장마감"]:
        ts = [t for t in all_trades if t.exit_reason == reason]
        if ts:
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {reason}: {len(ts)}건 | 합계 {mp:+.2f}% | 평균 {mp/len(ts):+.2f}%")


def main():
    # 거래일
    dates = get_trading_days(END_DATE, 20)
    print(f"  거래일 {len(dates)}일: {dates[0]}~{dates[-1]}")

    # 일별 데이터
    daily_info, all_codes = fetch_daily_data(dates)

    # 5분봉 수집
    bars_all = fetch_5min_bulk(all_codes, dates)

    # === 전략 실행 ===
    print("\n" + "=" * 65)
    print("  3. 전략 실행 (20일)")
    print("=" * 65)

    trades_nofilter = []
    trades_cap5000 = []

    for date in dates:
        t1 = run_one_day(bars_all, daily_info, date, use_cap_filter=False)
        t2 = run_one_day(bars_all, daily_info, date, use_cap_filter=True)
        trades_nofilter.extend(t1)
        trades_cap5000.extend(t2)
        d_fmt = f"{date[4:6]}/{date[6:]}"
        print(f"    {d_fmt}: 무필터 {len(t1)}건 | 5000억+ {len(t2)}건")

    # === 결과 ===
    print("\n" + "=" * 65)
    print("  4. 결과 비교 (20일)")
    print("=" * 65)

    print_summary(trades_nofilter, "A) 무필터 (현재)")
    print_summary(trades_cap5000, "B) 시총 5000억+ 필터")

    # 최종 비교 테이블
    print("\n" + "=" * 65)
    print("  5. 최종 비교")
    print("=" * 65)

    for label, trades in [("무필터", trades_nofilter), ("시총5000억+", trades_cap5000)]:
        if trades:
            total = len(trades)
            wins = sum(1 for t in trades if t.pnl_pct > 0)
            pnl = sum(t.pnl_pct for t in trades)
            avg = pnl / total

            dolpa = [t for t in trades if t.method == "돌파"]
            d_w = sum(1 for t in dolpa if t.pnl_pct > 0)
            d_pnl = sum(t.pnl_pct for t in dolpa)

            nullim = [t for t in trades if t.method == "눌림"]
            n_w = sum(1 for t in nullim if t.pnl_pct > 0)
            n_pnl = sum(t.pnl_pct for t in nullim)

            print(f"\n  [{label}]")
            print(f"    전체: {total}건 | {wins}W {total-wins}L | WR {wins/total*100:.1f}% | "
                  f"합계 {pnl:+.2f}% | 평균 {avg:+.2f}%")
            if dolpa:
                print(f"    돌파: {len(dolpa)}건 | {d_w}W {len(dolpa)-d_w}L | "
                      f"WR {d_w/len(dolpa)*100:.1f}% | {d_pnl:+.2f}%")
            if nullim:
                print(f"    눌림: {len(nullim)}건 | {n_w}W {len(nullim)-n_w}L | "
                      f"WR {n_w/len(nullim)*100:.1f}% | {n_pnl:+.2f}%")


if __name__ == "__main__":
    main()
