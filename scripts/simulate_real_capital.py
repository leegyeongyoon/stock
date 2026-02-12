"""
1000만원 실투자 시뮬레이션 (20일)

백테스트의 +96.83%는 개별 거래 수익률의 단순 합계.
실제로는:
  - 최대 2종목 동시 보유
  - 확신 50% / 보통 30% 포지션 사이징
  - 거래비용 (수수료 0.015% × 2 + 세금 0.23% = 편도 ~0.26%)
  - 주가가 비싸서 못 사는 경우
  - 이미 보유 중이라 추가 매수 불가
  - 동일 종목 중복 매수 불가

기존 backtest_20d_pullback.py의 "E) 95% + 오전거래량" 조건 사용.
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from dataclasses import dataclass, field
import time as time_mod
from collections import defaultdict


END_DATE = "20260212"

# 리스크 파라미터
SL_PCT = -0.04       # -4% 손절
TP_PCT = 0.05        # +5% 1차 익절
TP_PARTIAL = 0.70    # 70% 분매
BREAKEVEN_CUT = 0.005  # +0.5% 이하 본전컷

# 포지션 사이징
HIGH_CONF_PCT = 0.50  # 확신 종목: 50%
LOW_CONF_PCT = 0.30   # 보통 종목: 30%
MAX_POSITIONS = 2     # 최대 2종목
TOP_N = 5             # TOP5만 진입

# 거래비용
COMMISSION = 0.00015  # 매수/매도 각 0.015%
TAX = 0.0023          # 매도세 0.23%

INITIAL_CAPITAL = 10_000_000  # 1000만원

_kosdaq_set = None

def get_kosdaq_set():
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(END_DATE, market="KOSDAQ"))
    return _kosdaq_set

def code_to_ticker(code):
    return f"{code}{'.KQ' if code in get_kosdaq_set() else '.KS'}"


@dataclass
class Position:
    code: str
    name: str
    method: str
    entry_price: float
    quantity: int
    invested: float     # 실제 투입 금액
    entry_time: str
    partial_sold: bool = False
    original_quantity: int = 0

    def __post_init__(self):
        if self.original_quantity == 0:
            self.original_quantity = self.quantity


@dataclass
class TradeResult:
    code: str
    name: str
    method: str
    date: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    quantity: int
    pnl: float          # 원 단위 손익
    pnl_pct: float       # % 수익률
    exit_reason: str
    commission_cost: float


def get_trading_days(end_date, n_days=20):
    from datetime import timedelta
    end = pd.Timestamp(end_date)
    start = end - timedelta(days=60)
    df = pykrx_stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end_date, "005930")
    dates = [d.strftime("%Y%m%d") for d in df.index]
    return dates[-(n_days + 1):]


def fetch_daily_data(dates):
    print("=" * 70)
    print("  1. 일별 데이터 수집")
    print("=" * 70)
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
        time_mod.sleep(0.3)

    return daily_info, all_codes


def fetch_5min_bulk(codes, dates):
    print("\n" + "=" * 70)
    print("  2. 5분봉 수집")
    print("=" * 70)
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


def find_breakout(bars):
    """돌파매매: 09:30~11:00"""
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
    """눌림매매: 13:00~14:30, 95%깊이 + 오전거래량"""
    # 오전 거래량 체크
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


def calc_transaction_cost(price, qty, side="buy"):
    """거래비용 계산"""
    value = price * qty
    cost = value * COMMISSION  # 수수료
    if side == "sell":
        cost += value * TAX   # 매도세
    return cost


def simulate_day(bars_all, daily_info, date, prev_date, capital, positions):
    """하루 시뮬레이션 - 실제 자금 제약 반영"""
    info = daily_info[date]
    df = info["df"]
    universe = info["universe"]
    cap5000 = info["cap5000"]
    prev_df = daily_info[prev_date]["df"] if prev_date in daily_info else None

    # 3대 필터 적용
    eligible = universe & cap5000
    if prev_df is not None:
        inst_range = set(prev_df[
            (prev_df["기관순매수"] >= 50) & (prev_df["기관순매수"] <= 200)
        ].index.tolist())
        eligible = eligible & inst_range

    leaders = select_leaders(bars_all, date, eligible)
    leader_codes = [s["code"] for s in leaders]
    vol_median = get_morning_vol_median(bars_all, date, leader_codes)

    trades_today = []
    skipped_reasons = defaultdict(int)

    # === 1. 보유 포지션 모니터링 (5분봉 순회) ===
    codes_to_monitor = list(positions.keys())
    for code in codes_to_monitor:
        if code not in bars_all or date not in bars_all[code]:
            continue
        pos = positions[code]
        bars = bars_all[code][date]

        for ts, bar in bars.iterrows():
            lo_pct = (bar["Low"] / pos.entry_price) - 1
            hi_pct = (bar["High"] / pos.entry_price) - 1

            # 손절 -4%
            if lo_pct <= SL_PCT:
                exit_price = pos.entry_price * (1 + SL_PCT)
                sell_qty = pos.quantity
                cost = calc_transaction_cost(exit_price, sell_qty, "sell")
                pnl = (exit_price - pos.entry_price) * sell_qty - cost
                pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

                trades_today.append(TradeResult(
                    code=code, name=pos.name, method=pos.method, date=date,
                    entry_time=pos.entry_time, entry_price=pos.entry_price,
                    exit_time=str(ts)[:16], exit_price=exit_price,
                    quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
                    exit_reason="손절", commission_cost=cost,
                ))
                capital += exit_price * sell_qty - cost
                del positions[code]
                break

            # 1차 익절 +5% (70% 분매)
            if hi_pct >= TP_PCT and not pos.partial_sold:
                exit_price = pos.entry_price * (1 + TP_PCT)
                sell_qty = int(pos.quantity * TP_PARTIAL)
                if sell_qty <= 0:
                    sell_qty = pos.quantity

                cost = calc_transaction_cost(exit_price, sell_qty, "sell")
                pnl = (exit_price - pos.entry_price) * sell_qty - cost
                pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

                trades_today.append(TradeResult(
                    code=code, name=pos.name, method=pos.method, date=date,
                    entry_time=pos.entry_time, entry_price=pos.entry_price,
                    exit_time=str(ts)[:16], exit_price=exit_price,
                    quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
                    exit_reason="1차익절", commission_cost=cost,
                ))
                capital += exit_price * sell_qty - cost
                pos.quantity -= sell_qty
                pos.partial_sold = True

                if pos.quantity <= 0:
                    del positions[code]
                    break
                continue

            # 본전컷 (분매 후 원가 복귀)
            if pos.partial_sold and lo_pct <= BREAKEVEN_CUT:
                exit_price = bar["Close"]
                sell_qty = pos.quantity
                cost = calc_transaction_cost(exit_price, sell_qty, "sell")
                pnl = (exit_price - pos.entry_price) * sell_qty - cost
                pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

                trades_today.append(TradeResult(
                    code=code, name=pos.name, method=pos.method, date=date,
                    entry_time=pos.entry_time, entry_price=pos.entry_price,
                    exit_time=str(ts)[:16], exit_price=exit_price,
                    quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
                    exit_reason="본전컷", commission_cost=cost,
                ))
                capital += exit_price * sell_qty - cost
                del positions[code]
                break

    # === 2. 신규 진입 (TOP5 확신도순) ===
    # 돌파매매 (09:30~11:00)
    entries = []
    for s in leaders[:TOP_N]:
        code = s["code"]
        if code in positions:
            skipped_reasons["이미보유"] += 1
            continue
        if code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        entry = find_breakout(bars)
        if entry:
            entries.append({"code": code, "entry": entry, "method": "돌파",
                           "momentum": s["momentum"]})

    # 눌림매매 (13:00~14:30)
    for s in leaders[:TOP_N]:
        code = s["code"]
        if code in positions:
            continue
        if any(e["code"] == code for e in entries):
            continue
        if code not in bars_all or date not in bars_all[code]:
            continue
        bars = bars_all[code][date]
        entry = find_pullback(bars, vol_median)
        if entry:
            entries.append({"code": code, "entry": entry, "method": "눌림",
                           "momentum": s["momentum"]})

    # 모멘텀순 정렬 후 진입
    entries.sort(key=lambda x: x["momentum"], reverse=True)

    for e in entries:
        if len(positions) >= MAX_POSITIONS:
            skipped_reasons["최대보유초과"] += 1
            continue

        code = e["code"]
        entry = e["entry"]
        price = entry["price"]
        conf = entry["confidence"]

        # 포지션 사이징
        alloc_pct = HIGH_CONF_PCT if conf >= 0.7 else LOW_CONF_PCT
        invest_amount = capital * alloc_pct  # 현재 가용자금 기준

        # 실제 매수 가능 수량
        qty = int(invest_amount / price)
        if qty <= 0:
            skipped_reasons["자금부족"] += 1
            continue

        # 최소 10만원 이상 투자
        if price * qty < 100_000:
            skipped_reasons["소액스킵"] += 1
            continue

        buy_cost = calc_transaction_cost(price, qty, "buy")
        total_cost = price * qty + buy_cost

        if total_cost > capital:
            qty = int((capital - buy_cost) / price)
            if qty <= 0:
                skipped_reasons["자금부족"] += 1
                continue
            buy_cost = calc_transaction_cost(price, qty, "buy")
            total_cost = price * qty + buy_cost

        name = pykrx_stock.get_market_ticker_name(code) or code
        capital -= total_cost

        positions[code] = Position(
            code=code, name=name, method=e["method"],
            entry_price=price, quantity=qty,
            invested=price * qty,
            entry_time=str(entry["time"])[:16],
        )

    # === 3. 장마감 청산 (잔여 포지션) ===
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
        sell_qty = pos.quantity
        cost = calc_transaction_cost(exit_price, sell_qty, "sell")
        pnl = (exit_price - pos.entry_price) * sell_qty - cost
        pnl_pct = ((exit_price / pos.entry_price) - 1) * 100

        trades_today.append(TradeResult(
            code=code, name=pos.name, method=pos.method, date=date,
            entry_time=pos.entry_time, entry_price=pos.entry_price,
            exit_time=str(bars.index[-1])[:16], exit_price=exit_price,
            quantity=sell_qty, pnl=pnl, pnl_pct=pnl_pct,
            exit_reason="장마감", commission_cost=cost,
        ))
        capital += exit_price * sell_qty - cost
        del positions[code]

    return capital, trades_today, skipped_reasons


def main():
    print("=" * 70)
    print("  1000만원 실투자 시뮬레이션 (20일)")
    print(f"  초기자금: {INITIAL_CAPITAL:,}원")
    print(f"  조건: 시총5000억+ / 기관50~200억 / 눌림95%+거래량")
    print(f"  최대 {MAX_POSITIONS}종목 동시보유, TOP{TOP_N} 진입")
    print(f"  SL {SL_PCT*100:.0f}% / TP {TP_PCT*100:.0f}% ({TP_PARTIAL*100:.0f}%분매)")
    print(f"  거래비용: 수수료 {COMMISSION*100:.3f}% + 세금 {TAX*100:.2f}%")
    print("=" * 70)

    dates_all = get_trading_days(END_DATE, 20)
    prev_dates = dates_all[:-1]
    trade_dates = dates_all[1:]
    print(f"\n  매매일 {len(trade_dates)}일: {trade_dates[0]}~{trade_dates[-1]}")

    daily_info, all_codes = fetch_daily_data(dates_all)
    bars_all = fetch_5min_bulk(all_codes, trade_dates)

    # === 시뮬레이션 실행 ===
    print("\n" + "=" * 70)
    print("  3. 실투자 시뮬레이션")
    print("=" * 70)

    capital = INITIAL_CAPITAL
    positions = {}
    all_trades = []
    all_skipped = defaultdict(int)
    daily_log = []

    for i, date in enumerate(trade_dates):
        prev_date = prev_dates[i]
        day_start_capital = capital + sum(
            p.entry_price * p.quantity for p in positions.values()
        )

        capital, trades, skipped = simulate_day(
            bars_all, daily_info, date, prev_date, capital, positions
        )
        all_trades.extend(trades)
        for k, v in skipped.items():
            all_skipped[k] += v

        day_pnl = sum(t.pnl for t in trades)
        day_end_capital = capital + sum(
            p.entry_price * p.quantity for p in positions.values()
        )

        d_fmt = f"{date[4:6]}/{date[6:]}"
        daily_log.append({
            "date": d_fmt,
            "trades": len(trades),
            "pnl": day_pnl,
            "capital": day_end_capital,
        })

        wins = sum(1 for t in trades if t.pnl > 0)
        print(f"    {d_fmt}: {len(trades)}거래 "
              f"({wins}W {len(trades)-wins}L) "
              f"PnL {day_pnl:+,.0f}원 "
              f"자산 {day_end_capital:,.0f}원")

    # === 결과 ===
    print("\n" + "=" * 70)
    print("  4. 최종 결과")
    print("=" * 70)

    final_capital = capital
    total_pnl = final_capital - INITIAL_CAPITAL
    total_return = (final_capital / INITIAL_CAPITAL - 1) * 100
    total_trades = len(all_trades)
    total_wins = sum(1 for t in all_trades if t.pnl > 0)
    total_commission = sum(t.commission_cost for t in all_trades)

    print(f"\n  초기자금:     {INITIAL_CAPITAL:>12,}원")
    print(f"  최종자금:     {final_capital:>12,.0f}원")
    print(f"  총 수익:      {total_pnl:>+12,.0f}원 ({total_return:+.2f}%)")
    print(f"  총 거래비용:  {total_commission:>12,.0f}원")
    print(f"  총 거래:      {total_trades:>8}건")
    print(f"  승률:         {total_wins/total_trades*100 if total_trades else 0:>7.1f}%")
    print(f"  승: {total_wins}건 / 패: {total_trades - total_wins}건")

    # 방법별
    print(f"\n  [방법별]")
    for m in ["돌파", "눌림"]:
        ts = [t for t in all_trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl > 0)
            mp = sum(t.pnl for t in ts)
            print(f"    {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | "
                  f"WR {mw/len(ts)*100:.1f}% | {mp:+,.0f}원")

    # 청산사유별
    print(f"\n  [청산사유별]")
    for reason in ["1차익절", "손절", "본전컷", "장마감"]:
        ts = [t for t in all_trades if t.exit_reason == reason]
        if ts:
            mp = sum(t.pnl for t in ts)
            print(f"    {reason}: {len(ts)}건 | {mp:+,.0f}원")

    # 스킵 사유
    if all_skipped:
        print(f"\n  [진입 스킵 사유]")
        for reason, cnt in sorted(all_skipped.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {cnt}건")

    # 일별 요약
    print(f"\n  [일별]")
    print(f"  {'날짜':8s} {'거래':>4s} {'PnL':>12s} {'자산':>14s}")
    print(f"  {'─'*42}")
    for d in daily_log:
        print(f"  {d['date']:8s} {d['trades']:4d} {d['pnl']:>+12,.0f}원 {d['capital']:>14,.0f}원")

    # 최대 낙폭
    peak = INITIAL_CAPITAL
    max_dd = 0
    for d in daily_log:
        peak = max(peak, d["capital"])
        dd = (d["capital"] - peak) / peak * 100
        max_dd = min(max_dd, dd)
    print(f"\n  최대 낙폭(MDD): {max_dd:.2f}%")

    # 월 환산
    monthly_est = total_return / 20 * 22  # 22영업일/월
    print(f"  월 환산 수익률: {monthly_est:+.2f}% ({total_pnl / 20 * 22:+,.0f}원/월)")


if __name__ == "__main__":
    main()
