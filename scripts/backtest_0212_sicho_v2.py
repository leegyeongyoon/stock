"""
2026-02-12 백테스트 V2: 시초가매매 전일 조건 추가
홍인기 실제 조건:
  - 전일 대장주 (거래대금 TOP20)
  - 전일 장대양봉/상한가 (종가 > 시가*1.05, 거래대금 500억+)
  - 과열 필터 (전일 상한가 + 당일 갭 10%+ → 자제)
  - 전일 종가 = 지지선 (갭상승 후 전일종가까지 빠지면 지지 확인)
  - 분할매수 (1차 50%, 2차 50%)
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from datetime import datetime, timedelta
from dataclasses import dataclass, field

# ─── 설정 ───
TARGET_DATE = "20260212"
PREV_DATE = "20260211"
PREV_PREV_DATE = "20260210"  # 전전일 (2일 연속 확인용)

SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70
MAX_CONSECUTIVE_LOSS = 2
INIT_CAPITAL = 100_000_000

# 시초가매매 전용
SICHO_SL_PCT = -0.03
SICHO_TP_PCT = 0.04
GAP_UP_MIN = 0.02         # 갭상승 최소 2%
GAP_UP_OVERHEATED = 0.10   # 과열 기준: 전일 상한가 + 당일 갭 10%+
JANGDAE_MIN_CHANGE = 0.05  # 장대양봉 최소 등락률 5%
JANGDAE_MIN_VALUE = 50_000_000_000  # 장대양봉 최소 거래대금 500억

# KOSDAQ 종목 목록 (yfinance에서 .KQ 사용)
_kosdaq_set = None

def get_kosdaq_set():
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(TARGET_DATE, market="KOSDAQ"))
    return _kosdaq_set

def code_to_ticker(code: str) -> str:
    """종목코드 → yfinance 티커 (.KS 또는 .KQ)"""
    suffix = ".KQ" if code in get_kosdaq_set() else ".KS"
    return f"{code}{suffix}"


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
    note: str = ""


def analyze_prev_day():
    """전일(2/11) 분석: 대장주 + 장대양봉 + 수급"""
    print("=" * 60)
    print("1. 전일(2/11) 대장주·장대양봉 분석")
    print("=" * 60)

    df_prev = pykrx_stock.get_market_ohlcv_by_ticker(PREV_DATE, market="ALL")
    df_prev = df_prev[df_prev["거래량"] > 0]

    df_prev_prev = pykrx_stock.get_market_ohlcv_by_ticker(PREV_PREV_DATE, market="ALL")

    # 거래대금 TOP20 = 전일 대장주 후보
    top20 = df_prev.nlargest(20, "거래대금")

    print(f"\n  전일 거래대금 TOP20:")
    candidates = []
    for code in top20.index:
        row = df_prev.loc[code]
        name = pykrx_stock.get_market_ticker_name(code)

        open_p = row["시가"]
        close_p = row["종가"]
        high_p = row["고가"]
        volume = row["거래량"]
        value = row["거래대금"]
        change = row["등락률"]

        # 장대양봉 판정: 종가 > 시가 * 1.05 AND 거래대금 500억+
        is_jangdae = (close_p > open_p * (1 + JANGDAE_MIN_CHANGE) and
                      value >= JANGDAE_MIN_VALUE)

        # 상한가 판정 (코스피 30%, 코스닥 30%)
        is_sanghanga = change >= 29.0

        # 전전일 종가 대비 확인 (2일 연속 상승?)
        prev_prev_close = 0
        if code in df_prev_prev.index:
            prev_prev_close = df_prev_prev.loc[code, "종가"]

        # 수급: 외국인/기관 순매수 (pykrx에서 조회)
        foreign_net = 0
        inst_net = 0
        try:
            inv_data = pykrx_stock.get_market_trading_value_by_date(
                PREV_DATE, PREV_DATE, code
            )
            if not inv_data.empty:
                foreign_net = inv_data.iloc[0].get("외국인합계", 0)
                inst_net = inv_data.iloc[0].get("기관합계", 0)
        except Exception:
            pass

        tag = ""
        if is_sanghanga:
            tag = "상한가"
        elif is_jangdae:
            tag = "장대양봉"
        elif change >= 3.0:
            tag = "강세"

        candidates.append({
            "code": code,
            "name": name or code,
            "prev_close": close_p,
            "prev_open": open_p,
            "prev_high": high_p,
            "prev_change": change,
            "prev_value": value,
            "is_jangdae": is_jangdae,
            "is_sanghanga": is_sanghanga,
            "tag": tag,
            "foreign_net": foreign_net,
            "inst_net": inst_net,
        })

        mark = "*" if (is_jangdae or is_sanghanga) else " "
        print(f"  {mark} {name or code:12s} | {change:+6.1f}% | "
              f"거래대금 {value/1e8:,.0f}억 | {tag:6s} | "
              f"외국인 {foreign_net/1e8:+,.0f}억 기관 {inst_net/1e8:+,.0f}억")

    # D+1 시초가매매 후보: 장대양봉 또는 상한가
    d1_candidates = [c for c in candidates if c["is_jangdae"] or c["is_sanghanga"]]
    print(f"\n  → D+1 시초가매매 후보 (장대양봉/상한가): {len(d1_candidates)}개")
    for c in d1_candidates:
        print(f"    {c['name']:12s} | 전일 {c['prev_change']:+.1f}% | {c['tag']}")

    return candidates, d1_candidates, df_prev


def fetch_today_universe(d1_candidates, df_prev):
    """당일(2/12) 유니버스 구성 + 5분봉 수집"""
    print("\n" + "=" * 60)
    print("2. 당일(2/12) 유니버스 + 5분봉 수집")
    print("=" * 60)

    df_today = pykrx_stock.get_market_ohlcv_by_ticker(TARGET_DATE, market="ALL")
    df_today = df_today[df_today["거래량"] > 0]

    # D+1 후보 코드 (시초가매매용)
    d1_codes = {c["code"] for c in d1_candidates}

    # 당일 거래대금 TOP100 (돌파/눌림용)
    top100 = set(df_today.nlargest(100, "거래대금").index.tolist())

    # 등락률 +3% (당일 강세주)
    strong = set(df_today[df_today["등락률"] >= 3.0].index.tolist())

    # 전체 유니버스: D+1 후보 + TOP100 + 강세주
    universe = d1_codes | top100 | strong
    print(f"  D+1 후보: {len(d1_codes)}개")
    print(f"  TOP100 거래대금: {len(top100)}개")
    print(f"  등락률 +3%+: {len(strong)}개")
    print(f"  합집합: {len(universe)}개")

    # 5분봉 수집
    codes = list(universe)
    bars_dict = {}
    failed = 0
    batch_size = 20

    for batch_start in range(0, len(codes), batch_size):
        batch = codes[batch_start:batch_start + batch_size]
        tickers = [code_to_ticker(c) for c in batch]

        try:
            data = yf.download(
                " ".join(tickers), period="5d", interval="5m",
                progress=False, threads=True
            )
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

                    day_mask = df.index.date == pd.Timestamp("2026-02-12").date()
                    df_day = df[day_mask]

                    if len(df_day) >= 10:
                        bars_dict[code] = df_day
                except Exception:
                    failed += 1
        except Exception:
            failed += len(batch)

        done = batch_start + len(batch)
        if (done // batch_size) % 5 == 0 and done > 0:
            print(f"  진행: {done}/{len(codes)} ({len(bars_dict)}개 성공)")

    print(f"  완료: {len(bars_dict)}개 성공, {failed}개 실패")
    return bars_dict, df_today


def analyze_morning_flow(bars_dict, df_today):
    """9:00~9:30 수급 관찰 → 주도주 20개"""
    print("\n" + "=" * 60)
    print("3. 9:00~9:30 수급 관찰 (당일 주도주)")
    print("=" * 60)

    scores = []
    for code, df in bars_dict.items():
        morning = df[(df.index.hour == 9) & (df.index.minute < 30)]
        if len(morning) < 2:
            continue

        vol_sum = morning["Volume"].sum()
        price_change = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
        momentum = vol_sum * max(price_change, 0)

        name = pykrx_stock.get_market_ticker_name(code)
        scores.append({
            "code": code,
            "name": name or code,
            "momentum": momentum,
            "morning_change": price_change,
        })

    scores.sort(key=lambda x: x["momentum"], reverse=True)
    leaders = scores[:20]

    print(f"  주도주 TOP 10:")
    for i, s in enumerate(leaders[:10], 1):
        print(f"    {i:2d}. {s['name']:12s} | 오전 {s['morning_change']:+.1f}%")

    return {s["code"]: s for s in leaders}


def find_sicho_entry_v2(bars, candidate, df_today_row):
    """
    시초가매매 V2: 전일 조건 + 당일 갭 + 전일종가 지지

    조건:
    1. 전일 장대양봉/상한가 (analyze_prev_day에서 이미 필터)
    2. 당일 갭상승 2%+ (전일 종가 대비)
    3. 과열 아님 (전일 상한가 + 당일 갭 10%+ → 스킵)
    4. 진입: 갭상승 후 첫 눌림 → 전일종가 위에서 지지 확인 → 진입
    5. 손절: 전일종가 이탈 시
    """
    code = candidate["code"]
    name = candidate["name"]
    prev_close = candidate["prev_close"]

    if bars.empty or prev_close <= 0:
        return {"valid": False, "reason": "데이터 없음"}

    today_open = bars["Open"].iloc[0]
    gap_pct = (today_open / prev_close) - 1

    # 갭상승 2%+ 확인
    if gap_pct < 0.02:
        return {"valid": False, "reason": f"갭 {gap_pct*100:.1f}% < 2%"}

    # 과열 필터: 전일 상한가 + 당일 갭 10%+ → 자제
    if candidate["is_sanghanga"] and gap_pct >= GAP_UP_OVERHEATED:
        return {"valid": False, "reason": f"과열 (전일 상한가 + 갭 {gap_pct*100:.1f}%)"}

    # 9:00~9:25 구간에서 첫 눌림 찾기
    early = bars[(bars.index.hour == 9) & (bars.index.minute <= 25)]
    if len(early) < 2:
        return {"valid": False, "reason": "오전 데이터 부족"}

    first_bar = early.iloc[0]
    first_high = first_bar["High"]

    # 첫 봉이 음봉이면 → 갭상승 후 바로 하락 = 약세 신호
    if first_bar["Close"] < first_bar["Open"] * 0.995:
        return {"valid": False, "reason": "첫봉 음봉 (약세)"}

    # 눌림 찾기: 이후 봉에서 되돌림 발생
    for i in range(1, len(early)):
        bar = early.iloc[i]
        ts = early.index[i]

        # 전일종가 이탈 → 포기 (지지 실패)
        if bar["Low"] < prev_close * 0.99:
            return {"valid": False, "reason": "전일종가 이탈"}

        # 눌림 조건: 저가가 시가보다 낮고, 종가가 반등
        rise = first_high - today_open
        if rise <= 0:
            continue

        pullback_level = first_high - (rise * 0.3)  # 30% 되돌림

        if bar["Low"] <= pullback_level and bar["Close"] > pullback_level:
            # 전일종가 위에서 지지 확인
            if bar["Close"] > prev_close:
                return {
                    "valid": True,
                    "entry_price": bar["Close"],
                    "entry_time": ts,
                    "gap_pct": gap_pct,
                    "support": prev_close,
                    "sl_price": prev_close * 0.99,  # 전일종가 이탈 = 손절
                }

    # 9:00~9:25에서 눌림 없음 → 계속 상승 = 추격매수 위험
    return {"valid": False, "reason": "눌림 미발생 (추격 위험)"}


def find_breakout_entry(bars):
    """돌파매매: 9:30~11:00"""
    window = bars[
        ((bars.index.hour == 9) & (bars.index.minute >= 30)) |
        (bars.index.hour == 10)
    ]
    if len(window) < 3:
        return {"valid": False}

    for i in range(5, len(window)):
        prev_high = window["High"].iloc[i-5:i].max()
        bar = window.iloc[i]

        if bar["High"] > prev_high and bar["Close"] > prev_high:
            avg_vol = window["Volume"].iloc[i-5:i].mean()
            if avg_vol > 0 and bar["Volume"] >= avg_vol * 1.2:
                return {
                    "valid": True,
                    "entry_price": bar["Close"],
                    "entry_time": window.index[i],
                }

    return {"valid": False}


def find_pullback_entry(bars):
    """눌림매매: 13:00~14:30"""
    window = bars[
        (bars.index.hour >= 13) & (bars.index.hour < 15) &
        ~((bars.index.hour == 14) & (bars.index.minute > 30))
    ]
    if len(window) < 5:
        return {"valid": False}

    morning = bars[bars.index.hour < 12]
    if morning.empty:
        return {"valid": False}

    morning_high = morning["High"].max()
    morning_low = morning["Low"].min()
    range_50 = morning_high - (morning_high - morning_low) * 0.5

    for i in range(2, len(window)):
        bar = window.iloc[i]
        prev = window.iloc[i-1]

        if (prev["Low"] <= morning_high * 0.98 and
            bar["Close"] > prev["Close"] and
            bar["Close"] > range_50 and
            bar["Low"] > morning_low):
            return {
                "valid": True,
                "entry_price": bar["Close"],
                "entry_time": window.index[i],
            }

    return {"valid": False}


def simulate_trade(bars, entry_time, entry_price, method, code, name,
                   sl_pct=None, tp_pct=None, sl_price=None, note=""):
    """매매 시뮬레이션 (전일종가 기반 손절 지원)"""
    sl = sl_pct or (SICHO_SL_PCT if method == "시초가" else SL_PCT)
    tp = tp_pct or (SICHO_TP_PCT if method == "시초가" else TP_PCT)

    after_entry = bars[bars.index > entry_time]
    trade = Trade(
        code=code, name=name, method=method,
        entry_time=str(entry_time)[:16],
        entry_price=entry_price,
        note=note,
    )

    for ts, bar in after_entry.iterrows():
        # 전일종가 기반 손절 (시초가매매 전용)
        if sl_price and bar["Low"] <= sl_price:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = sl_price
            trade.pnl_pct = ((sl_price / entry_price) - 1) * 100
            trade.exit_reason = "전일종가 이탈"
            return trade

        pnl_low = (bar["Low"] / entry_price) - 1
        pnl_high = (bar["High"] / entry_price) - 1

        # % 기반 손절
        if pnl_low <= sl:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = entry_price * (1 + sl)
            trade.pnl_pct = sl * 100
            trade.exit_reason = "손절"
            return trade

        # 익절
        if pnl_high >= tp:
            partial_pnl = tp * TP_PARTIAL
            trade.exit_time = str(ts)[:16]
            trade.exit_price = entry_price * (1 + tp)
            trade.pnl_pct = partial_pnl * 100
            trade.exit_reason = "익절"
            return trade

    # 장마감
    if len(after_entry) > 0:
        last = after_entry.iloc[-1]
        trade.exit_time = str(after_entry.index[-1])[:16]
        trade.exit_price = last["Close"]
        trade.pnl_pct = ((last["Close"] / entry_price) - 1) * 100
        trade.exit_reason = "장마감"

    return trade


def run_backtest():
    print("\n" + "=" * 70)
    print("  홍인기 전략 백테스트 V2: 2026-02-12")
    print("  시초가매매 = 전일 대장주 + 장대양봉 + 갭상승 + 전일종가지지")
    print("=" * 70)

    # 1. 전일 분석
    all_candidates, d1_candidates, df_prev = analyze_prev_day()

    # 2. 당일 데이터
    bars_dict, df_today = fetch_today_universe(d1_candidates, df_prev)

    # 3. 수급 관찰
    leaders = analyze_morning_flow(bars_dict, df_today)
    leader_codes = set(leaders.keys())

    # ────────────────────────────────────────
    # 4. 시초가매매 (D+1: 전일 대장주 갭상승)
    # ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("4. 시초가매매 필터링 (전일 조건 적용)")
    print("=" * 60)

    sicho_results = []
    for cand in d1_candidates:
        code = cand["code"]
        name = cand["name"]

        if code not in bars_dict:
            print(f"  {name:12s} | 5분봉 없음")
            continue

        bars = bars_dict[code]
        today_row = df_today.loc[code] if code in df_today.index else None

        entry = find_sicho_entry_v2(bars, cand, today_row)

        if entry["valid"]:
            sicho_results.append({
                "code": code,
                "name": name,
                "cand": cand,
                **entry,
            })
            print(f"  O {name:12s} | 전일 {cand['prev_change']:+.1f}% ({cand['tag']}) | "
                  f"갭 +{entry['gap_pct']*100:.1f}% | 진입 {entry['entry_price']:,.0f}원 @ "
                  f"{str(entry['entry_time'])[11:16]} | 지지선 {entry['support']:,.0f}원")
        else:
            reason = entry.get("reason", "")
            print(f"  X {name:12s} | 전일 {cand['prev_change']:+.1f}% ({cand['tag']}) | {reason}")

    print(f"\n  → 시초가매매 진입 가능: {len(sicho_results)}개 / D+1 후보 {len(d1_candidates)}개")

    # ────────────────────────────────────────
    # 5. 매매 실행
    # ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("5. 매매 실행")
    print("=" * 60)

    all_trades = []
    consecutive_loss = 0
    traded_codes = set()

    # 5-A. 시초가매매
    print("\n  [A] 시초가매매 (D+1 전일 대장주)")
    if sicho_results:
        for sr in sorted(sicho_results, key=lambda x: -x["gap_pct"]):
            if consecutive_loss >= MAX_CONSECUTIVE_LOSS:
                print(f"    -- 2연패 정지")
                break

            code = sr["code"]
            name = sr["name"]
            bars = bars_dict[code]
            cand = sr["cand"]

            trade = simulate_trade(
                bars, sr["entry_time"], sr["entry_price"],
                "시초가", code, name,
                sl_price=sr["sl_price"],
                note=f"전일{cand['tag']} {cand['prev_change']:+.1f}%",
            )
            all_trades.append(trade)
            traded_codes.add(code)

            if trade.pnl_pct < 0:
                consecutive_loss += 1
            else:
                consecutive_loss = 0

            win = "W" if trade.pnl_pct > 0 else "L"
            print(f"    {win} {name:12s} | 전일{cand['tag']} {cand['prev_change']:+.1f}% | "
                  f"갭+{sr['gap_pct']*100:.1f}% | "
                  f"{trade.entry_time[11:]} → {trade.exit_time[11:]} | "
                  f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")
    else:
        print("    없음 (D+1 조건 미충족)")

    # 5-B. 돌파매매
    print(f"\n  [B] 돌파매매 (9:30~11:00)")
    if consecutive_loss < MAX_CONSECUTIVE_LOSS:
        for code in leader_codes:
            if code in traded_codes or code not in bars_dict:
                continue
            if consecutive_loss >= MAX_CONSECUTIVE_LOSS:
                print(f"    -- 2연패 정지")
                break

            bars = bars_dict[code]
            name = leaders[code]["name"]
            entry = find_breakout_entry(bars)

            if entry["valid"]:
                trade = simulate_trade(
                    bars, entry["entry_time"], entry["entry_price"],
                    "돌파", code, name,
                )
                all_trades.append(trade)
                traded_codes.add(code)

                if trade.pnl_pct < 0:
                    consecutive_loss += 1
                else:
                    consecutive_loss = 0

                win = "W" if trade.pnl_pct > 0 else "L"
                print(f"    {win} {name:12s} | "
                      f"{trade.entry_time[11:]} → {trade.exit_time[11:]} | "
                      f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")
    else:
        print(f"    -- 2연패 상태, 스킵")

    # 5-C. 눌림매매
    print(f"\n  [C] 눌림매매 (13:00~14:30)")
    if consecutive_loss < MAX_CONSECUTIVE_LOSS:
        for code in leader_codes:
            if code in traded_codes or code not in bars_dict:
                continue
            if consecutive_loss >= MAX_CONSECUTIVE_LOSS:
                print(f"    -- 2연패 정지")
                break

            bars = bars_dict[code]
            name = leaders[code]["name"]
            entry = find_pullback_entry(bars)

            if entry["valid"]:
                trade = simulate_trade(
                    bars, entry["entry_time"], entry["entry_price"],
                    "눌림", code, name,
                )
                all_trades.append(trade)
                traded_codes.add(code)

                if trade.pnl_pct < 0:
                    consecutive_loss += 1
                else:
                    consecutive_loss = 0

                win = "W" if trade.pnl_pct > 0 else "L"
                print(f"    {win} {name:12s} | "
                      f"{trade.entry_time[11:]} → {trade.exit_time[11:]} | "
                      f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")
    else:
        print(f"    -- 2연패 상태, 스킵")

    # ────────────────────────────────────────
    # 6. 결과
    # ────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  결과 요약")
    print("=" * 70)

    if not all_trades:
        print("  매매 없음")
        return

    total = len(all_trades)
    wins = [t for t in all_trades if t.pnl_pct > 0]
    losses = [t for t in all_trades if t.pnl_pct <= 0]
    total_pnl = sum(t.pnl_pct for t in all_trades)
    wr = len(wins) / total * 100

    print(f"\n  전체: {total}건 | {len(wins)}W {len(losses)}L | WR {wr:.1f}% | 수익 {total_pnl:+.2f}%")
    print(f"  {'─'*50}")

    for method_name in ["시초가", "돌파", "눌림"]:
        trades = [t for t in all_trades if t.method == method_name]
        if trades:
            m_pnl = sum(t.pnl_pct for t in trades)
            m_w = sum(1 for t in trades if t.pnl_pct > 0)
            print(f"  {method_name}: {len(trades)}건 | {m_w}W {len(trades)-m_w}L | "
                  f"WR {m_w/len(trades)*100:.0f}% | {m_pnl:+.2f}%")

    print(f"\n  상세:")
    print(f"  {'#':>2} {'방법':4s} {'종목':12s} {'진입':>6s} {'청산':>6s} {'수익률':>8s} {'사유':8s} {'비고'}")
    print(f"  {'-'*72}")
    for i, t in enumerate(all_trades, 1):
        print(f"  {i:2d} {t.method:4s} {t.name:12s} {t.entry_time[11:]:>6s} "
              f"{t.exit_time[11:]:>6s} {t.pnl_pct:+6.2f}% {t.exit_reason:8s} {t.note}")

    # V1 대비 비교
    print(f"\n  {'─'*50}")
    print(f"  V1 (갭만) 대비 V2 (전일조건) 비교:")
    print(f"  V1: 시초가매매 2건 전승 +3.81% (조건=갭3%만)")
    print(f"  V2: 시초가매매 {len([t for t in all_trades if t.method == '시초가'])}건 "
          f"(조건=전일대장+장대양봉+갭+전일종가지지)")

    sicho_trades = [t for t in all_trades if t.method == "시초가"]
    if sicho_trades:
        sicho_pnl = sum(t.pnl_pct for t in sicho_trades)
        sicho_w = sum(1 for t in sicho_trades if t.pnl_pct > 0)
        print(f"       → {sicho_w}W {len(sicho_trades)-sicho_w}L, {sicho_pnl:+.2f}%")

        filtered_out = len(d1_candidates) - len(sicho_results)
        print(f"       → 필터링으로 {filtered_out}개 위험 매매 제거")


if __name__ == "__main__":
    run_backtest()
