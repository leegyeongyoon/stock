"""
홍인기 돌파매매 백테스트 V2: 기관 수급 중심

이전 분석 결과:
  기관순매수+: O +1.38% WR54% vs X -2.77% WR19% → 압도적
  끼(급등이력): O +1.37% WR50% vs X -0.63% WR45% → 효과
  차트위치:     O +1.32% WR47% vs X -0.09% WR51% → 약간
  거래대금:     차이 미미
  외국인:       효과 없음

→ 조건 3개로 축소:
  필수: 기관 순매수 > 0
  보조1: 끼 (과거 60일 내 +15% 이력)
  보조2: 차트 위치 (전일종가 >= 20일고가 * 95%)

비교 그룹:
  A) 기관O + 끼O + 차트O (3점)
  B) 기관O + 끼O or 차트O (2점)
  C) 기관O만 (1점)
  D) 기관X (대조군)
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from datetime import datetime, timedelta
import time

# ─── 설정 ───
END_DATE = "20260212"
N_ANALYSIS_DAYS = 20
TOP_N = 20

SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70

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
    suffix = ".KQ" if code in get_kosdaq_set() else ".KS"
    return f"{code}{suffix}"


def get_trading_days(end_date, n_days):
    start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=n_days * 2)).strftime("%Y%m%d")
    days = pykrx_stock.get_previous_business_days(fromdate=start, todate=end_date)
    return [d.strftime("%Y%m%d") for d in days[-n_days:]]


# ─── Phase 1: Daily 분석 ───

def phase1():
    print("=" * 70)
    print("  Phase 1: 기관 수급 중심 돌파매매 Daily 스크리닝 (20일)")
    print("  필수=기관순매수 / 보조=끼+차트위치")
    print("=" * 70)

    all_days = get_trading_days(END_DATE, N_ANALYSIS_DAYS + KKI_LOOKBACK_DAYS + CHART_HIGH_DAYS)
    analysis_days = all_days[-N_ANALYSIS_DAYS:]
    print(f"  분석: {analysis_days[0]} ~ {analysis_days[-1]}")

    # 일봉 캐시
    print(f"  일봉 수집 중... ({len(all_days)}일)")
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

        # 전일 거래대금 TOP20 + 강세 3%+
        top20 = df_prev.nlargest(TOP_N, "거래대금")
        strong_codes = [c for c in top20.index if df_prev.loc[c, "등락률"] >= 3.0]

        for code in strong_codes:
            name = pykrx_stock.get_market_ticker_name(code) or code
            prev_row = df_prev.loc[code]
            prev_close = prev_row["종가"]
            prev_change = prev_row["등락률"]

            # ── 필수: 기관 수급 ──
            inst_ok = False
            inst_net = 0
            try:
                inv = pykrx_stock.get_market_trading_value_by_date(prev_day, prev_day, code)
                if not inv.empty:
                    inst_net = inv.iloc[0].get("기관합계", 0)
                    inst_ok = inst_net > 0
            except Exception:
                pass

            # ── 보조1: 끼 ──
            kki_ok = False
            lookback_start = max(0, curr_pos - KKI_LOOKBACK_DAYS)
            for ld in all_days[lookback_start:curr_pos - 1]:
                if ld in daily and code in daily[ld].index:
                    if daily[ld].loc[code, "등락률"] >= KKI_MIN_CHANGE:
                        kki_ok = True
                        break

            # ── 보조2: 차트 위치 ──
            chart_ok = False
            high_20d = 0
            for hd in all_days[max(0, curr_pos - CHART_HIGH_DAYS):curr_pos]:
                if hd in daily and code in daily[hd].index:
                    h = daily[hd].loc[code, "고가"]
                    if h > high_20d:
                        high_20d = h
            if high_20d > 0:
                chart_ok = prev_close / high_20d >= CHART_NEAR_PCT

            # 점수: 기관(필수) + 끼 + 차트
            score = sum([inst_ok, kki_ok, chart_ok])

            # 당일 결과
            if code not in df_curr.index:
                continue

            curr_row = df_curr.loc[code]
            curr_open = curr_row["시가"]
            curr_close = curr_row["종가"]
            curr_high = curr_row["고가"]
            curr_change = curr_row["등락률"]

            # 돌파 진입 추정 (전일종가+3% 돌파)
            est_entry = prev_close * 1.03
            if curr_high >= est_entry and est_entry > 0:
                est_pnl = (curr_close / est_entry - 1) * 100
                est_traded = True
            else:
                est_pnl = 0
                est_traded = False

            events.append({
                "prev_day": prev_day, "curr_day": curr_day,
                "code": code, "name": name,
                "prev_change": prev_change, "prev_close": prev_close,
                "inst_ok": inst_ok, "inst_net": inst_net,
                "kki_ok": kki_ok, "chart_ok": chart_ok,
                "score": score,
                "curr_change": curr_change, "curr_close": curr_close,
                "curr_high": curr_high, "curr_open": curr_open,
                "est_traded": est_traded, "est_pnl": est_pnl,
            })

        if (day_idx + 1) % 5 == 0:
            print(f"  진행: {day_idx+1}/{len(analysis_days)}일 ({len(events)}건)")

    print(f"\n  총 후보: {len(events)}건")

    if not events:
        return events

    df = pd.DataFrame(events)
    traded = df[df["est_traded"]]

    # ── 기관O vs 기관X (핵심 비교) ──
    print(f"\n  ┌─── 기관 수급 필터 효과 ───┐")
    inst_yes = traded[traded["inst_ok"]]
    inst_no = traded[~traded["inst_ok"]]
    if len(inst_yes) > 0:
        print(f"  │ 기관O: {len(inst_yes):3d}건 | "
              f"평균 {inst_yes['est_pnl'].mean():+.2f}% | "
              f"승률 {(inst_yes['est_pnl']>0).mean()*100:.0f}% | "
              f"합계 {inst_yes['est_pnl'].sum():+.1f}%")
    if len(inst_no) > 0:
        print(f"  │ 기관X: {len(inst_no):3d}건 | "
              f"평균 {inst_no['est_pnl'].mean():+.2f}% | "
              f"승률 {(inst_no['est_pnl']>0).mean()*100:.0f}% | "
              f"합계 {inst_no['est_pnl'].sum():+.1f}%")
    print(f"  └──────────────────────────┘")

    # ── 기관O 내에서 보조 조건 효과 ──
    print(f"\n  ┌─── 기관O 내 보조 조건 조합 ───┐")
    inst_traded = traded[traded["inst_ok"]]
    if len(inst_traded) > 0:
        for label, cond in [
            ("기관O + 끼O + 차트O", inst_traded[(inst_traded["kki_ok"]) & (inst_traded["chart_ok"])]),
            ("기관O + 끼O",         inst_traded[(inst_traded["kki_ok"]) & (~inst_traded["chart_ok"])]),
            ("기관O + 차트O",       inst_traded[(~inst_traded["kki_ok"]) & (inst_traded["chart_ok"])]),
            ("기관O만",             inst_traded[(~inst_traded["kki_ok"]) & (~inst_traded["chart_ok"])]),
        ]:
            if len(cond) > 0:
                avg = cond["est_pnl"].mean()
                wr = (cond["est_pnl"] > 0).mean() * 100
                tot = cond["est_pnl"].sum()
                print(f"  │ {label:20s}: {len(cond):3d}건 | "
                      f"평균 {avg:+.2f}% | 승률 {wr:.0f}% | 합계 {tot:+.1f}%")
    print(f"  └────────────────────────────┘")

    # ── 기관 순매수 크기별 ──
    print(f"\n  ┌─── 기관 순매수 크기별 (돌파 진입) ───┐")
    for label, lo, hi in [
        ("매도(음수)", -1e18, 0),
        ("소폭매수 0~50억", 0, 5e9),
        ("중간 50~200억", 5e9, 2e10),
        ("대량 200억+", 2e10, 1e18),
    ]:
        sub = traded[(traded["inst_net"] >= lo) & (traded["inst_net"] < hi)]
        if len(sub) > 0:
            avg = sub["est_pnl"].mean()
            wr = (sub["est_pnl"] > 0).mean() * 100
            print(f"  │ {label:18s}: {len(sub):3d}건 | "
                  f"평균 {avg:+.2f}% | 승률 {wr:.0f}%")
    print(f"  └─────────────────────────────────┘")

    # ── 전일 등락률 크기별 (기관O만) ──
    print(f"\n  ┌─── 전일 등락률별 (기관O + 돌파진입) ───┐")
    inst_t = traded[traded["inst_ok"]]
    for label, lo, hi in [
        ("3~10%",  3, 10),
        ("10~20%", 10, 20),
        ("20~30%", 20, 30),
        ("30%+(상한가)", 30, 100),
    ]:
        sub = inst_t[(inst_t["prev_change"] >= lo) & (inst_t["prev_change"] < hi)]
        if len(sub) > 0:
            avg = sub["est_pnl"].mean()
            wr = (sub["est_pnl"] > 0).mean() * 100
            print(f"  │ 전일 {label:14s}: {len(sub):3d}건 | "
                  f"평균 {avg:+.2f}% | 승률 {wr:.0f}%")
    print(f"  └────────────────────────────────────┘")

    return events


# ─── Phase 2: 5분봉 시뮬 ───

def phase2(events):
    print("\n" + "=" * 70)
    print("  Phase 2: 5분봉 돌파매매 시뮬레이션 (최근 5일)")
    print("  기관O 필수 / 기관X는 대조군")
    print("=" * 70)

    if not events:
        return

    df = pd.DataFrame(events)
    recent_days = sorted(df["curr_day"].unique())[-5:]
    recent = df[df["curr_day"].isin(recent_days)].copy()

    print(f"  대상: {len(recent)}건 (최근 5일)")

    # 5분봉 다운로드
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

    print(f"  수집 완료: {len(bars_all)}개")

    # 시뮬
    results = []
    for _, ev in recent.sort_values(["curr_day", "score"], ascending=[True, False]).iterrows():
        code = ev["code"]
        name = ev["name"]
        curr_day = ev["curr_day"]

        if code not in bars_all:
            continue

        target_date = pd.Timestamp(f"{curr_day[:4]}-{curr_day[4:6]}-{curr_day[6:]}").date()
        day_bars = bars_all[code][bars_all[code].index.date == target_date]
        if len(day_bars) < 10:
            continue

        # 오전 모멘텀 (9:30~10:00)
        morning = day_bars[
            ((day_bars.index.hour == 9) & (day_bars.index.minute >= 30)) |
            ((day_bars.index.hour == 10) & (day_bars.index.minute == 0))
        ]
        mom_ok = False
        mom_detail = ""
        if len(morning) >= 3:
            bull = sum(1 for _, b in morning.iterrows() if b["Close"] >= b["Open"])
            br = bull / len(morning)
            pchg = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
            mom_ok = br >= 0.5 and pchg > 0
            mom_detail = f"양봉{br*100:.0f}% {pchg:+.1f}%"

        # 돌파 진입 (10:00~11:00)
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

        if entry is None:
            results.append({**dict(ev), "traded": False, "mom_ok": mom_ok,
                            "pnl": 0, "exit_reason": "진입X"})
            continue

        # SL/TP
        ep = entry["price"]
        et = entry["time"]
        after = day_bars[day_bars.index > et]

        xp, xt, xr = None, None, ""
        for ts, bar in after.iterrows():
            lo = (bar["Low"] / ep) - 1
            hi = (bar["High"] / ep) - 1
            if lo <= SL_PCT:
                xp = ep * (1 + SL_PCT)
                xt, xr = ts, "손절-4%"
                break
            if hi >= TP_PCT:
                xp = ep * (1 + TP_PCT * TP_PARTIAL)
                xt, xr = ts, "익절+5%"
                break

        if xp is None and len(after) > 0:
            xp = after.iloc[-1]["Close"]
            xt = after.index[-1]
            xr = "장마감"

        pnl = (xp / ep - 1) * 100 if xp and ep else 0

        tags = "기관" if ev["inst_ok"] else "기관X"
        if ev["kki_ok"]: tags += "+끼"
        if ev["chart_ok"]: tags += "+차트"
        if mom_ok: tags += "+모멘텀"

        w = "W" if pnl > 0 else "L"
        print(f"  {w} {curr_day[4:]}/{curr_day[6:]} {name:10s} | "
              f"[{tags}] 기관{ev['inst_net']/1e8:+,.0f}억 | "
              f"{str(et)[11:16]}→{str(xt)[11:16]} | "
              f"{pnl:+.2f}% ({xr}) | {mom_detail}")

        results.append({**dict(ev), "traded": True, "mom_ok": mom_ok,
                        "pnl": pnl, "exit_reason": xr})

    # 결과
    traded_r = [r for r in results if r["traded"]]
    if not traded_r:
        print("\n  매매 없음")
        return

    tdf = pd.DataFrame(traded_r)

    print(f"\n  ┌─── 5분봉 시뮬 결과 ───┐")
    tot = len(tdf)
    ws = (tdf["pnl"] > 0).sum()
    print(f"  │ 전체: {tot}건 | {ws}W {tot-ws}L | "
          f"WR {ws/tot*100:.0f}% | 평균 {tdf['pnl'].mean():+.2f}%")
    print(f"  │")

    # 기관O vs X
    for label, sub in [
        ("기관O", tdf[tdf["inst_ok"]]),
        ("기관X", tdf[~tdf["inst_ok"]]),
    ]:
        if len(sub) > 0:
            sw = (sub["pnl"] > 0).sum()
            print(f"  │ {label}: {len(sub):3d}건 | {sw}W {len(sub)-sw}L | "
                  f"WR {sw/len(sub)*100:.0f}% | 평균 {sub['pnl'].mean():+.2f}% | "
                  f"합계 {sub['pnl'].sum():+.1f}%")
    print(f"  │")

    # 기관O 내 보조조건
    inst_t = tdf[tdf["inst_ok"]]
    if len(inst_t) > 0:
        for label, mask in [
            ("기관+끼+차트", (inst_t["kki_ok"]) & (inst_t["chart_ok"])),
            ("기관+끼",     (inst_t["kki_ok"]) & (~inst_t["chart_ok"])),
            ("기관+차트",   (~inst_t["kki_ok"]) & (inst_t["chart_ok"])),
            ("기관만",      (~inst_t["kki_ok"]) & (~inst_t["chart_ok"])),
        ]:
            sub = inst_t[mask]
            if len(sub) > 0:
                sw = (sub["pnl"] > 0).sum()
                print(f"  │ {label:12s}: {len(sub):2d}건 | {sw}W {len(sub)-sw}L | "
                      f"평균 {sub['pnl'].mean():+.2f}%")

    # 모멘텀 필터
    print(f"  │")
    for label, sub in [
        ("모멘텀O", tdf[tdf["inst_ok"] & tdf["mom_ok"]]),
        ("모멘텀X", tdf[tdf["inst_ok"] & ~tdf["mom_ok"]]),
    ]:
        if len(sub) > 0:
            sw = (sub["pnl"] > 0).sum()
            print(f"  │ 기관O+{label}: {len(sub):2d}건 | "
                  f"WR {sw/len(sub)*100:.0f}% | 평균 {sub['pnl'].mean():+.2f}%")

    print(f"  └─────────────────────┘")


def main():
    t0 = time.time()
    events = phase1()
    phase2(events)

    elapsed = time.time() - t0
    print(f"\n  소요시간: {elapsed:.0f}초")

    # 최종 전략 제안
    if events:
        df = pd.DataFrame(events)
        traded = df[df["est_traded"]]

        print("\n" + "=" * 70)
        print("  최종 전략 제안: 기관 수급 중심 돌파매매")
        print("=" * 70)

        # 기관O 그룹
        inst_t = traded[traded["inst_ok"]]
        inst_n = traded[~traded["inst_ok"]]

        if len(inst_t) > 0 and len(inst_n) > 0:
            print(f"\n  기관O: {len(inst_t)}건, 평균 {inst_t['est_pnl'].mean():+.2f}%, "
                  f"승률 {(inst_t['est_pnl']>0).mean()*100:.0f}%")
            print(f"  기관X: {len(inst_n)}건, 평균 {inst_n['est_pnl'].mean():+.2f}%, "
                  f"승률 {(inst_n['est_pnl']>0).mean()*100:.0f}%")
            diff = inst_t['est_pnl'].mean() - inst_n['est_pnl'].mean()
            print(f"  차이: {diff:+.2f}%p")

        # 최적 조합
        print(f"\n  조합별 비교 (기관O 기반):")
        if len(inst_t) > 0:
            for label, mask in [
                ("기관O + 끼O + 차트O", (inst_t["kki_ok"]) & (inst_t["chart_ok"])),
                ("기관O + 끼O",         (inst_t["kki_ok"])),
                ("기관O + 차트O",       (inst_t["chart_ok"])),
                ("기관O (전체)",        pd.Series(True, index=inst_t.index)),
            ]:
                sub = inst_t[mask]
                if len(sub) >= 3:
                    avg = sub["est_pnl"].mean()
                    wr = (sub["est_pnl"] > 0).mean() * 100
                    print(f"    {label:24s}: {len(sub):3d}건 | "
                          f"평균 {avg:+.2f}% | 승률 {wr:.0f}%")

        print(f"\n  권장 전략:")
        print(f"    1. 전일 거래대금 TOP20 + 강세(+3%+)")
        print(f"    2. 전일 기관 순매수 > 0 (필수)")
        print(f"    3. 끼(과거 +15% 이력) 있으면 추가점수")
        print(f"    4. 10:00~11:00 돌파 진입 (5봉고점 + 거래량 1.5x)")
        print(f"    5. SL -4% / TP +5%")


if __name__ == "__main__":
    main()
