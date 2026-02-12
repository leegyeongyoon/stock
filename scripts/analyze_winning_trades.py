"""
승리 거래 vs 패배 거래 특성 분석

목표: +96% 백테스트에서 실제로 수익을 낸 거래들의 공통점 찾기
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from dataclasses import dataclass, asdict
import time
from collections import defaultdict

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
    # 추가 분석 필드
    market_cap: float = 0.0  # 시가총액 (억)
    inst_buy: float = 0.0    # 기관순매수 (억)
    daily_change: float = 0.0  # 당일 등락률
    morning_vol_rank: int = 0  # 오전 거래량 순위
    leader_rank: int = 0       # 리더 순위
    entry_hour: int = 0        # 진입 시간
    sector: str = ""           # 업종


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


def find_pullback_95(bars, vol_median):
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


def simulate_trade(bars, entry_price, entry_idx):
    for i in range(entry_idx + 1, len(bars)):
        bar = bars.iloc[i]
        lo_pct = (bar["Low"] / entry_price) - 1
        hi_pct = (bar["High"] / entry_price) - 1

        if lo_pct <= SL_PCT:
            return SL_PCT * 100, "손절", bars.index[i]
        if hi_pct >= TP_PCT:
            return TP_PCT * 100 * TP_PARTIAL, "1차익절", bars.index[i]

    last = bars.iloc[-1]
    pnl = ((last["Close"] / entry_price) - 1) * 100
    return pnl, "장마감", bars.index[-1]


def run_backtest(bars_all, daily_info, dates, prev_dates):
    all_trades = []

    for i, date in enumerate(dates):
        prev_date = prev_dates[i]
        info = daily_info[date]
        df = info["df"]
        universe = info["universe"]
        cap5000 = info["cap5000"]
        prev_df = daily_info[prev_date]["df"] if prev_date in daily_info else None

        # 3대 필터
        eligible = universe & cap5000
        if prev_df is not None:
            inst_range = set(prev_df[
                (prev_df["기관순매수"] >= 50) & (prev_df["기관순매수"] <= 200)
            ].index.tolist())
            eligible = eligible & inst_range

        leaders = select_leaders(bars_all, date, eligible)
        leader_codes = [s["code"] for s in leaders]
        vol_median = get_morning_vol_median(bars_all, date, leader_codes)

        for rank, s in enumerate(leaders[:10], 1):
            code = s["code"]
            if code not in bars_all or date not in bars_all[code]:
                continue
            bars = bars_all[code][date]

            # 돌파매매
            entry = find_breakout(bars)
            if entry:
                entry_idx = bars.index.get_loc(entry["time"])
                pnl, reason, exit_time = simulate_trade(bars, entry["price"], entry_idx)

                # 추가 정보 수집
                market_cap = df.loc[code, "시가총액_억"] if code in df.index else 0
                inst_buy = prev_df.loc[code, "기관순매수"] if prev_df is not None and code in prev_df.index else 0
                daily_change = df.loc[code, "등락률"] if code in df.index else 0

                trade = Trade(
                    code=code,
                    name=pykrx_stock.get_market_ticker_name(code) or code,
                    method="돌파",
                    date=date,
                    entry_time=str(entry["time"])[:16],
                    entry_price=entry["price"],
                    exit_time=str(exit_time)[:16],
                    exit_price=entry["price"] * (1 + pnl/100),
                    pnl_pct=pnl,
                    exit_reason=reason,
                    market_cap=market_cap,
                    inst_buy=inst_buy,
                    daily_change=daily_change,
                    leader_rank=rank,
                    entry_hour=entry["time"].hour,
                )
                all_trades.append(trade)

            # 눌림매매
            entry = find_pullback_95(bars, vol_median)
            if entry:
                entry_idx = bars.index.get_loc(entry["time"])
                pnl, reason, exit_time = simulate_trade(bars, entry["price"], entry_idx)

                market_cap = df.loc[code, "시가총액_억"] if code in df.index else 0
                inst_buy = prev_df.loc[code, "기관순매수"] if prev_df is not None and code in prev_df.index else 0
                daily_change = df.loc[code, "등락률"] if code in df.index else 0

                trade = Trade(
                    code=code,
                    name=pykrx_stock.get_market_ticker_name(code) or code,
                    method="눌림",
                    date=date,
                    entry_time=str(entry["time"])[:16],
                    entry_price=entry["price"],
                    exit_time=str(exit_time)[:16],
                    exit_price=entry["price"] * (1 + pnl/100),
                    pnl_pct=pnl,
                    exit_reason=reason,
                    market_cap=market_cap,
                    inst_buy=inst_buy,
                    daily_change=daily_change,
                    leader_rank=rank,
                    entry_hour=entry["time"].hour,
                )
                all_trades.append(trade)

    return all_trades


def analyze_trades(trades):
    print("\n" + "=" * 65)
    print("  3. 승리 거래 vs 패배 거래 분석")
    print("=" * 65)

    df = pd.DataFrame([asdict(t) for t in trades])
    df["is_win"] = df["pnl_pct"] > 0

    wins = df[df["is_win"]]
    losses = df[~df["is_win"]]

    print(f"\n  전체: {len(df)}건, 승: {len(wins)}건, 패: {len(losses)}건")
    print(f"  총 수익률: {df['pnl_pct'].sum():.2f}%")
    print(f"  승률: {len(wins)/len(df)*100:.1f}%")

    print("\n  === 시가총액 분석 ===")
    for label, cap_min, cap_max in [
        ("5000~1만억", 5000, 10000),
        ("1만~3만억", 10000, 30000),
        ("3만~10만억", 30000, 100000),
        ("10만억+", 100000, float("inf")),
    ]:
        subset = df[(df["market_cap"] >= cap_min) & (df["market_cap"] < cap_max)]
        if len(subset) > 0:
            wr = (subset["pnl_pct"] > 0).mean() * 100
            total = subset["pnl_pct"].sum()
            print(f"    {label}: {len(subset)}건, WR {wr:.1f}%, 합계 {total:+.2f}%")

    print("\n  === 기관순매수 분석 ===")
    for label, inst_min, inst_max in [
        ("50~80억", 50, 80),
        ("80~120억", 80, 120),
        ("120~150억", 120, 150),
        ("150~200억", 150, 200),
    ]:
        subset = df[(df["inst_buy"] >= inst_min) & (df["inst_buy"] < inst_max)]
        if len(subset) > 0:
            wr = (subset["pnl_pct"] > 0).mean() * 100
            total = subset["pnl_pct"].sum()
            print(f"    {label}: {len(subset)}건, WR {wr:.1f}%, 합계 {total:+.2f}%")

    print("\n  === 리더 순위 분석 ===")
    for rank in range(1, 11):
        subset = df[df["leader_rank"] == rank]
        if len(subset) > 0:
            wr = (subset["pnl_pct"] > 0).mean() * 100
            total = subset["pnl_pct"].sum()
            avg = subset["pnl_pct"].mean()
            print(f"    TOP{rank}: {len(subset)}건, WR {wr:.1f}%, 합계 {total:+.2f}%, 평균 {avg:+.2f}%")

    print("\n  === 진입 시간 분석 ===")
    for hour in range(9, 16):
        subset = df[df["entry_hour"] == hour]
        if len(subset) > 0:
            wr = (subset["pnl_pct"] > 0).mean() * 100
            total = subset["pnl_pct"].sum()
            print(f"    {hour}시: {len(subset)}건, WR {wr:.1f}%, 합계 {total:+.2f}%")

    print("\n  === 당일 등락률 분석 ===")
    for label, chg_min, chg_max in [
        ("0~3%", 0, 3),
        ("3~6%", 3, 6),
        ("6~10%", 6, 10),
        ("10~15%", 10, 15),
        ("15%+", 15, 100),
    ]:
        subset = df[(df["daily_change"] >= chg_min) & (df["daily_change"] < chg_max)]
        if len(subset) > 0:
            wr = (subset["pnl_pct"] > 0).mean() * 100
            total = subset["pnl_pct"].sum()
            print(f"    {label}: {len(subset)}건, WR {wr:.1f}%, 합계 {total:+.2f}%")

    print("\n  === 매매 방법 분석 ===")
    for method in ["돌파", "눌림"]:
        subset = df[df["method"] == method]
        if len(subset) > 0:
            wr = (subset["pnl_pct"] > 0).mean() * 100
            total = subset["pnl_pct"].sum()
            avg = subset["pnl_pct"].mean()
            print(f"    {method}: {len(subset)}건, WR {wr:.1f}%, 합계 {total:+.2f}%, 평균 {avg:+.2f}%")

    # 최고 성과 거래들
    print("\n  === TOP 10 수익 거래 ===")
    top10 = df.nlargest(10, "pnl_pct")
    for _, t in top10.iterrows():
        print(f"    {t['date']} {t['name']}: {t['pnl_pct']:+.2f}% | "
              f"시총{t['market_cap']:.0f}억, 기관{t['inst_buy']:.0f}억, TOP{t['leader_rank']}")

    print("\n  === WORST 10 손실 거래 ===")
    worst10 = df.nsmallest(10, "pnl_pct")
    for _, t in worst10.iterrows():
        print(f"    {t['date']} {t['name']}: {t['pnl_pct']:+.2f}% | "
              f"시총{t['market_cap']:.0f}억, 기관{t['inst_buy']:.0f}억, TOP{t['leader_rank']}")

    return df


def main():
    print("=" * 65)
    print("  승리 거래 특성 분석")
    print("=" * 65)

    dates_all = get_trading_days(END_DATE, 20)
    prev_dates = dates_all[:-1]
    trade_dates = dates_all[1:]
    print(f"\n  분석 기간: {trade_dates[0]}~{trade_dates[-1]} ({len(trade_dates)}일)")

    daily_info, all_codes = fetch_daily_data(dates_all)
    bars_all = fetch_5min_bulk(all_codes, trade_dates)

    trades = run_backtest(bars_all, daily_info, trade_dates, prev_dates)
    df = analyze_trades(trades)

    # 추천 필터 도출
    print("\n" + "=" * 65)
    print("  4. 추천 필터")
    print("=" * 65)

    # 최적 조합 찾기
    best_combos = []
    for top_n in [1, 2, 3, 5]:
        for cap_min in [5000, 10000, 30000]:
            for inst_min, inst_max in [(50, 200), (80, 200), (100, 200)]:
                subset = df[
                    (df["leader_rank"] <= top_n) &
                    (df["market_cap"] >= cap_min) &
                    (df["inst_buy"] >= inst_min) &
                    (df["inst_buy"] <= inst_max)
                ]
                if len(subset) >= 5:
                    wr = (subset["pnl_pct"] > 0).mean() * 100
                    total = subset["pnl_pct"].sum()
                    avg = subset["pnl_pct"].mean()
                    best_combos.append({
                        "top_n": top_n,
                        "cap_min": cap_min,
                        "inst_min": inst_min,
                        "inst_max": inst_max,
                        "trades": len(subset),
                        "wr": wr,
                        "total": total,
                        "avg": avg,
                    })

    best_combos.sort(key=lambda x: x["total"], reverse=True)
    print("\n  수익률 합계 TOP 10 조합:")
    for c in best_combos[:10]:
        print(f"    TOP{c['top_n']}, 시총{c['cap_min']}억+, 기관{c['inst_min']}~{c['inst_max']}억: "
              f"{c['trades']}건, WR {c['wr']:.1f}%, 합계 {c['total']:+.2f}%, 평균 {c['avg']:+.2f}%")

    best_combos.sort(key=lambda x: x["avg"], reverse=True)
    print("\n  건당 평균 수익 TOP 10 조합:")
    for c in best_combos[:10]:
        print(f"    TOP{c['top_n']}, 시총{c['cap_min']}억+, 기관{c['inst_min']}~{c['inst_max']}억: "
              f"{c['trades']}건, WR {c['wr']:.1f}%, 합계 {c['total']:+.2f}%, 평균 {c['avg']:+.2f}%")


if __name__ == "__main__":
    main()
