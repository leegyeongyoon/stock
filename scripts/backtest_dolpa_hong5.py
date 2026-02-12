"""
홍인기 돌파매매 백테스트 - "완벽한 종목 5가지 조건"
20일 Daily 분석 + 5일 5분봉 시뮬레이션

5가지 조건:
  1. 끼 - 과거 60일 내 +20%/상한가 이력
  2. 차트 위치 - 전일종가 >= 20일고가 * 95% (전고점 돌파 근접)
  3. 거래대금 - 당일 TOP10 (테마 내 압도적)
  4. 기관 수급 - 기관(투신+연기금) 순매수 > 0
  5. 외국인 수급 - 외국인 순매수 > 0 (프로그램매매 대용)

돌파 진입: 10:00~11:00, 5봉 고점 돌파 + 거래량 1.5x
SL: -4%, TP: +5% (70% 부분익절)
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from datetime import datetime, timedelta
from collections import defaultdict
import time

# ─── 설정 ───
END_DATE = "20260212"
N_ANALYSIS_DAYS = 20
TOP_N = 20              # 거래대금 상위 N (후보풀)

SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70

# 조건 파라미터
KKI_LOOKBACK_DAYS = 90    # 끼 확인: 90일 lookback
KKI_MIN_CHANGE = 15.0     # +15% 이상 급등 이력
CHART_HIGH_DAYS = 20      # 20일 고가 대비
CHART_NEAR_PCT = 0.95     # 전일종가 >= 20일고가 * 95%
VALUE_TOP_N = 10          # 거래대금 TOP10

# KOSDAQ
_kosdaq_set = None


def get_kosdaq_set(date=END_DATE):
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(date, market="KOSDAQ"))
    return _kosdaq_set


def code_to_ticker(code: str) -> str:
    suffix = ".KQ" if code in get_kosdaq_set() else ".KS"
    return f"{code}{suffix}"


def get_trading_days(end_date, n_days):
    start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=n_days * 2)).strftime("%Y%m%d")
    days = pykrx_stock.get_previous_business_days(fromdate=start, todate=end_date)
    return [d.strftime("%Y%m%d") for d in days[-n_days:]]


# ─── 조건 체크 함수들 ───

def check_kki(code, daily_history):
    """조건1: 끼 - 과거 일봉에서 +15%/상한가 이력"""
    if code not in daily_history or not daily_history[code]:
        return False, ""

    records = daily_history[code]
    hits = []
    for date_str, change in records:
        if change >= KKI_MIN_CHANGE:
            hits.append((date_str, change))

    if hits:
        best = max(hits, key=lambda x: x[1])
        return True, f"{best[0]} +{best[1]:.0f}% ({len(hits)}회)"
    return False, ""


def check_chart_position(code, prev_day_close, high_20d):
    """조건2: 차트 위치 - 전일종가가 20일 고가의 95% 이상"""
    if high_20d <= 0 or prev_day_close <= 0:
        return False, ""

    ratio = prev_day_close / high_20d
    if ratio >= CHART_NEAR_PCT:
        return True, f"종가/20일고가 = {ratio*100:.0f}%"
    return False, ""


def check_value_rank(code, day_ohlcv):
    """조건3: 거래대금 TOP10"""
    if day_ohlcv is None or code not in day_ohlcv.index:
        return False, 0, ""

    top10 = day_ohlcv.nlargest(VALUE_TOP_N, "거래대금")
    if code in top10.index:
        rank = list(top10.index).index(code) + 1
        value = day_ohlcv.loc[code, "거래대금"]
        return True, rank, f"#{rank} ({value/1e8:,.0f}억)"
    return False, 99, ""


def check_institutional(code, date_str):
    """조건4: 기관 수급 (투신/연기금 순매수 > 0)"""
    try:
        inv = pykrx_stock.get_market_trading_value_by_date(date_str, date_str, code)
        if inv.empty:
            return False, 0, ""

        row = inv.iloc[0]
        inst_net = row.get("기관합계", 0)
        return inst_net > 0, inst_net, f"기관 {inst_net/1e8:+,.0f}억"
    except Exception:
        return False, 0, ""


def check_foreign(code, date_str):
    """조건5: 외국인 수급 (순매수 > 0)"""
    try:
        inv = pykrx_stock.get_market_trading_value_by_date(date_str, date_str, code)
        if inv.empty:
            return False, 0, ""

        row = inv.iloc[0]
        foreign_net = row.get("외국인합계", 0)
        return foreign_net > 0, foreign_net, f"외국인 {foreign_net/1e8:+,.0f}억"
    except Exception:
        return False, 0, ""


# ─── Phase 1: Daily 분석 ───

def phase1_daily_screening():
    """20일 Daily 스크리닝: 5가지 조건 체크"""
    print("=" * 70)
    print("  Phase 1: 돌파매매 5가지 조건 Daily 스크리닝 (20일)")
    print("=" * 70)

    # 거래일 목록 (분석 20일 + 끼확인용 90일 = 110일)
    all_days = get_trading_days(END_DATE, N_ANALYSIS_DAYS + KKI_LOOKBACK_DAYS + CHART_HIGH_DAYS)
    analysis_days = all_days[-N_ANALYSIS_DAYS:]

    print(f"  분석 기간: {analysis_days[0]} ~ {analysis_days[-1]} ({len(analysis_days)}일)")
    print(f"  끼 확인 lookback: {KKI_LOOKBACK_DAYS}일 / 차트 고가: {CHART_HIGH_DAYS}일")

    # 전체 일봉 데이터 캐시 (all_days 전체)
    print(f"\n  일봉 데이터 수집 중... ({len(all_days)}일)")
    daily_ohlcv = {}  # date_str -> DataFrame
    for i, day in enumerate(all_days):
        try:
            df = pykrx_stock.get_market_ohlcv_by_ticker(day, market="ALL")
            df = df[df["거래량"] > 0]
            daily_ohlcv[day] = df
        except Exception:
            pass
        if (i + 1) % 20 == 0:
            print(f"    {i+1}/{len(all_days)} 완료")

    print(f"  일봉 수집 완료: {len(daily_ohlcv)}일")

    # 끼 히스토리 빌드: 각 종목의 과거 급등 이력
    # 분석일 기준으로 lookback
    print(f"\n  끼 히스토리 빌드 중...")

    # 전체 이벤트 수집
    all_events = []

    for day_idx, curr_day in enumerate(analysis_days):
        # 전일 찾기
        curr_pos = all_days.index(curr_day)
        if curr_pos < 1:
            continue
        prev_day = all_days[curr_pos - 1]

        if prev_day not in daily_ohlcv or curr_day not in daily_ohlcv:
            continue

        df_prev = daily_ohlcv[prev_day]
        df_curr = daily_ohlcv[curr_day]

        # 전일 거래대금 TOP20 (후보풀)
        top20 = df_prev.nlargest(TOP_N, "거래대금")

        # 전일 강세주 필터: 등락률 +3% 이상
        strong_codes = [c for c in top20.index if df_prev.loc[c, "등락률"] >= 3.0]

        for code in strong_codes:
            name = pykrx_stock.get_market_ticker_name(code) or code
            prev_row = df_prev.loc[code]
            prev_close = prev_row["종가"]
            prev_change = prev_row["등락률"]
            prev_value = prev_row["거래대금"]

            # ── 조건 1: 끼 ──
            # lookback 기간의 일봉 확인
            lookback_start = max(0, curr_pos - KKI_LOOKBACK_DAYS)
            lookback_days = all_days[lookback_start:curr_pos - 1]  # 전일 제외 (전일 자체의 급등은 제외)

            kki_history = {}
            kki_records = []
            for ld in lookback_days:
                if ld in daily_ohlcv and code in daily_ohlcv[ld].index:
                    chg = daily_ohlcv[ld].loc[code, "등락률"]
                    if chg >= KKI_MIN_CHANGE:
                        kki_records.append((ld[4:6] + "/" + ld[6:], chg))
            kki_history[code] = kki_records

            kki_ok, kki_detail = check_kki(code, kki_history)

            # ── 조건 2: 차트 위치 ──
            high_days = all_days[max(0, curr_pos - CHART_HIGH_DAYS):curr_pos]
            high_20d = 0
            for hd in high_days:
                if hd in daily_ohlcv and code in daily_ohlcv[hd].index:
                    h = daily_ohlcv[hd].loc[code, "고가"]
                    if h > high_20d:
                        high_20d = h

            chart_ok, chart_detail = check_chart_position(code, prev_close, high_20d)

            # ── 조건 3: 거래대금 TOP10 ──
            value_ok, value_rank, value_detail = check_value_rank(code, df_prev)

            # ── 조건 4: 기관 수급 ──
            inst_ok, inst_net, inst_detail = check_institutional(code, prev_day)

            # ── 조건 5: 외국인 수급 ──
            foreign_ok, foreign_net, foreign_detail = check_foreign(code, prev_day)

            # 점수 합산
            score = sum([kki_ok, chart_ok, value_ok, inst_ok, foreign_ok])

            # 당일 결과 (돌파 시뮬용)
            curr_open = 0
            curr_close = 0
            curr_high = 0
            curr_low = 0
            curr_change = 0
            if code in df_curr.index:
                curr_row = df_curr.loc[code]
                curr_open = curr_row["시가"]
                curr_close = curr_row["종가"]
                curr_high = curr_row["고가"]
                curr_low = curr_row["저가"]
                curr_change = curr_row["등락률"]

            # 당일 10:00 매수 → 종가 매도 시뮬 (대략적)
            # 10시 시점 ≈ 시가~고가 중간점으로 추정, 종가 매도
            if curr_open > 0:
                # 돌파 진입 가격 ≈ 전일종가 * 1.03 (3% 돌파)
                est_entry = prev_close * 1.03
                if curr_high >= est_entry and est_entry > 0:
                    est_pnl = (curr_close / est_entry - 1) * 100
                    est_traded = True
                else:
                    est_pnl = 0
                    est_traded = False
            else:
                est_pnl = 0
                est_traded = False

            all_events.append({
                "prev_day": prev_day,
                "curr_day": curr_day,
                "code": code,
                "name": name,
                "prev_change": prev_change,
                "prev_value": prev_value,
                "score": score,
                "kki_ok": kki_ok,
                "chart_ok": chart_ok,
                "value_ok": value_ok,
                "inst_ok": inst_ok,
                "foreign_ok": foreign_ok,
                "kki_detail": kki_detail,
                "chart_detail": chart_detail,
                "value_detail": value_detail,
                "inst_detail": inst_detail,
                "foreign_detail": foreign_detail,
                "curr_change": curr_change,
                "curr_high": curr_high,
                "curr_low": curr_low,
                "curr_open": curr_open,
                "curr_close": curr_close,
                "prev_close": prev_close,
                "est_traded": est_traded,
                "est_pnl": est_pnl,
            })

        if (day_idx + 1) % 5 == 0:
            print(f"  분석 진행: {day_idx+1}/{len(analysis_days)}일 "
                  f"({len(all_events)}건)")

    print(f"\n  총 후보: {len(all_events)}건 (전일 TOP20 + 강세 3%+)")

    # ── 점수별 분석 ──
    if not all_events:
        return all_events

    df = pd.DataFrame(all_events)

    print(f"\n  ┌─── 점수 분포 ───┐")
    for s in range(6):
        sub = df[df["score"] == s]
        if len(sub) > 0:
            traded = sub[sub["est_traded"]]
            if len(traded) > 0:
                avg_pnl = traded["est_pnl"].mean()
                wr = (traded["est_pnl"] > 0).mean() * 100
                print(f"  │ {s}점: {len(sub):3d}건 | 돌파진입 {len(traded):3d}건 | "
                      f"평균 {avg_pnl:+.2f}% | 승률 {wr:.0f}%")
            else:
                print(f"  │ {s}점: {len(sub):3d}건 | 돌파진입 0건")
    print(f"  └────────────────┘")

    # 조건별 효과
    print(f"\n  ┌─── 개별 조건 효과 (돌파 진입한 경우만) ───┐")
    traded = df[df["est_traded"]]
    if len(traded) > 0:
        for cond_name, cond_col in [
            ("끼(급등이력)", "kki_ok"),
            ("차트위치(고가근접)", "chart_ok"),
            ("거래대금TOP10", "value_ok"),
            ("기관순매수+", "inst_ok"),
            ("외국인순매수+", "foreign_ok"),
        ]:
            yes = traded[traded[cond_col]]
            no = traded[~traded[cond_col]]
            if len(yes) > 0 and len(no) > 0:
                y_pnl = yes["est_pnl"].mean()
                y_wr = (yes["est_pnl"] > 0).mean() * 100
                n_pnl = no["est_pnl"].mean()
                n_wr = (no["est_pnl"] > 0).mean() * 100
                print(f"  │ {cond_name:16s} | "
                      f"O: {len(yes):3d}건 평균{y_pnl:+.2f}% WR{y_wr:.0f}% | "
                      f"X: {len(no):3d}건 평균{n_pnl:+.2f}% WR{n_wr:.0f}%")
            elif len(yes) > 0:
                y_pnl = yes["est_pnl"].mean()
                y_wr = (yes["est_pnl"] > 0).mean() * 100
                print(f"  │ {cond_name:16s} | "
                      f"O: {len(yes):3d}건 평균{y_pnl:+.2f}% WR{y_wr:.0f}% | "
                      f"X: 0건")
    print(f"  └─────────────────────────────────────────────────┘")

    # 고점수(4-5점) vs 저점수(0-2점) 비교
    print(f"\n  ┌─── 점수 그룹별 비교 ───┐")
    for label, lo, hi in [("4-5점 (완벽~근접)", 4, 5), ("3점 (보통)", 3, 3),
                           ("0-2점 (부족)", 0, 2)]:
        sub = traded[(traded["score"] >= lo) & (traded["score"] <= hi)]
        if len(sub) > 0:
            avg = sub["est_pnl"].mean()
            wr = (sub["est_pnl"] > 0).mean() * 100
            tot = sub["est_pnl"].sum()
            print(f"  │ {label:20s}: {len(sub):3d}건 | "
                  f"평균 {avg:+.2f}% | 승률 {wr:.0f}% | 합계 {tot:+.1f}%")
    print(f"  └───────────────────────┘")

    # 5점 만점 개별 이벤트
    perfect = df[df["score"] >= 4]
    if len(perfect) > 0:
        print(f"\n  ┌─── 4점 이상 종목 상세 ───┐")
        for _, ev in perfect.sort_values("curr_day").iterrows():
            conds = ""
            if ev["kki_ok"]: conds += "끼"
            if ev["chart_ok"]: conds += " 차트"
            if ev["value_ok"]: conds += " 대금"
            if ev["inst_ok"]: conds += " 기관"
            if ev["foreign_ok"]: conds += " 외인"

            entry_mark = "O" if ev["est_traded"] else "X"
            pnl_str = f"{ev['est_pnl']:+.1f}%" if ev["est_traded"] else "진입X"
            win = "W" if ev["est_pnl"] > 0 and ev["est_traded"] else ("L" if ev["est_traded"] else "-")

            print(f"  │ {win} {ev['curr_day'][4:]}/{ev['curr_day'][6:]} "
                  f"{ev['name']:10s} | {ev['score']}점 [{conds.strip()}] | "
                  f"전일 {ev['prev_change']:+.1f}% | 당일 {ev['curr_change']:+.1f}% | "
                  f"{pnl_str}")
        print(f"  └────────────────────────┘")

    return all_events


# ─── Phase 2: 5분봉 시뮬레이션 ───

def phase2_5min_simulation(events):
    """최근 5일 고점수 종목 5분봉 돌파 시뮬레이션"""
    print("\n" + "=" * 70)
    print("  Phase 2: 5분봉 돌파매매 시뮬레이션 (최근 5일)")
    print("=" * 70)

    if not events:
        print("  이벤트 없음")
        return

    df = pd.DataFrame(events)

    # 최근 5일
    recent_days = sorted(df["curr_day"].unique())[-5:]
    recent = df[df["curr_day"].isin(recent_days)]

    # 3점 이상만 시뮬 (비교를 위해 0-2점도 일부 포함)
    sim_targets = recent.copy()

    print(f"  대상: {len(sim_targets)}건 (최근 5일)")

    # 5분봉 다운로드
    target_codes = list(sim_targets["code"].unique())
    kosdaq_set = get_kosdaq_set()

    print(f"  5분봉 다운로드: {len(target_codes)}개 종목...")

    bars_all = {}
    batch_size = 20
    for bs in range(0, len(target_codes), batch_size):
        batch_codes = target_codes[bs:bs + batch_size]
        tickers = [code_to_ticker(c) for c in batch_codes]

        try:
            data = yf.download(
                " ".join(tickers), period="5d", interval="5m",
                progress=False, threads=True
            )
            if data.empty:
                continue

            for code in batch_codes:
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

    print(f"  5분봉 수집 완료: {len(bars_all)}개")

    # 시뮬레이션
    print(f"\n  ┌─── 5분봉 돌파매매 시뮬레이션 ───┐")

    sim_results = []
    for _, ev in sim_targets.sort_values(["curr_day", "score"], ascending=[True, False]).iterrows():
        code = ev["code"]
        name = ev["name"]
        curr_day = ev["curr_day"]
        score = ev["score"]
        prev_close = ev["prev_close"]

        if code not in bars_all:
            continue

        all_bars = bars_all[code]
        target_date = pd.Timestamp(f"{curr_day[:4]}-{curr_day[4:6]}-{curr_day[6:]}").date()
        day_bars = all_bars[all_bars.index.date == target_date]

        if len(day_bars) < 10:
            continue

        # ── 오전 모멘텀 체크 (조건4 프로그램매매 대용) ──
        morning = day_bars[
            ((day_bars.index.hour == 9) & (day_bars.index.minute >= 30)) |
            ((day_bars.index.hour == 10) & (day_bars.index.minute == 0))
        ]

        morning_momentum_ok = False
        morning_detail = ""
        if len(morning) >= 3:
            bullish_count = sum(1 for _, b in morning.iterrows() if b["Close"] >= b["Open"])
            bullish_ratio = bullish_count / len(morning)
            price_chg = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
            morning_momentum_ok = bullish_ratio >= 0.5 and price_chg > 0
            morning_detail = f"양봉{bullish_ratio*100:.0f}% {price_chg:+.1f}%"

        # ── 돌파 진입 (10:00~11:00) ──
        window = day_bars[
            (day_bars.index.hour == 10) |
            ((day_bars.index.hour == 11) & (day_bars.index.minute == 0))
        ]

        entry = None
        if len(window) >= 6:
            for i in range(5, len(window)):
                prev_5_high = window["High"].iloc[i-5:i].max()
                bar = window.iloc[i]

                if bar["High"] > prev_5_high and bar["Close"] > prev_5_high:
                    avg_vol = window["Volume"].iloc[i-5:i].mean()
                    if avg_vol > 0 and bar["Volume"] >= avg_vol * 1.5:
                        entry = {
                            "entry_price": bar["Close"],
                            "entry_time": window.index[i],
                        }
                        break

        if entry is None:
            sim_results.append({
                **dict(ev), "traded": False,
                "morning_ok": morning_momentum_ok,
                "pnl": 0, "exit_reason": "진입불가",
            })
            continue

        # ── SL/TP 시뮬레이션 ──
        entry_price = entry["entry_price"]
        entry_time = entry["entry_time"]
        after = day_bars[day_bars.index > entry_time]

        exit_price = None
        exit_time = None
        exit_reason = ""

        for ts, bar in after.iterrows():
            pnl_low = (bar["Low"] / entry_price) - 1
            pnl_high = (bar["High"] / entry_price) - 1

            if pnl_low <= SL_PCT:
                exit_price = entry_price * (1 + SL_PCT)
                exit_time = ts
                exit_reason = "손절-4%"
                break

            if pnl_high >= TP_PCT:
                exit_price = entry_price * (1 + TP_PCT * TP_PARTIAL)
                exit_time = ts
                exit_reason = "익절+5%"
                break

        if exit_price is None and len(after) > 0:
            last = after.iloc[-1]
            exit_price = last["Close"]
            exit_time = after.index[-1]
            exit_reason = "장마감"

        pnl = 0
        if exit_price and entry_price:
            pnl = (exit_price / entry_price - 1) * 100

        total_score = score + (1 if morning_momentum_ok else 0)  # 6점 만점

        conds = ""
        if ev["kki_ok"]: conds += "끼"
        if ev["chart_ok"]: conds += " 차트"
        if ev["value_ok"]: conds += " 대금"
        if ev["inst_ok"]: conds += " 기관"
        if ev["foreign_ok"]: conds += " 외인"
        if morning_momentum_ok: conds += " 모멘텀"

        win = "W" if pnl > 0 else "L"
        print(f"  │ {win} {curr_day[4:6]}/{curr_day[6:]} "
              f"{name:10s} | {total_score}점 [{conds.strip()}] | "
              f"{str(entry_time)[11:16]}→{str(exit_time)[11:16]} | "
              f"{pnl:+.2f}% ({exit_reason}) | {morning_detail}")

        sim_results.append({
            **dict(ev), "traded": True,
            "morning_ok": morning_momentum_ok,
            "total_score": total_score,
            "pnl": pnl, "exit_reason": exit_reason,
            "entry_time": str(entry_time),
            "exit_time_str": str(exit_time),
        })

    print(f"  └─────────────────────────────────┘")

    # ── 시뮬 결과 요약 ──
    traded = [r for r in sim_results if r["traded"]]
    if not traded:
        print("\n  매매 없음")
        return

    tdf = pd.DataFrame(traded)

    print(f"\n  ┌─── 시뮬레이션 결과 요약 ───┐")
    total = len(tdf)
    wins = (tdf["pnl"] > 0).sum()
    total_pnl = tdf["pnl"].sum()
    avg_pnl = tdf["pnl"].mean()
    print(f"  │ 전체: {total}건 | {wins}W {total-wins}L | "
          f"WR {wins/total*100:.0f}% | 평균 {avg_pnl:+.2f}% | 합계 {total_pnl:+.1f}%")
    print(f"  │")

    # 점수별 (daily 5점 기준)
    for label, lo, hi in [("4-5점(완벽)", 4, 5), ("3점(보통)", 3, 3), ("0-2점(부족)", 0, 2)]:
        sub = tdf[(tdf["score"] >= lo) & (tdf["score"] <= hi)]
        if len(sub) > 0:
            sw = (sub["pnl"] > 0).sum()
            sa = sub["pnl"].mean()
            st = sub["pnl"].sum()
            print(f"  │ {label:14s}: {len(sub):3d}건 | {sw}W {len(sub)-sw}L | "
                  f"WR {sw/len(sub)*100:.0f}% | 평균 {sa:+.2f}% | 합계 {st:+.1f}%")
    print(f"  │")

    # 오전 모멘텀 O vs X
    mom_yes = tdf[tdf["morning_ok"]]
    mom_no = tdf[~tdf["morning_ok"]]
    if len(mom_yes) > 0:
        print(f"  │ 오전모멘텀 O: {len(mom_yes):3d}건 | "
              f"WR {(mom_yes['pnl']>0).mean()*100:.0f}% | 평균 {mom_yes['pnl'].mean():+.2f}%")
    if len(mom_no) > 0:
        print(f"  │ 오전모멘텀 X: {len(mom_no):3d}건 | "
              f"WR {(mom_no['pnl']>0).mean()*100:.0f}% | 평균 {mom_no['pnl'].mean():+.2f}%")

    print(f"  └───────────────────────────┘")

    # ── 기존 단순 돌파 vs 5가지 조건 비교 ──
    print(f"\n  ┌─── 기존 단순 돌파 vs 홍인기 5조건 ───┐")
    simple = tdf  # 전체 = 단순 돌파 (조건 없이 진입)
    filtered = tdf[tdf["score"] >= 3]  # 3점 이상만
    strict = tdf[tdf["score"] >= 4]    # 4점 이상만

    for label, sub in [("단순돌파(전체)", simple), ("3점이상", filtered), ("4점이상", strict)]:
        if len(sub) > 0:
            sw = (sub["pnl"] > 0).sum()
            sa = sub["pnl"].mean()
            st = sub["pnl"].sum()
            print(f"  │ {label:14s}: {len(sub):3d}건 | {sw}W {len(sub)-sw}L | "
                  f"WR {sw/len(sub)*100:.0f}% | 평균 {sa:+.2f}%")
        else:
            print(f"  │ {label:14s}: 0건")
    print(f"  └────────────────────────────────────┘")


# ─── Main ───

def main():
    t0 = time.time()

    events = phase1_daily_screening()
    phase2_5min_simulation(events)

    elapsed = time.time() - t0
    print(f"\n  소요시간: {elapsed:.0f}초")

    # 최종 결론
    print("\n" + "=" * 70)
    print("  최종 결론")
    print("=" * 70)
    if events:
        df = pd.DataFrame(events)
        traded = df[df["est_traded"]]

        print(f"\n  20일간 분석:")
        print(f"  총 후보: {len(df)}건 (전일 TOP20 강세주)")
        print(f"  돌파 진입 가능: {len(traded)}건")

        for s in [5, 4, 3]:
            sub = traded[traded["score"] >= s]
            if len(sub) > 0:
                avg = sub["est_pnl"].mean()
                wr = (sub["est_pnl"] > 0).mean() * 100
                print(f"  {s}점 이상만 매매 시: {len(sub)}건, "
                      f"평균 {avg:+.2f}%, 승률 {wr:.0f}%")

        print(f"\n  결론: 점수가 높을수록 수익률이 좋은지?")
        for s in range(6):
            sub = traded[traded["score"] == s]
            if len(sub) >= 3:
                print(f"    {s}점: {len(sub)}건, 평균 {sub['est_pnl'].mean():+.2f}%, "
                      f"승률 {(sub['est_pnl']>0).mean()*100:.0f}%")


if __name__ == "__main__":
    main()
