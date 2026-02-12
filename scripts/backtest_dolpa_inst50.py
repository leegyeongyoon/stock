"""
홍인기 돌파매매 백테스트 V3: 기관 50~200억 스위트스팟

이전 결과:
  기관 매도:      -2.77% WR19%
  기관 0~50억:    +1.98% WR42%
  기관 50~200억:  +2.71% WR70%  ← 스위트스팟
  기관 200억+:    +0.29% WR54%

→ 기관 50~200억만 필터 + 끼/차트 보조
→ 기관 크기 세분화 + 진입 타이밍 최적화
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from datetime import datetime, timedelta
import time

END_DATE = "20260212"
N_ANALYSIS_DAYS = 20
TOP_N = 20

SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70

# 기관 스위트스팟
INST_MIN = 5_000_000_000    # 50억
INST_MAX = 20_000_000_000   # 200억

KKI_LOOKBACK_DAYS = 90
KKI_MIN_CHANGE = 15.0
CHART_HIGH_DAYS = 20
CHART_NEAR_PCT = 0.95

_kosdaq_set = None

def get_kosdaq_set(date=END_DATE):
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(date, market="KOSDAQ"))
    return _kosdaq_set

def code_to_ticker(code):
    return f"{code}{'.KQ' if code in get_kosdaq_set() else '.KS'}"

def get_trading_days(end_date, n_days):
    start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=n_days * 2)).strftime("%Y%m%d")
    days = pykrx_stock.get_previous_business_days(fromdate=start, todate=end_date)
    return [d.strftime("%Y%m%d") for d in days[-n_days:]]


def phase1():
    print("=" * 70)
    print("  기관 50~200억 스위트스팟 돌파매매 (20일)")
    print("=" * 70)

    all_days = get_trading_days(END_DATE, N_ANALYSIS_DAYS + KKI_LOOKBACK_DAYS + CHART_HIGH_DAYS)
    analysis_days = all_days[-N_ANALYSIS_DAYS:]
    print(f"  기간: {analysis_days[0]} ~ {analysis_days[-1]}")

    print(f"  일봉 수집... ({len(all_days)}일)")
    daily = {}
    for i, day in enumerate(all_days):
        try:
            df = pykrx_stock.get_market_ohlcv_by_ticker(day, market="ALL")
            daily[day] = df[df["거래량"] > 0]
        except Exception:
            pass
        if (i + 1) % 30 == 0:
            print(f"    {i+1}/{len(all_days)}")
    print(f"  완료: {len(daily)}일")

    events = []

    for day_idx, curr_day in enumerate(analysis_days):
        curr_pos = all_days.index(curr_day)
        if curr_pos < 1:
            continue
        prev_day = all_days[curr_pos - 1]
        if prev_day not in daily or curr_day not in daily:
            continue

        df_prev = daily[prev_day]
        df_curr = daily[curr_day]

        top20 = df_prev.nlargest(TOP_N, "거래대금")
        strong = [c for c in top20.index if df_prev.loc[c, "등락률"] >= 3.0]

        for code in strong:
            name = pykrx_stock.get_market_ticker_name(code) or code
            prev_row = df_prev.loc[code]
            prev_close = prev_row["종가"]
            prev_change = prev_row["등락률"]
            prev_value = prev_row["거래대금"]

            # 기관 수급
            inst_net = 0
            foreign_net = 0
            try:
                inv = pykrx_stock.get_market_trading_value_by_date(prev_day, prev_day, code)
                if not inv.empty:
                    inst_net = inv.iloc[0].get("기관합계", 0)
                    foreign_net = inv.iloc[0].get("외국인합계", 0)
            except Exception:
                pass

            # 기관 구간 태그
            if inst_net < 0:
                inst_group = "매도"
            elif inst_net < INST_MIN:
                inst_group = "소폭0~50"
            elif inst_net <= INST_MAX:
                inst_group = "스위트50~200"
            else:
                inst_group = "대량200+"

            # 끼
            kki_ok = False
            lookback_start = max(0, curr_pos - KKI_LOOKBACK_DAYS)
            for ld in all_days[lookback_start:curr_pos - 1]:
                if ld in daily and code in daily[ld].index:
                    if daily[ld].loc[code, "등락률"] >= KKI_MIN_CHANGE:
                        kki_ok = True
                        break

            # 차트 위치
            chart_ok = False
            high_20d = 0
            for hd in all_days[max(0, curr_pos - CHART_HIGH_DAYS):curr_pos]:
                if hd in daily and code in daily[hd].index:
                    h = daily[hd].loc[code, "고가"]
                    if h > high_20d:
                        high_20d = h
            if high_20d > 0:
                chart_ok = prev_close / high_20d >= CHART_NEAR_PCT

            # 당일 결과
            if code not in df_curr.index:
                continue
            cr = df_curr.loc[code]

            est_entry = prev_close * 1.03
            if cr["고가"] >= est_entry and est_entry > 0:
                est_pnl = (cr["종가"] / est_entry - 1) * 100
                est_traded = True
            else:
                est_pnl = 0
                est_traded = False

            events.append({
                "prev_day": prev_day, "curr_day": curr_day,
                "code": code, "name": name,
                "prev_change": prev_change, "prev_close": prev_close,
                "prev_value": prev_value,
                "inst_net": inst_net, "foreign_net": foreign_net,
                "inst_group": inst_group,
                "kki_ok": kki_ok, "chart_ok": chart_ok,
                "curr_change": cr["등락률"],
                "curr_open": cr["시가"], "curr_close": cr["종가"],
                "curr_high": cr["고가"], "curr_low": cr["저가"],
                "est_traded": est_traded, "est_pnl": est_pnl,
            })

        if (day_idx + 1) % 5 == 0:
            print(f"  진행: {day_idx+1}/{len(analysis_days)}일 ({len(events)}건)")

    print(f"\n  총 후보: {len(events)}건")
    if not events:
        return events

    df = pd.DataFrame(events)
    traded = df[df["est_traded"]]

    # ── 기관 구간별 전체 비교 ──
    print(f"\n  ┌─── 기관 순매수 구간별 비교 ───┐")
    for grp in ["매도", "소폭0~50", "스위트50~200", "대량200+"]:
        sub = traded[traded["inst_group"] == grp]
        if len(sub) > 0:
            avg = sub["est_pnl"].mean()
            wr = (sub["est_pnl"] > 0).mean() * 100
            tot = sub["est_pnl"].sum()
            mark = "★" if grp == "스위트50~200" else " "
            print(f"  │{mark} {grp:12s}: {len(sub):3d}건 | "
                  f"평균 {avg:+.2f}% | 승률 {wr:.0f}% | 합계 {tot:+.1f}%")
    print(f"  └────────────────────────────┘")

    # ── 스위트스팟 세분화 ──
    sweet = traded[traded["inst_group"] == "스위트50~200"]
    print(f"\n  ┌─── 스위트스팟(50~200억) 세분화 ───┐")
    if len(sweet) > 0:
        for label, lo, hi in [
            ("50~80억",  5e9, 8e9),
            ("80~120억", 8e9, 1.2e10),
            ("120~200억", 1.2e10, 2e10),
        ]:
            sub = sweet[(sweet["inst_net"] >= lo) & (sweet["inst_net"] < hi)]
            if len(sub) > 0:
                avg = sub["est_pnl"].mean()
                wr = (sub["est_pnl"] > 0).mean() * 100
                print(f"  │ {label:10s}: {len(sub):3d}건 | "
                      f"평균 {avg:+.2f}% | 승률 {wr:.0f}%")
    print(f"  └──────────────────────────────┘")

    # ── 스위트스팟 + 보조 조건 ──
    print(f"\n  ┌─── 스위트스팟 + 보조 조건 ───┐")
    if len(sweet) > 0:
        for label, mask in [
            ("50~200 + 끼 + 차트", (sweet["kki_ok"]) & (sweet["chart_ok"])),
            ("50~200 + 끼",       (sweet["kki_ok"])),
            ("50~200 + 차트",     (sweet["chart_ok"])),
            ("50~200 전체",       pd.Series(True, index=sweet.index)),
        ]:
            sub = sweet[mask]
            if len(sub) > 0:
                avg = sub["est_pnl"].mean()
                wr = (sub["est_pnl"] > 0).mean() * 100
                tot = sub["est_pnl"].sum()
                print(f"  │ {label:20s}: {len(sub):3d}건 | "
                      f"평균 {avg:+.2f}% | 승률 {wr:.0f}% | 합계 {tot:+.1f}%")
    print(f"  └──────────────────────────────┘")

    # ── 스위트스팟 + 전일 등락률 ──
    print(f"\n  ┌─── 스위트스팟 + 전일 등락률 ───┐")
    if len(sweet) > 0:
        for label, lo, hi in [
            ("3~10%",  3, 10),
            ("10~20%", 10, 20),
            ("20%+",   20, 100),
        ]:
            sub = sweet[(sweet["prev_change"] >= lo) & (sweet["prev_change"] < hi)]
            if len(sub) > 0:
                avg = sub["est_pnl"].mean()
                wr = (sub["est_pnl"] > 0).mean() * 100
                print(f"  │ 전일 {label:8s}: {len(sub):3d}건 | "
                      f"평균 {avg:+.2f}% | 승률 {wr:.0f}%")
    print(f"  └────────────────────────────┘")

    # ── 스위트스팟 개별 이벤트 ──
    sweet_all = df[df["inst_group"] == "스위트50~200"]
    print(f"\n  ┌─── 스위트스팟 전체 이벤트 ({len(sweet_all)}건) ───┐")
    for _, ev in sweet_all.sort_values("curr_day").iterrows():
        tags = ""
        if ev["kki_ok"]: tags += "끼 "
        if ev["chart_ok"]: tags += "차트 "
        if not tags: tags = "- "

        entry_mark = "O" if ev["est_traded"] else "X"
        if ev["est_traded"]:
            w = "W" if ev["est_pnl"] > 0 else "L"
            pnl_s = f"{ev['est_pnl']:+.1f}%"
        else:
            w = "-"
            pnl_s = "진입X"

        print(f"  │ {w} {ev['curr_day'][4:6]}/{ev['curr_day'][6:]} "
              f"{ev['name']:10s} | 기관{ev['inst_net']/1e8:+,.0f}억 | "
              f"전일{ev['prev_change']:+.1f}% | 당일{ev['curr_change']:+.1f}% | "
              f"[{tags.strip()}] | {pnl_s}")
    print(f"  └─────────────────────────────────┘")

    return events


def phase2(events):
    print("\n" + "=" * 70)
    print("  Phase 2: 5분봉 시뮬레이션 (최근 5일)")
    print("  기관 50~200억 vs 기타 비교")
    print("=" * 70)

    if not events:
        return

    df = pd.DataFrame(events)
    recent_days = sorted(df["curr_day"].unique())[-5:]
    recent = df[df["curr_day"].isin(recent_days)].copy()

    print(f"  대상: {len(recent)}건")

    codes = list(recent["code"].unique())
    print(f"  5분봉: {len(codes)}개 종목...")

    bars_all = {}
    batch_size = 20
    for bs in range(0, len(codes), batch_size):
        batch = codes[bs:bs + batch_size]
        tickers = [code_to_ticker(c) for c in batch]
        try:
            data = yf.download(" ".join(tickers), period="5d", interval="5m",
                               progress=False, threads=True)
            if data.empty:
                continue
            for code in batch:
                ticker = code_to_ticker(code)
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if ticker in data.columns.get_level_values(1):
                            sub = data.xs(ticker, level=1, axis=1).copy()
                        else:
                            continue
                    else:
                        sub = data.copy()
                    sub = sub.dropna(subset=["Close"])
                    if sub.empty:
                        continue
                    if sub.index.tz is not None:
                        sub.index = sub.index.tz_convert("Asia/Seoul")
                    else:
                        sub.index = sub.index.tz_localize("UTC").tz_convert("Asia/Seoul")
                    bars_all[code] = sub
                except Exception:
                    continue
        except Exception:
            continue

    print(f"  수집: {len(bars_all)}개\n")

    results = []
    for _, ev in recent.sort_values(["curr_day", "inst_net"], ascending=[True, False]).iterrows():
        code, name, curr_day = ev["code"], ev["name"], ev["curr_day"]

        if code not in bars_all:
            continue

        target_date = pd.Timestamp(f"{curr_day[:4]}-{curr_day[4:6]}-{curr_day[6:]}").date()
        day_bars = bars_all[code][bars_all[code].index.date == target_date]
        if len(day_bars) < 10:
            continue

        # 오전 모멘텀
        morning = day_bars[
            ((day_bars.index.hour == 9) & (day_bars.index.minute >= 30)) |
            ((day_bars.index.hour == 10) & (day_bars.index.minute == 0))
        ]
        mom_ok = False
        mom_s = ""
        if len(morning) >= 3:
            bull = sum(1 for _, b in morning.iterrows() if b["Close"] >= b["Open"])
            br = bull / len(morning)
            pc = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
            mom_ok = br >= 0.5 and pc > 0
            mom_s = f"양봉{br*100:.0f}% {pc:+.1f}%"

        # 돌파 진입
        window = day_bars[
            (day_bars.index.hour == 10) |
            ((day_bars.index.hour == 11) & (day_bars.index.minute == 0))
        ]
        entry = None
        if len(window) >= 6:
            for i in range(5, len(window)):
                ph = window["High"].iloc[i-5:i].max()
                bar = window.iloc[i]
                if bar["High"] > ph and bar["Close"] > ph:
                    av = window["Volume"].iloc[i-5:i].mean()
                    if av > 0 and bar["Volume"] >= av * 1.5:
                        entry = {"price": bar["Close"], "time": window.index[i]}
                        break

        if not entry:
            results.append({**dict(ev), "traded": False, "mom_ok": mom_ok, "pnl": 0})
            continue

        # SL/TP
        ep, et = entry["price"], entry["time"]
        after = day_bars[day_bars.index > et]
        xp, xt, xr = None, None, ""

        for ts, bar in after.iterrows():
            lo = (bar["Low"] / ep) - 1
            hi = (bar["High"] / ep) - 1
            if lo <= SL_PCT:
                xp, xt, xr = ep * (1 + SL_PCT), ts, "손절"
                break
            if hi >= TP_PCT:
                xp, xt, xr = ep * (1 + TP_PCT * TP_PARTIAL), ts, "익절"
                break

        if xp is None and len(after) > 0:
            xp, xt, xr = after.iloc[-1]["Close"], after.index[-1], "장마감"

        pnl = (xp / ep - 1) * 100 if xp and ep else 0
        w = "W" if pnl > 0 else "L"
        grp = ev["inst_group"]
        mark = "★" if grp == "스위트50~200" else " "

        tags = grp
        if ev["kki_ok"]: tags += "+끼"
        if ev["chart_ok"]: tags += "+차트"
        if mom_ok: tags += "+모멘텀"

        print(f"  {mark}{w} {curr_day[4:]}/{curr_day[6:]} {name:10s} | "
              f"[{tags}] 기관{ev['inst_net']/1e8:+,.0f}억 | "
              f"{str(et)[11:16]}→{str(xt)[11:16]} | "
              f"{pnl:+.2f}% ({xr}) | {mom_s}")

        results.append({**dict(ev), "traded": True, "mom_ok": mom_ok, "pnl": pnl, "exit_reason": xr})

    traded_r = [r for r in results if r["traded"]]
    if not traded_r:
        print("\n  매매 없음")
        return

    tdf = pd.DataFrame(traded_r)

    print(f"\n  ┌─── 5분봉 결과 ───┐")
    for grp in ["스위트50~200", "소폭0~50", "대량200+", "매도"]:
        sub = tdf[tdf["inst_group"] == grp]
        if len(sub) > 0:
            sw = (sub["pnl"] > 0).sum()
            mark = "★" if grp == "스위트50~200" else " "
            print(f"  │{mark} {grp:12s}: {len(sub):2d}건 | {sw}W {len(sub)-sw}L | "
                  f"WR {sw/len(sub)*100:.0f}% | 평균 {sub['pnl'].mean():+.2f}% | "
                  f"합계 {sub['pnl'].sum():+.1f}%")
    print(f"  └──────────────────┘")


def main():
    t0 = time.time()
    events = phase1()
    phase2(events)
    elapsed = time.time() - t0
    print(f"\n  소요: {elapsed:.0f}초")

    if not events:
        return

    df = pd.DataFrame(events)
    traded = df[df["est_traded"]]
    sweet = traded[traded["inst_group"] == "스위트50~200"]

    print("\n" + "=" * 70)
    print("  최종 전략")
    print("=" * 70)

    if len(sweet) > 0:
        avg = sweet["est_pnl"].mean()
        wr = (sweet["est_pnl"] > 0).mean() * 100
        tot = sweet["est_pnl"].sum()
        print(f"\n  기관 50~200억 필터:")
        print(f"    {len(sweet)}건 | 평균 {avg:+.2f}% | 승률 {wr:.0f}% | 합계 {tot:+.1f}%")

        # 최적 조합
        sweet_kki = sweet[sweet["kki_ok"]]
        if len(sweet_kki) > 0:
            print(f"    + 끼 추가: {len(sweet_kki)}건 | "
                  f"평균 {sweet_kki['est_pnl'].mean():+.2f}% | "
                  f"승률 {(sweet_kki['est_pnl']>0).mean()*100:.0f}%")

        sweet_both = sweet[(sweet["kki_ok"]) & (sweet["chart_ok"])]
        if len(sweet_both) > 0:
            print(f"    + 끼+차트: {len(sweet_both)}건 | "
                  f"평균 {sweet_both['est_pnl'].mean():+.2f}% | "
                  f"승률 {(sweet_both['est_pnl']>0).mean()*100:.0f}%")

    # 다른 구간과 비교
    others = traded[traded["inst_group"] != "스위트50~200"]
    if len(others) > 0:
        print(f"\n  기관 50~200억 외 나머지:")
        print(f"    {len(others)}건 | 평균 {others['est_pnl'].mean():+.2f}% | "
              f"승률 {(others['est_pnl']>0).mean()*100:.0f}%")

    print(f"\n  전략 요약:")
    print(f"    조건1: 전일 거래대금 TOP20 + 강세(+3%+)")
    print(f"    조건2: 전일 기관 순매수 50~200억 (필수)")
    print(f"    조건3: 끼(과거 +15% 이력) 추가시 승률↑")
    print(f"    진입:  10:00~11:00 돌파 (5봉고점 + 거래량 1.5x)")
    print(f"    SL:    -4% / TP: +5%")


if __name__ == "__main__":
    main()
