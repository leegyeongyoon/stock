"""
20일 백테스트: 시총 5000억+ + 기관수급 필터 조합

필터 조합:
  A) 시총 5000억+ (기준)
  B) 시총 5000억+ + 전일 기관 순매수 > 0
  C) 시총 5000억+ + 전일 기관 순매수 50억+
  D) 시총 5000억+ + 전일 기관 순매수 50~200억
  E) 시총 5000억+ + 전일 기관+외국인 동시 순매수

기관 데이터: 전일 기준 (실전에서 장전에 확인 가능)
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
    cap_bil: float = 0.0
    inst_prev: float = 0.0
    exit_time: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    market: str = ""


def get_trading_days(end_date, n_days=20):
    from datetime import timedelta
    end = pd.Timestamp(end_date)
    start = end - timedelta(days=60)
    start_str = start.strftime("%Y%m%d")
    df = pykrx_stock.get_market_ohlcv_by_date(start_str, end_date, "005930")
    dates = [d.strftime("%Y%m%d") for d in df.index]
    return dates[-(n_days + 1):]  # +1일 (전일 기관 데이터용)


def fetch_daily_data(dates):
    """각 날짜별 OHLCV + 시가총액 + 기관순매수"""
    print("=" * 65)
    print("  1. 일별 데이터 수집 (OHLCV + 시총 + 기관수급)")
    print("=" * 65)

    daily_info = {}
    all_codes = set()

    for i, date in enumerate(dates):
        # OHLCV + 시가총액
        df_ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(date, market="ALL")
        df_ohlcv = df_ohlcv[df_ohlcv["거래량"] > 0]

        df_cap = pykrx_stock.get_market_cap_by_ticker(date, market="ALL")

        if "시가총액" in df_ohlcv.columns:
            df = df_ohlcv.copy()
            df["시가총액"] = df_cap["시가총액"]
        else:
            df = df_ohlcv.join(df_cap[["시가총액"]], how="left")
        df["시가총액_억"] = df["시가총액"] / 1e8

        # 기관 순매수
        try:
            df_inst = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                date, date, market="KOSPI", investor="기관합계")
            df_inst_kq = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                date, date, market="KOSDAQ", investor="기관합계")
            inst_all = pd.concat([df_inst, df_inst_kq])
            df["기관순매수"] = inst_all["순매수거래대금"] / 1e8  # 억원
        except Exception:
            df["기관순매수"] = 0

        # 외국인 순매수
        try:
            df_for = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                date, date, market="KOSPI", investor="외국인합계")
            df_for_kq = pykrx_stock.get_market_net_purchases_of_equities_by_ticker(
                date, date, market="KOSDAQ", investor="외국인합계")
            for_all = pd.concat([df_for, df_for_kq])
            df["외국인순매수"] = for_all["순매수거래대금"] / 1e8
        except Exception:
            df["외국인순매수"] = 0

        # 유니버스
        top100 = set(df.nlargest(100, "거래대금").index.tolist())
        strong = set(df[df["등락률"] >= 3.0].index.tolist())
        universe = top100 | strong
        cap5000 = set(df[df["시가총액_억"] >= 5000].index.tolist())

        daily_info[date] = {
            "df": df,
            "universe": universe,
            "cap5000": cap5000,
        }
        all_codes |= universe

        inst_pos = df[(df.index.isin(universe & cap5000)) & (df["기관순매수"] > 0)]
        print(f"    {date}: 유니버스 {len(universe)}개, "
              f"5000억+ {len(cap5000 & universe)}개, "
              f"기관+ {len(inst_pos)}개")
        time.sleep(0.3)

    print(f"\n  전체 유니크 코드: {len(all_codes)}개")
    return daily_info, all_codes


def fetch_5min_bulk(codes, dates):
    """5분봉 일괄 수집"""
    print("\n" + "=" * 65)
    print("  2. 5분봉 일괄 수집")
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
    """모멘텀 TOP20"""
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


def simulate(bars, entry, method, code, name, date, cap, inst, market):
    ep, et = entry["price"], entry["time"]
    after = bars[bars.index > et]
    trade = Trade(code=code, name=name, method=method, date=date,
                  entry_time=str(et)[:16], entry_price=ep,
                  cap_bil=cap, inst_prev=inst, market=market)

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


def run_one_day(bars_all, daily_info, date, prev_date, filter_type):
    """특정 날짜 전략 실행"""
    info = daily_info[date]
    df = info["df"]
    universe = info["universe"]
    cap5000 = info["cap5000"]

    # 전일 기관 데이터
    prev_df = daily_info[prev_date]["df"] if prev_date in daily_info else None

    # 시총 5000억+ 기본
    eligible = universe & cap5000

    # 기관 필터 적용 (전일 기준)
    if prev_df is not None and filter_type != "cap_only":
        if filter_type == "inst_pos":
            # 전일 기관 순매수 > 0
            inst_pos = set(prev_df[prev_df["기관순매수"] > 0].index.tolist())
            eligible = eligible & inst_pos
        elif filter_type == "inst_50":
            # 전일 기관 순매수 50억+
            inst_50 = set(prev_df[prev_df["기관순매수"] >= 50].index.tolist())
            eligible = eligible & inst_50
        elif filter_type == "inst_50_200":
            # 전일 기관 순매수 50~200억
            inst_range = set(prev_df[
                (prev_df["기관순매수"] >= 50) & (prev_df["기관순매수"] <= 200)
            ].index.tolist())
            eligible = eligible & inst_range
        elif filter_type == "inst_for":
            # 전일 기관+외국인 동시 순매수
            both = set(prev_df[
                (prev_df["기관순매수"] > 0) & (prev_df["외국인순매수"] > 0)
            ].index.tolist())
            eligible = eligible & both

    leaders = select_leaders(bars_all, date, eligible)
    if not leaders:
        return []

    trades = []
    traded = set()

    for code in leaders:
        if code in traded or code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        entry = find_breakout(bars)
        if entry:
            name = pykrx_stock.get_market_ticker_name(code) or code
            cap = df.loc[code, "시가총액_억"] if code in df.index else 0
            inst = prev_df.loc[code, "기관순매수"] if prev_df is not None and code in prev_df.index else 0
            mkt = "KQ" if code in get_kosdaq_set() else "KS"
            trade = simulate(bars, entry, "돌파", code, name, date, cap, inst, mkt)
            trades.append(trade)
            traded.add(code)

    for code in leaders:
        if code in traded or code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        entry = find_pullback(bars)
        if entry:
            name = pykrx_stock.get_market_ticker_name(code) or code
            cap = df.loc[code, "시가총액_억"] if code in df.index else 0
            inst = prev_df.loc[code, "기관순매수"] if prev_df is not None and code in prev_df.index else 0
            mkt = "KQ" if code in get_kosdaq_set() else "KS"
            trade = simulate(bars, entry, "눌림", code, name, date, cap, inst, mkt)
            trades.append(trade)
            traded.add(code)

    return trades


def print_summary(all_trades, label):
    print(f"\n{'━'*65}")
    print(f"  {label}")
    print(f"{'━'*65}")

    if not all_trades:
        print("  매매 없음")
        return

    total = len(all_trades)
    wins = sum(1 for t in all_trades if t.pnl_pct > 0)
    total_pnl = sum(t.pnl_pct for t in all_trades)
    avg_pnl = total_pnl / total
    wr = wins / total * 100

    print(f"  전체: {total}건 | {wins}W {total-wins}L | WR {wr:.1f}% | "
          f"합계 {total_pnl:+.2f}% | 평균 {avg_pnl:+.2f}%")

    for m in ["돌파", "눌림"]:
        ts = [t for t in all_trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl_pct > 0)
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | "
                  f"WR {mw/len(ts)*100:.1f}% | {mp:+.2f}%")

    # 청산 사유
    for reason in ["익절", "손절", "장마감"]:
        ts = [t for t in all_trades if t.exit_reason == reason]
        if ts:
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {reason}: {len(ts)}건 | {mp:+.2f}%")

    # 날짜별
    dates = sorted(set(t.date for t in all_trades))
    print(f"\n  날짜별:")
    print(f"  {'날짜':10s} {'건':>3s} {'W':>3s} {'L':>3s} {'WR':>5s} {'합계':>8s}")
    print(f"  {'─'*38}")
    for d in dates:
        ts = [t for t in all_trades if t.date == d]
        dw = sum(1 for t in ts if t.pnl_pct > 0)
        dp = sum(t.pnl_pct for t in ts)
        d_fmt = f"{d[4:6]}/{d[6:]}"
        print(f"  {d_fmt:10s} {len(ts):3d} {dw:3d} {len(ts)-dw:3d} "
              f"{dw/len(ts)*100:4.0f}% {dp:+8.2f}%")


def main():
    dates_all = get_trading_days(END_DATE, 20)
    # dates_all[0]은 전일 데이터용, dates_all[1:]이 실제 매매일
    prev_dates = dates_all[:-1]
    trade_dates = dates_all[1:]
    print(f"  매매일 {len(trade_dates)}일: {trade_dates[0]}~{trade_dates[-1]}")
    print(f"  (전일 데이터: {dates_all[0]}부터)")

    # 일별 데이터
    daily_info, all_codes = fetch_daily_data(dates_all)

    # 5분봉
    bars_all = fetch_5min_bulk(all_codes, trade_dates)

    # === 전략 실행 ===
    print("\n" + "=" * 65)
    print("  3. 필터별 전략 실행 (20일)")
    print("=" * 65)

    filter_configs = [
        ("cap_only",    "A) 시총 5000억+"),
        ("inst_pos",    "B) 5000억+ + 전일 기관 순매수>0"),
        ("inst_50",     "C) 5000억+ + 전일 기관 50억+"),
        ("inst_50_200", "D) 5000억+ + 전일 기관 50~200억"),
        ("inst_for",    "E) 5000억+ + 전일 기관+외국인 동시"),
    ]

    results = {}

    for ftype, flabel in filter_configs:
        all_trades = []
        for i, date in enumerate(trade_dates):
            prev_date = prev_dates[i]
            trades = run_one_day(bars_all, daily_info, date, prev_date, ftype)
            all_trades.extend(trades)
        results[ftype] = (flabel, all_trades)

    # === 결과 출력 ===
    print("\n" + "=" * 65)
    print("  4. 결과 비교")
    print("=" * 65)

    for ftype, flabel in filter_configs:
        _, trades = results[ftype]
        print_summary(trades, flabel)

    # 최종 비교 테이블
    print("\n" + "=" * 65)
    print("  5. 최종 비교 테이블")
    print("=" * 65)
    print(f"  {'필터':35s} {'건':>4s} {'W':>4s} {'L':>4s} {'WR':>6s} {'합계':>9s} {'평균':>7s}")
    print(f"  {'─'*70}")

    for ftype, flabel in filter_configs:
        _, trades = results[ftype]
        if trades:
            total = len(trades)
            wins = sum(1 for t in trades if t.pnl_pct > 0)
            pnl = sum(t.pnl_pct for t in trades)
            avg = pnl / total
            print(f"  {flabel:35s} {total:4d} {wins:4d} {total-wins:4d} "
                  f"{wins/total*100:5.1f}% {pnl:+9.2f}% {avg:+6.2f}%")
        else:
            print(f"  {flabel:35s}    0    -    -     -      0.00%  0.00%")

    # 돌파만 비교
    print(f"\n  [돌파만]")
    print(f"  {'필터':35s} {'건':>4s} {'W':>4s} {'L':>4s} {'WR':>6s} {'합계':>9s}")
    print(f"  {'─'*65}")
    for ftype, flabel in filter_configs:
        _, trades = results[ftype]
        dolpa = [t for t in trades if t.method == "돌파"]
        if dolpa:
            dw = sum(1 for t in dolpa if t.pnl_pct > 0)
            dp = sum(t.pnl_pct for t in dolpa)
            print(f"  {flabel:35s} {len(dolpa):4d} {dw:4d} {len(dolpa)-dw:4d} "
                  f"{dw/len(dolpa)*100:5.1f}% {dp:+9.2f}%")

    # 눌림만 비교
    print(f"\n  [눌림만]")
    print(f"  {'필터':35s} {'건':>4s} {'W':>4s} {'L':>4s} {'WR':>6s} {'합계':>9s}")
    print(f"  {'─'*65}")
    for ftype, flabel in filter_configs:
        _, trades = results[ftype]
        nullim = [t for t in trades if t.method == "눌림"]
        if nullim:
            nw = sum(1 for t in nullim if t.pnl_pct > 0)
            np_ = sum(t.pnl_pct for t in nullim)
            print(f"  {flabel:35s} {len(nullim):4d} {nw:4d} {len(nullim)-nw:4d} "
                  f"{nw/len(nullim)*100:5.1f}% {np_:+9.2f}%")


if __name__ == "__main__":
    main()
