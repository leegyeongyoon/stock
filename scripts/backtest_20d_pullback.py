"""
20일 백테스트: 눌림매매 조건 개선

기본 필터: 시총 5000억+ & 전일 기관 50~200억
돌파는 동일, 눌림만 조건 변경하여 비교:

  A) 기존 눌림: 오전고점 98% + 반등 + Close > 50%되돌림
  B) 깊이 95%: 오전고점 95%까지 눌림 허용 (더 깊은 눌림만)
  C) 깊이 93%: 오전고점 93%까지
  D) 오전 거래량 조건: 기존 + 오전 거래량 상위 50% 종목만
  E) 깊이 95% + 오전 거래량: B+D 조합
  F) 깊이 93% + 오전 거래량: C+D 조합
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from dataclasses import dataclass
import time

END_DATE = "20260212"

SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70

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
    code: str
    name: str
    method: str
    date: str
    entry_time: str
    entry_price: float
    exit_time: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    market: str = ""


def get_trading_days(end_date, n_days=20):
    from datetime import timedelta
    end = pd.Timestamp(end_date)
    start = end - timedelta(days=60)
    df = pykrx_stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end_date, "005930")
    dates = [d.strftime("%Y%m%d") for d in df.index]
    return dates[-(n_days + 1):]


def fetch_daily_data(dates):
    print("=" * 65)
    print("  1. 일별 데이터 수집")
    print("=" * 65)

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
        cap5000 = set(df[df["시가총액_억"] >= 5000].index.tolist())

        daily_info[date] = {"df": df, "universe": universe, "cap5000": cap5000}
        all_codes |= universe
        print(f"    {date}: {len(universe)}개")
        time.sleep(0.3)

    print(f"  유니크 코드: {len(all_codes)}개")
    return daily_info, all_codes


def fetch_5min_bulk(codes, dates):
    print("\n" + "=" * 65)
    print("  2. 5분봉 수집")
    print("=" * 65)

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
    print(f"  완료: {len(bars_all)}개 종목, {total_bars}개 일별, {failed}개 실패")
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
                return {"price": bar["Close"], "time": window.index[i]}
    return None


def find_pullback(bars, depth_pct=0.98, require_vol=False, vol_threshold=0):
    """눌림매매

    Args:
        depth_pct: 오전고점 대비 눌림 비율 (0.98=2%눌림, 0.95=5%눌림, 0.93=7%눌림)
        require_vol: 오전 거래량 조건 사용 여부
        vol_threshold: 오전 거래량 최소값
    """
    # 오전 거래량 체크
    if require_vol:
        morning_full = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
        if morning_full.empty:
            return None
        morning_vol = morning_full["Volume"].sum()
        if morning_vol < vol_threshold:
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
        if (prev["Low"] <= mh * depth_pct and
            bar["Close"] > prev["Close"] and
            bar["Close"] > r50 and
            bar["Low"] > ml):
            return {"price": bar["Close"], "time": window.index[i]}
    return None


def simulate(bars, entry, method, code, name, date, market):
    ep, et = entry["price"], entry["time"]
    after = bars[bars.index > et]
    trade = Trade(code=code, name=name, method=method, date=date,
                  entry_time=str(et)[:16], entry_price=ep, market=market)
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


def get_morning_vol_median(bars_all, date, leader_codes):
    """해당 날짜 리더 종목들의 오전 거래량 중위값"""
    vols = []
    for code in leader_codes:
        if code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        morning = bars[(bars.index.hour >= 9) & (bars.index.hour < 12)]
        if not morning.empty:
            vols.append(morning["Volume"].sum())
    return np.median(vols) if vols else 0


def run_one_day(bars_all, daily_info, date, prev_date, pullback_fn):
    info = daily_info[date]
    df = info["df"]
    universe = info["universe"]
    cap5000 = info["cap5000"]

    prev_df = daily_info[prev_date]["df"] if prev_date in daily_info else None
    eligible = universe & cap5000
    if prev_df is not None:
        inst_range = set(prev_df[
            (prev_df["기관순매수"] >= 50) & (prev_df["기관순매수"] <= 200)
        ].index.tolist())
        eligible = eligible & inst_range

    leaders = select_leaders(bars_all, date, eligible)
    leader_codes = [s["code"] for s in leaders]
    if not leader_codes:
        return []

    trades = []
    traded = set()

    # 돌파 (동일)
    for code in leader_codes:
        if code in traded or code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        entry = find_breakout(bars)
        if entry:
            name = pykrx_stock.get_market_ticker_name(code) or code
            mkt = "KQ" if code in get_kosdaq_set() else "KS"
            trade = simulate(bars, entry, "돌파", code, name, date, mkt)
            trades.append(trade)
            traded.add(code)

    # 눌림 (pullback_fn으로 다양한 조건 테스트)
    vol_median = get_morning_vol_median(bars_all, date, leader_codes)

    for code in leader_codes:
        if code in traded or code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        entry = pullback_fn(bars, vol_median)
        if entry:
            name = pykrx_stock.get_market_ticker_name(code) or code
            mkt = "KQ" if code in get_kosdaq_set() else "KS"
            trade = simulate(bars, entry, "눌림", code, name, date, mkt)
            trades.append(trade)
            traded.add(code)

    return trades


def print_summary(trades, label):
    print(f"\n{'━'*65}")
    print(f"  {label}")
    print(f"{'━'*65}")
    if not trades:
        print("  매매 없음")
        return

    total = len(trades)
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    pnl = sum(t.pnl_pct for t in trades)

    print(f"  전체: {total}건 | {wins}W {total-wins}L | WR {wins/total*100:.1f}% | "
          f"합계 {pnl:+.2f}% | 평균 {pnl/total:+.2f}%")

    for m in ["돌파", "눌림"]:
        ts = [t for t in trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl_pct > 0)
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | "
                  f"WR {mw/len(ts)*100:.1f}% | {mp:+.2f}%")

    for reason in ["익절", "손절", "장마감"]:
        ts = [t for t in trades if t.exit_reason == reason]
        if ts:
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {reason}: {len(ts)}건 | {mp:+.2f}%")


def main():
    dates_all = get_trading_days(END_DATE, 20)
    prev_dates = dates_all[:-1]
    trade_dates = dates_all[1:]
    print(f"  매매일 {len(trade_dates)}일: {trade_dates[0]}~{trade_dates[-1]}")

    daily_info, all_codes = fetch_daily_data(dates_all)
    bars_all = fetch_5min_bulk(all_codes, trade_dates)

    # 눌림 조건별 함수 정의
    pullback_configs = [
        ("A) 기존 (98%눌림)", lambda bars, vm: find_pullback(bars, depth_pct=0.98)),
        ("B) 95%눌림 (5%하락)", lambda bars, vm: find_pullback(bars, depth_pct=0.95)),
        ("C) 93%눌림 (7%하락)", lambda bars, vm: find_pullback(bars, depth_pct=0.93)),
        ("D) 기존 + 오전거래량", lambda bars, vm: find_pullback(bars, depth_pct=0.98, require_vol=True, vol_threshold=vm)),
        ("E) 95% + 오전거래량", lambda bars, vm: find_pullback(bars, depth_pct=0.95, require_vol=True, vol_threshold=vm)),
        ("F) 93% + 오전거래량", lambda bars, vm: find_pullback(bars, depth_pct=0.93, require_vol=True, vol_threshold=vm)),
    ]

    print("\n" + "=" * 65)
    print("  3. 눌림 조건별 백테스트 (기본: 시총5000억+기관50~200억)")
    print("=" * 65)

    results = {}
    for plabel, pfn in pullback_configs:
        all_trades = []
        for i, date in enumerate(trade_dates):
            prev_date = prev_dates[i]
            trades = run_one_day(bars_all, daily_info, date, prev_date, pfn)
            all_trades.extend(trades)
        results[plabel] = all_trades
        print_summary(all_trades, plabel)

    # 최종 비교 테이블
    print("\n" + "=" * 65)
    print("  4. 눌림 조건 비교 (눌림만)")
    print("=" * 65)
    print(f"  {'조건':25s} {'건':>4s} {'W':>4s} {'L':>4s} {'WR':>6s} {'합계':>9s} {'평균':>7s}")
    print(f"  {'─'*60}")

    for plabel, _ in pullback_configs:
        trades = results[plabel]
        nullim = [t for t in trades if t.method == "눌림"]
        if nullim:
            nw = sum(1 for t in nullim if t.pnl_pct > 0)
            np_ = sum(t.pnl_pct for t in nullim)
            print(f"  {plabel:25s} {len(nullim):4d} {nw:4d} {len(nullim)-nw:4d} "
                  f"{nw/len(nullim)*100:5.1f}% {np_:+9.2f}% {np_/len(nullim):+6.2f}%")
        else:
            print(f"  {plabel:25s}    0    -    -     -      0.00%  0.00%")

    # 전체 (돌파+눌림) 비교
    print(f"\n  전체 (돌파+눌림) 비교:")
    print(f"  {'조건':25s} {'건':>4s} {'W':>4s} {'L':>4s} {'WR':>6s} {'합계':>9s}")
    print(f"  {'─'*55}")
    for plabel, _ in pullback_configs:
        trades = results[plabel]
        if trades:
            tw = sum(1 for t in trades if t.pnl_pct > 0)
            tp = sum(t.pnl_pct for t in trades)
            print(f"  {plabel:25s} {len(trades):4d} {tw:4d} {len(trades)-tw:4d} "
                  f"{tw/len(trades)*100:5.1f}% {tp:+9.2f}%")


if __name__ == "__main__":
    main()
