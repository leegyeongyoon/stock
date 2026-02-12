"""
다일 분석: 전일 대장주 D+1 시초가매매 패턴
Phase 1: pykrx 일봉 20일 → 장대양봉/상한가 다음날 갭/수익률 패턴
Phase 2: yfinance 5분봉 최근 5일 → 실제 시초가매매 시뮬레이션
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from datetime import datetime, timedelta
from collections import defaultdict

# ─── 설정 ───
JANGDAE_MIN_CHANGE = 0.05   # 장대양봉 5%+
JANGDAE_MIN_VALUE = 50_000_000_000  # 500억+
TOP_N = 20  # 거래대금 상위 N

SICHO_SL = -0.03
SICHO_TP = 0.04
DOLPA_SL = -0.04
DOLPA_TP = 0.05


def get_trading_days(end_date="20260212", n_days=25):
    """최근 n일의 거래일 목록"""
    # pykrx에서 거래일 가져오기
    start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=50)).strftime("%Y%m%d")
    days = pykrx_stock.get_previous_business_days(fromdate=start, todate=end_date)
    return [d.strftime("%Y%m%d") for d in days[-n_days:]]


def phase1_daily_pattern():
    """Phase 1: 일봉 기반 20일 패턴 분석"""
    print("=" * 70)
    print("  Phase 1: 전일 장대양봉/상한가 → 다음날 결과 (일봉 20일)")
    print("=" * 70)

    days = get_trading_days("20260212", n_days=22)  # 20일 + 여유

    all_events = []

    for i in range(1, len(days)):
        prev_day = days[i - 1]
        curr_day = days[i]

        # 전일 OHLCV
        df_prev = pykrx_stock.get_market_ohlcv_by_ticker(prev_day, market="ALL")
        df_prev = df_prev[df_prev["거래량"] > 0]

        # 당일 OHLCV
        df_curr = pykrx_stock.get_market_ohlcv_by_ticker(curr_day, market="ALL")
        df_curr = df_curr[df_curr["거래량"] > 0]

        # 전일 거래대금 TOP20
        top20 = df_prev.nlargest(TOP_N, "거래대금")

        for code in top20.index:
            row_prev = df_prev.loc[code]
            prev_open = row_prev["시가"]
            prev_close = row_prev["종가"]
            prev_change = row_prev["등락률"]
            prev_value = row_prev["거래대금"]

            # 장대양봉/상한가 판정
            is_jangdae = (prev_close > prev_open * (1 + JANGDAE_MIN_CHANGE) and
                          prev_value >= JANGDAE_MIN_VALUE)
            is_sanghanga = prev_change >= 29.0

            if not (is_jangdae or is_sanghanga):
                continue

            # 당일 데이터 확인
            if code not in df_curr.index:
                continue

            row_curr = df_curr.loc[code]
            curr_open = row_curr["시가"]
            curr_close = row_curr["종가"]
            curr_high = row_curr["고가"]
            curr_low = row_curr["저가"]
            curr_change = row_curr["등락률"]

            gap_pct = (curr_open / prev_close - 1) * 100
            day_pnl = curr_change  # 당일 등락률
            intraday_range = (curr_high / curr_low - 1) * 100 if curr_low > 0 else 0

            # 시초가 매수 → 종가 매도 시 수익률
            sicho_to_close = (curr_close / curr_open - 1) * 100

            # 고가 대비 (시초가에 사서 고가에 팔 수 있었는지)
            sicho_to_high = (curr_high / curr_open - 1) * 100

            # 저가 대비 (최대 손실)
            sicho_to_low = (curr_low / curr_open - 1) * 100

            name = pykrx_stock.get_market_ticker_name(code)
            tag = "상한가" if is_sanghanga else "장대양봉"

            all_events.append({
                "prev_day": prev_day,
                "curr_day": curr_day,
                "code": code,
                "name": name or code,
                "tag": tag,
                "prev_change": prev_change,
                "prev_value": prev_value,
                "gap_pct": gap_pct,
                "day_pnl": day_pnl,
                "sicho_to_close": sicho_to_close,
                "sicho_to_high": sicho_to_high,
                "sicho_to_low": sicho_to_low,
                "intraday_range": intraday_range,
            })

    # ── 결과 분석 ──
    print(f"\n  총 이벤트: {len(all_events)}건 (전일 TOP20 장대양봉/상한가)")
    if not all_events:
        return all_events

    df = pd.DataFrame(all_events)

    # 1) 갭상승 분포
    print(f"\n  ┌─── 갭 분포 ───┐")
    gap_up = df[df["gap_pct"] >= 2]
    gap_small = df[(df["gap_pct"] >= 0) & (df["gap_pct"] < 2)]
    gap_down = df[df["gap_pct"] < 0]
    print(f"  │ 갭상승 2%+: {len(gap_up):3d}건 ({len(gap_up)/len(df)*100:.0f}%)")
    print(f"  │ 소폭 0~2%:  {len(gap_small):3d}건 ({len(gap_small)/len(df)*100:.0f}%)")
    print(f"  │ 갭하락:      {len(gap_down):3d}건 ({len(gap_down)/len(df)*100:.0f}%)")
    print(f"  └──────────────┘")

    # 2) 갭상승 2%+ 종목의 당일 수익률
    print(f"\n  ┌─── 갭상승 2%+ 종목의 시초가 매수 → 결과 ───┐")
    if len(gap_up) > 0:
        print(f"  │ 시초가→종가 평균: {gap_up['sicho_to_close'].mean():+.2f}%")
        print(f"  │ 시초가→고가 평균: {gap_up['sicho_to_high'].mean():+.2f}% (최대 수익 가능)")
        print(f"  │ 시초가→저가 평균: {gap_up['sicho_to_low'].mean():+.2f}% (최대 손실)")
        print(f"  │ 종가 양수 비율:   {(gap_up['sicho_to_close'] > 0).sum()}/{len(gap_up)} "
              f"({(gap_up['sicho_to_close'] > 0).mean()*100:.0f}%)")
        print(f"  │ 종가 +3%+ 비율:  {(gap_up['sicho_to_close'] >= 3).sum()}/{len(gap_up)}")
        print(f"  │ 종가 -3%- 비율:  {(gap_up['sicho_to_close'] <= -3).sum()}/{len(gap_up)}")
    print(f"  └─────────────────────────────────────────┘")

    # 3) 상한가 vs 장대양봉 구분
    print(f"\n  ┌─── 전일 유형별 비교 ───┐")
    for tag in ["상한가", "장대양봉"]:
        sub = df[df["tag"] == tag]
        if len(sub) == 0:
            continue
        gap_up_sub = sub[sub["gap_pct"] >= 2]
        print(f"  │ [{tag}] 총 {len(sub)}건")
        print(f"  │   갭상승 2%+: {len(gap_up_sub)}건")
        if len(gap_up_sub) > 0:
            print(f"  │   시초가→종가: {gap_up_sub['sicho_to_close'].mean():+.2f}%")
            print(f"  │   시초가→저가: {gap_up_sub['sicho_to_low'].mean():+.2f}%")
        print(f"  │   전체 시초가→종가: {sub['sicho_to_close'].mean():+.2f}%")
    print(f"  └──────────────────────┘")

    # 4) 갭 크기별 수익률
    print(f"\n  ┌─── 갭 크기별 시초가→종가 수익률 ───┐")
    bins = [(-999, -2), (-2, 0), (0, 2), (2, 5), (5, 10), (10, 999)]
    labels = ["갭-2%이하", "갭-2~0%", "갭0~2%", "갭2~5%", "갭5~10%", "갭10%+"]
    for (lo, hi), label in zip(bins, labels):
        sub = df[(df["gap_pct"] >= lo) & (df["gap_pct"] < hi)]
        if len(sub) > 0:
            avg = sub["sicho_to_close"].mean()
            wr = (sub["sicho_to_close"] > 0).mean() * 100
            print(f"  │ {label:10s}: {len(sub):3d}건 | 평균 {avg:+.2f}% | 양수비율 {wr:.0f}%")
    print(f"  └──────────────────────────────────────┘")

    # 5) 수급별 (외국인/기관 순매수 여부)
    # pykrx에서 전일 수급 확인은 느려서 스킵, 대신 전일 등락률 크기별로
    print(f"\n  ┌─── 전일 등락률별 다음날 패턴 ───┐")
    change_bins = [(5, 10), (10, 20), (20, 30), (30, 100)]
    change_labels = ["5~10%", "10~20%", "20~30%", "30%+(상한가)"]
    for (lo, hi), label in zip(change_bins, change_labels):
        sub = df[(df["prev_change"] >= lo) & (df["prev_change"] < hi)]
        if len(sub) > 0:
            gap_avg = sub["gap_pct"].mean()
            stc_avg = sub["sicho_to_close"].mean()
            stl_avg = sub["sicho_to_low"].mean()
            print(f"  │ 전일 {label:12s}: {len(sub):3d}건 | 갭 {gap_avg:+.1f}% | "
                  f"시초→종가 {stc_avg:+.2f}% | 시초→저가 {stl_avg:+.2f}%")
    print(f"  └────────────────────────────────────┘")

    # 6) 개별 이벤트 (갭상승 2%+ 상세)
    print(f"\n  ┌─── 갭상승 2%+ 개별 이벤트 ───┐")
    if len(gap_up) > 0:
        for _, ev in gap_up.sort_values("curr_day").iterrows():
            win = "W" if ev["sicho_to_close"] > 0 else "L"
            print(f"  │ {win} {ev['curr_day'][:4]}-{ev['curr_day'][4:6]}-{ev['curr_day'][6:]} "
                  f"{ev['name']:10s} | 전일{ev['tag']} {ev['prev_change']:+.0f}% | "
                  f"갭 {ev['gap_pct']:+.1f}% | 시초→종가 {ev['sicho_to_close']:+.2f}% | "
                  f"시초→저가 {ev['sicho_to_low']:+.2f}%")
    print(f"  └──────────────────────────────┘")

    return all_events


def phase2_5min_simulation(events):
    """Phase 2: 최근 5일 5분봉 시초가매매 시뮬레이션"""
    print("\n" + "=" * 70)
    print("  Phase 2: 5분봉 시초가매매 시뮬레이션 (최근 5일)")
    print("=" * 70)

    # 갭상승 2%+ 이벤트만
    gap_events = [e for e in events if e["gap_pct"] >= 2.0]

    if not gap_events:
        print("  갭상승 2%+ 이벤트 없음")
        return

    # 최근 5일만 (yfinance 5분봉 한계)
    recent_days = sorted(set(e["curr_day"] for e in gap_events))[-5:]
    recent_events = [e for e in gap_events if e["curr_day"] in recent_days]

    print(f"  대상: {len(recent_events)}건 (최근 5일 갭상승 2%+)")

    # KOSDAQ 목록
    latest_day = recent_days[-1] if recent_days else "20260212"
    kosdaq_set = set(pykrx_stock.get_market_ticker_list(latest_day, market="KOSDAQ"))

    # 대상 종목 5분봉 다운로드
    target_codes = list(set(e["code"] for e in recent_events))
    tickers = []
    code_to_tick = {}
    for code in target_codes:
        suffix = ".KQ" if code in kosdaq_set else ".KS"
        tick = f"{code}{suffix}"
        tickers.append(tick)
        code_to_tick[code] = tick

    print(f"  5분봉 다운로드: {len(tickers)}개 종목...")

    bars_all = {}
    batch_size = 20
    for bs in range(0, len(tickers), batch_size):
        batch_tickers = tickers[bs:bs + batch_size]
        batch_codes = target_codes[bs:bs + batch_size]
        try:
            data = yf.download(
                " ".join(batch_tickers), period="5d", interval="5m",
                progress=False, threads=True
            )
            if data.empty:
                continue

            for code in batch_codes:
                tick = code_to_tick[code]
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if tick in data.columns.get_level_values(1):
                            df = data.xs(tick, level=1, axis=1).copy()
                        else:
                            continue
                    else:
                        df = data.copy()

                    df = df.dropna(subset=["Close"])
                    if df.empty:
                        continue

                    if df.index.tz is not None:
                        df.index = df.index.tz_convert("Asia/Seoul")
                    else:
                        df.index = df.index.tz_localize("UTC").tz_convert("Asia/Seoul")

                    bars_all[code] = df
                except Exception:
                    continue
        except Exception:
            continue

    print(f"  5분봉 수집 완료: {len(bars_all)}개")

    # 시뮬레이션
    print(f"\n  ┌─── 5분봉 시초가매매 시뮬레이션 ───┐")
    sim_results = []

    for ev in sorted(recent_events, key=lambda x: x["curr_day"]):
        code = ev["code"]
        name = ev["name"]
        curr_date = ev["curr_day"]

        if code not in bars_all:
            print(f"  │ - {curr_date[4:6]}/{curr_date[6:]} {name:10s} | 5분봉 없음")
            continue

        df = bars_all[code]
        target_date = pd.Timestamp(f"{curr_date[:4]}-{curr_date[4:6]}-{curr_date[6:]}").date()
        day_bars = df[df.index.date == target_date]

        if len(day_bars) < 5:
            print(f"  │ - {curr_date[4:6]}/{curr_date[6:]} {name:10s} | 데이터 부족")
            continue

        prev_close = ev["prev_change"]  # 이건 등락률이니까...
        # 전일 종가 역산: 시가 / (1 + gap_pct/100)
        today_open = day_bars["Open"].iloc[0]
        prev_close_price = today_open / (1 + ev["gap_pct"] / 100)

        # 9:00~9:25 눌림 진입 시도
        early = day_bars[(day_bars.index.hour == 9) & (day_bars.index.minute <= 25)]
        entry_price = None
        entry_time = None
        entry_reason = ""

        if len(early) >= 2:
            first_bar = early.iloc[0]
            first_high = first_bar["High"]

            # 첫 봉 음봉 체크
            if first_bar["Close"] < first_bar["Open"] * 0.995:
                entry_reason = "첫봉음봉"
            else:
                for j in range(1, len(early)):
                    bar = early.iloc[j]
                    # 전일종가 이탈 체크
                    if bar["Low"] < prev_close_price * 0.99:
                        entry_reason = "전일종가이탈"
                        break

                    rise = first_high - today_open
                    if rise <= 0:
                        continue
                    pullback_level = first_high - (rise * 0.3)

                    if bar["Low"] <= pullback_level and bar["Close"] > pullback_level:
                        if bar["Close"] > prev_close_price:
                            entry_price = bar["Close"]
                            entry_time = early.index[j]
                            break

                if entry_price is None and not entry_reason:
                    entry_reason = "눌림없음"
        else:
            entry_reason = "데이터부족"

        if entry_price is None:
            print(f"  │ - {curr_date[4:6]}/{curr_date[6:]} {name:10s} | "
                  f"전일 {ev['tag']} {ev['prev_change']:+.0f}% | 갭 {ev['gap_pct']:+.1f}% | "
                  f"진입불가 ({entry_reason})")
            sim_results.append({
                **ev, "traded": False, "reason": entry_reason,
                "pnl": 0, "exit_reason": "",
            })
            continue

        # SL/TP 시뮬
        after = day_bars[day_bars.index > entry_time]
        exit_price = None
        exit_time = None
        exit_reason = ""
        pnl = 0

        for ts, bar in after.iterrows():
            # 전일종가 이탈 손절
            if bar["Low"] <= prev_close_price * 0.99:
                exit_price = prev_close_price * 0.99
                exit_time = ts
                exit_reason = "전일종가이탈"
                break

            pnl_low = (bar["Low"] / entry_price) - 1
            pnl_high = (bar["High"] / entry_price) - 1

            if pnl_low <= SICHO_SL:
                exit_price = entry_price * (1 + SICHO_SL)
                exit_time = ts
                exit_reason = "손절-3%"
                break

            if pnl_high >= SICHO_TP:
                exit_price = entry_price * (1 + SICHO_TP * 0.7)  # 70% 익절
                exit_time = ts
                exit_reason = "익절+4%"
                break

        if exit_price is None and len(after) > 0:
            last = after.iloc[-1]
            exit_price = last["Close"]
            exit_time = after.index[-1]
            exit_reason = "장마감"

        if exit_price and entry_price:
            pnl = (exit_price / entry_price - 1) * 100

        win = "W" if pnl > 0 else "L"
        print(f"  │ {win} {curr_date[4:6]}/{curr_date[6:]} {name:10s} | "
              f"전일 {ev['tag']} {ev['prev_change']:+.0f}% | 갭 {ev['gap_pct']:+.1f}% | "
              f"{str(entry_time)[11:16]}→{str(exit_time)[11:16]} | "
              f"{pnl:+.2f}% ({exit_reason})")

        sim_results.append({
            **ev, "traded": True, "reason": "",
            "pnl": pnl, "exit_reason": exit_reason,
        })

    print(f"  └─────────────────────────────────────┘")

    # 시뮬 요약
    traded = [r for r in sim_results if r["traded"]]
    not_traded = [r for r in sim_results if not r["traded"]]

    print(f"\n  시뮬레이션 요약:")
    print(f"  총 갭상승 2%+ 이벤트: {len(sim_results)}건")
    print(f"  진입 성공: {len(traded)}건")
    print(f"  진입 불가: {len(not_traded)}건")

    if not_traded:
        reasons = defaultdict(int)
        for r in not_traded:
            reasons[r["reason"]] += 1
        print(f"  진입 불가 사유:")
        for reason, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {cnt}건")

    if traded:
        wins = [r for r in traded if r["pnl"] > 0]
        total_pnl = sum(r["pnl"] for r in traded)
        print(f"\n  매매 결과: {len(wins)}W {len(traded)-len(wins)}L | "
              f"WR {len(wins)/len(traded)*100:.0f}% | 총 {total_pnl:+.2f}%")
        print(f"  평균 수익: {total_pnl/len(traded):+.2f}%")


def main():
    events = phase1_daily_pattern()
    phase2_5min_simulation(events)

    # 최종 결론
    print("\n" + "=" * 70)
    print("  최종 분석 결론")
    print("=" * 70)
    if events:
        df = pd.DataFrame(events)
        gap_up = df[df["gap_pct"] >= 2]
        total = len(df)

        print(f"\n  20일간 전일 대장주(TOP20) 장대양봉/상한가: {total}건")
        print(f"  그 중 다음날 갭상승 2%+: {len(gap_up)}건 ({len(gap_up)/total*100:.0f}%)")

        if len(gap_up) > 0:
            # 시초가 매수 → 종가 매도
            avg_stc = gap_up["sicho_to_close"].mean()
            wr_stc = (gap_up["sicho_to_close"] > 0).mean() * 100
            avg_stl = gap_up["sicho_to_low"].mean()

            print(f"\n  갭상승 2%+ 종목 시초가 매수 시:")
            print(f"    → 종가까지 보유: 평균 {avg_stc:+.2f}%, 승률 {wr_stc:.0f}%")
            print(f"    → 장중 최대 손실: 평균 {avg_stl:+.2f}%")
            print(f"    → 결론: {'시초가매매 유효' if avg_stc > 0 and wr_stc >= 50 else '시초가매매 위험'}")


if __name__ == "__main__":
    main()
