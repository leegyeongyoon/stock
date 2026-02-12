"""
2026-02-12 백테스트: 시초가매매 로직 추가
홍인기 전략 3가지 매매 기법:
  A) 시초가매매 (9:05~9:15): 갭상승 종목 첫 눌림 진입
  B) 돌파매매 (9:30~11:00): 오전 골든타임 전고점 돌파
  C) 눌림매매 (13:00~14:30): 오후 되돌림 지지선 진입
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
PREV_DATE = "20260211"  # 전일 종가 비교용
SL_PCT = -0.04       # 손절 -4%
TP_PCT = 0.05        # 익절 +5%
TP_PARTIAL = 0.70    # 1차 익절 비중 70%
MAX_POS_PCT = 0.30   # 최대 비중 30%
MAX_CONSECUTIVE_LOSS = 2  # 2연패 정지
INIT_CAPITAL = 100_000_000  # 1억

# 시초가매매 전용 설정
GAP_UP_THRESHOLD = 0.03    # 갭상승 기준 3%+
SICHO_SL_PCT = -0.03       # 시초가매매 손절 -3% (빠른 매매)
SICHO_TP_PCT = 0.04        # 시초가매매 익절 +4%
SICHO_PULLBACK_RATIO = 0.4 # 첫 봉 상승의 40%+ 되돌림 시 진입


@dataclass
class Trade:
    code: str
    name: str
    method: str  # "시초가" / "돌파" / "눌림"
    entry_time: str
    entry_price: float
    exit_time: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    partial_sold: bool = False


def fetch_universe():
    """거래대금 TOP100 + 등락률 +3% 강세주 → 주도주 유니버스"""
    print("=" * 60)
    print("1. 유니버스 구성 (거래대금 TOP100 + 강세주)")
    print("=" * 60)

    # 거래대금 TOP 100
    df_market = pykrx_stock.get_market_ohlcv_by_ticker(TARGET_DATE, market="ALL")
    df_market = df_market[df_market["거래량"] > 0]
    top100 = df_market.nlargest(100, "거래대금")

    # 등락률 +3% 이상 (당일 강세주)
    strong = df_market[df_market["등락률"] >= 3.0]

    # 합집합
    universe_codes = set(top100.index.tolist()) | set(strong.index.tolist())
    print(f"  TOP100 거래대금: {len(top100)}개")
    print(f"  등락률 +3%+: {len(strong)}개")
    print(f"  합집합 유니버스: {len(universe_codes)}개")

    # 전일 종가 가져오기
    df_prev = pykrx_stock.get_market_ohlcv_by_ticker(PREV_DATE, market="ALL")

    return universe_codes, df_market, df_prev


def analyze_morning_flow(bars_dict: dict, df_market: pd.DataFrame):
    """9:00~9:30 수급 관찰 → 주도주 20개 선별"""
    print("\n" + "=" * 60)
    print("2. 9:00~9:30 수급 관찰 (주도주 선별)")
    print("=" * 60)

    morning_scores = []
    for code, df in bars_dict.items():
        # 9:00~9:30 데이터만
        morning = df[(df.index.hour == 9) & (df.index.minute < 30)]
        if len(morning) < 2:
            continue

        # 수급 점수: 거래량 * 등락률
        vol_sum = morning["Volume"].sum()
        price_change = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
        momentum = vol_sum * max(price_change, 0)  # 양의 모멘텀만

        name = pykrx_stock.get_market_ticker_name(code)
        morning_scores.append({
            "code": code,
            "name": name or code,
            "morning_volume": vol_sum,
            "morning_change": price_change,
            "momentum_score": momentum,
            "market_change": df_market.loc[code, "등락률"] if code in df_market.index else 0,
        })

    # 모멘텀 점수 TOP 20
    morning_scores.sort(key=lambda x: x["momentum_score"], reverse=True)
    leaders = morning_scores[:20]

    print(f"\n  주도주 TOP 20:")
    for i, s in enumerate(leaders[:10], 1):
        print(f"    {i:2d}. {s['name']:12s} | 오전수익 {s['morning_change']:+.1f}% | 모멘텀 {s['momentum_score']:,.0f}")

    return {s["code"]: s for s in leaders}


def detect_gap_up(code: str, bars: pd.DataFrame, prev_close: float) -> dict:
    """갭상승 감지: 시가 vs 전일종가"""
    if bars.empty or prev_close <= 0:
        return {"is_gap": False}

    open_price = bars["Open"].iloc[0]
    gap_pct = (open_price / prev_close) - 1

    return {
        "is_gap": gap_pct >= GAP_UP_THRESHOLD,
        "gap_pct": gap_pct,
        "open_price": open_price,
        "prev_close": prev_close,
    }


def find_sicho_entry(bars: pd.DataFrame, gap_info: dict) -> dict:
    """
    시초가매매 진입 로직:
    - 9:00~9:05 첫 봉 상승 확인
    - 9:05~9:15 첫 눌림(되돌림) 대기
    - 눌림 후 다시 반등 시 진입
    - 눌림이 시가 아래로 가면 포기
    """
    # 9:00~9:15 데이터
    early = bars[(bars.index.hour == 9) & (bars.index.minute <= 15)]
    if len(early) < 2:
        return {"valid": False, "reason": "데이터 부족"}

    open_price = gap_info["open_price"]
    first_bar = early.iloc[0]
    first_high = first_bar["High"]
    first_close = first_bar["Close"]

    # 첫 봉이 양봉이어야 함 (시가 대비 상승)
    if first_close < open_price:
        return {"valid": False, "reason": "첫봉 음봉"}

    # 9:05~ 바들에서 눌림 찾기
    after_first = early.iloc[1:]
    if len(after_first) == 0:
        return {"valid": False, "reason": "눌림 데이터 없음"}

    for i, (ts, bar) in enumerate(after_first.iterrows()):
        # 눌림 조건: 저가가 첫 봉 상승분의 40%+ 되돌림
        rise = first_high - open_price
        if rise <= 0:
            return {"valid": False, "reason": "상승폭 없음"}

        pullback_level = first_high - (rise * SICHO_PULLBACK_RATIO)

        # 저가가 눌림 수준까지 내려왔고, 종가가 다시 반등
        if bar["Low"] <= pullback_level and bar["Close"] > pullback_level:
            # 시가 아래로 깊이 빠지면 포기
            if bar["Low"] < open_price * 0.99:
                return {"valid": False, "reason": "시가 이탈"}

            return {
                "valid": True,
                "entry_price": bar["Close"],
                "entry_time": ts,
                "pullback_low": bar["Low"],
                "first_high": first_high,
            }

    # 9:05~9:15에 눌림 없이 계속 상승 → 9:15 이후 첫 눌림 체크
    bars_915_930 = bars[(bars.index.hour == 9) & (bars.index.minute > 15) & (bars.index.minute < 30)]
    for ts, bar in bars_915_930.iterrows():
        rise = first_high - open_price
        if rise <= 0:
            break
        pullback_level = first_high - (rise * SICHO_PULLBACK_RATIO)
        if bar["Low"] <= pullback_level and bar["Close"] > pullback_level:
            if bar["Low"] < open_price * 0.99:
                return {"valid": False, "reason": "시가 이탈 (9:15-9:30)"}
            return {
                "valid": True,
                "entry_price": bar["Close"],
                "entry_time": ts,
                "pullback_low": bar["Low"],
                "first_high": first_high,
            }

    return {"valid": False, "reason": "눌림 미발생"}


def find_breakout_entry(bars: pd.DataFrame) -> dict:
    """돌파매매: 9:30~11:00 전고점 돌파"""
    window = bars[
        ((bars.index.hour == 9) & (bars.index.minute >= 30)) |
        (bars.index.hour == 10)
    ]
    if len(window) < 3:
        return {"valid": False}

    # 진입 전 5봉 고점 돌파
    for i in range(5, len(window)):
        prev_high = window["High"].iloc[i-5:i].max()
        bar = window.iloc[i]

        if bar["High"] > prev_high and bar["Close"] > prev_high:
            # 거래량 확인: 직전 5봉 평균 대비 1.2x+
            avg_vol = window["Volume"].iloc[i-5:i].mean()
            if avg_vol > 0 and bar["Volume"] >= avg_vol * 1.2:
                return {
                    "valid": True,
                    "entry_price": bar["Close"],
                    "entry_time": window.index[i],
                    "breakout_level": prev_high,
                }

    return {"valid": False}


def find_pullback_entry(bars: pd.DataFrame) -> dict:
    """눌림매매: 13:00~14:30 되돌림 지지"""
    window = bars[
        (bars.index.hour >= 13) & (bars.index.hour < 15) &
        ~((bars.index.hour == 14) & (bars.index.minute > 30))
    ]
    if len(window) < 5:
        return {"valid": False}

    # 오전 고점
    morning = bars[bars.index.hour < 12]
    if morning.empty:
        return {"valid": False}
    morning_high = morning["High"].max()
    morning_low = morning["Low"].min()
    range_50 = morning_high - (morning_high - morning_low) * 0.5

    for i in range(2, len(window)):
        bar = window.iloc[i]
        prev = window.iloc[i-1]

        # 되돌림 후 반등: 저가가 50% 수준까지 내려왔다가 종가 반등
        if (prev["Low"] <= morning_high * 0.98 and
            bar["Close"] > prev["Close"] and
            bar["Close"] > range_50 and
            bar["Low"] > morning_low):
            return {
                "valid": True,
                "entry_price": bar["Close"],
                "entry_time": window.index[i],
                "support_level": prev["Low"],
            }

    return {"valid": False}


def simulate_trade(bars: pd.DataFrame, entry_time, entry_price: float,
                   method: str, code: str, name: str) -> Trade:
    """진입 후 SL/TP 시뮬레이션"""
    sl = SICHO_SL_PCT if method == "시초가" else SL_PCT
    tp = SICHO_TP_PCT if method == "시초가" else TP_PCT

    after_entry = bars[bars.index > entry_time]
    trade = Trade(
        code=code, name=name, method=method,
        entry_time=str(entry_time)[:16],
        entry_price=entry_price,
    )

    for ts, bar in after_entry.iterrows():
        pnl_high = (bar["High"] / entry_price) - 1
        pnl_low = (bar["Low"] / entry_price) - 1
        pnl_close = (bar["Close"] / entry_price) - 1

        # 손절 체크 (저가 기준)
        if pnl_low <= sl:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = entry_price * (1 + sl)
            trade.pnl_pct = sl * 100
            trade.exit_reason = "손절"
            return trade

        # 익절 체크 (고가 기준)
        if pnl_high >= tp:
            # 70% 익절 + 30% 본전컷 시나리오 → 평균 수익
            partial_pnl = tp * TP_PARTIAL
            remain_pnl = 0.0  # 본전컷 가정
            total_pnl = partial_pnl + remain_pnl * (1 - TP_PARTIAL)
            trade.exit_time = str(ts)[:16]
            trade.exit_price = entry_price * (1 + tp)
            trade.pnl_pct = total_pnl * 100
            trade.exit_reason = "익절"
            trade.partial_sold = True
            return trade

    # 장 마감 시 청산
    if len(after_entry) > 0:
        last = after_entry.iloc[-1]
        trade.exit_time = str(after_entry.index[-1])[:16]
        trade.exit_price = last["Close"]
        trade.pnl_pct = ((last["Close"] / entry_price) - 1) * 100
        trade.exit_reason = "장마감"

    return trade


def fetch_5min_data(codes: list) -> dict:
    """yfinance로 5분봉 데이터 수집"""
    print("\n" + "=" * 60)
    print("3. 5분봉 데이터 수집 (yfinance)")
    print("=" * 60)

    bars_dict = {}
    failed = 0
    batch_size = 20

    for batch_start in range(0, len(codes), batch_size):
        batch = codes[batch_start:batch_start + batch_size]
        tickers = [f"{c}.KS" for c in batch]
        ticker_str = " ".join(tickers)

        try:
            data = yf.download(
                ticker_str, period="5d", interval="5m",
                progress=False, threads=True
            )
            if data.empty:
                failed += len(batch)
                continue

            for code in batch:
                ticker = f"{code}.KS"
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

                    # UTC → KST 변환
                    if df.index.tz is not None:
                        df.index = df.index.tz_convert("Asia/Seoul")
                    else:
                        df.index = df.index.tz_localize("UTC").tz_convert("Asia/Seoul")

                    # 2/12 데이터만
                    day_mask = df.index.date == pd.Timestamp("2026-02-12").date()
                    df_day = df[day_mask]

                    if len(df_day) >= 10:
                        bars_dict[code] = df_day
                except Exception:
                    failed += 1
                    continue

        except Exception as e:
            print(f"  배치 다운로드 실패: {e}")
            failed += len(batch)

        if (batch_start // batch_size + 1) % 5 == 0:
            print(f"  진행: {batch_start + len(batch)}/{len(codes)} ({len(bars_dict)}개 성공)")

    print(f"  완료: {len(bars_dict)}개 성공, {failed}개 실패")
    return bars_dict


def run_backtest():
    """전체 백테스트 실행"""
    print("\n" + "=" * 70)
    print("  홍인기 전략 백테스트: 2026-02-12 (시초가매매 추가)")
    print("=" * 70)

    # 1. 유니버스
    universe_codes, df_market, df_prev = fetch_universe()

    # 2. 5분봉 수집
    bars_dict = fetch_5min_data(list(universe_codes))

    # 3. 9:00~9:30 수급 관찰
    leaders = analyze_morning_flow(bars_dict, df_market)
    leader_codes = set(leaders.keys())

    # 4. 갭상승 종목 식별 + 시초가매매 시그널
    print("\n" + "=" * 60)
    print("4. 갭상승 감지 + 시초가매매 시그널")
    print("=" * 60)

    gap_stocks = []
    sicho_entries = []

    for code in leader_codes:
        if code not in bars_dict or code not in df_prev.index:
            continue

        bars = bars_dict[code]
        prev_close = df_prev.loc[code, "종가"]
        name = leaders[code]["name"]

        gap = detect_gap_up(code, bars, prev_close)
        if gap["is_gap"]:
            gap_stocks.append({
                "code": code,
                "name": name,
                "gap_pct": gap["gap_pct"] * 100,
                "prev_close": prev_close,
                "open_price": gap["open_price"],
            })

            # 시초가매매 진입점 찾기
            entry = find_sicho_entry(bars, gap)
            if entry["valid"]:
                sicho_entries.append({
                    "code": code,
                    "name": name,
                    "gap_pct": gap["gap_pct"] * 100,
                    **entry,
                })
            else:
                print(f"  {name}: 갭 +{gap['gap_pct']*100:.1f}% → 시초가매매 불가 ({entry.get('reason', '')})")

    print(f"\n  갭상승 종목 (3%+): {len(gap_stocks)}개")
    for g in sorted(gap_stocks, key=lambda x: -x["gap_pct"])[:10]:
        print(f"    {g['name']:12s} | 갭 +{g['gap_pct']:.1f}% | 전일 {g['prev_close']:,}원 → 시가 {g['open_price']:,}원")

    print(f"\n  시초가매매 진입 가능: {len(sicho_entries)}개")
    for e in sicho_entries:
        print(f"    {e['name']:12s} | 갭 +{e['gap_pct']:.1f}% | 진입 {e['entry_price']:,.0f}원 @ {str(e['entry_time'])[11:16]}")

    # 5. 전체 매매 실행
    print("\n" + "=" * 60)
    print("5. 매매 실행 (시초가 + 돌파 + 눌림)")
    print("=" * 60)

    all_trades = []
    consecutive_loss = 0
    daily_pnl = 0.0
    traded_codes = set()  # 중복 매매 방지

    # 5-A. 시초가매매 (9:05~9:15, 갭상승 종목)
    print("\n  [A] 시초가매매 (갭상승 + 첫 눌림)")
    for entry_info in sorted(sicho_entries, key=lambda x: -x["gap_pct"]):
        if consecutive_loss >= MAX_CONSECUTIVE_LOSS:
            print(f"    ⚠ 2연패 일일정지 - 시초가매매 중단")
            break

        code = entry_info["code"]
        name = entry_info["name"]
        bars = bars_dict[code]

        trade = simulate_trade(
            bars, entry_info["entry_time"], entry_info["entry_price"],
            "시초가", code, name
        )
        all_trades.append(trade)
        traded_codes.add(code)

        # 연패 카운터
        if trade.pnl_pct < 0:
            consecutive_loss += 1
        else:
            consecutive_loss = 0
        daily_pnl += trade.pnl_pct

        win = "W" if trade.pnl_pct > 0 else "L"
        print(f"    {win} {name:12s} | 갭+{entry_info['gap_pct']:.1f}% | "
              f"{trade.entry_time[11:]} → {trade.exit_time[11:]} | "
              f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")

    # 5-B. 돌파매매 (9:30~11:00)
    print(f"\n  [B] 돌파매매 (오전 골든타임)")
    if consecutive_loss < MAX_CONSECUTIVE_LOSS:
        for code in leader_codes:
            if code in traded_codes or code not in bars_dict:
                continue
            if consecutive_loss >= MAX_CONSECUTIVE_LOSS:
                print(f"    ⚠ 2연패 일일정지 - 돌파매매 중단")
                break

            bars = bars_dict[code]
            name = leaders[code]["name"]
            entry = find_breakout_entry(bars)

            if entry["valid"]:
                trade = simulate_trade(
                    bars, entry["entry_time"], entry["entry_price"],
                    "돌파", code, name
                )
                all_trades.append(trade)
                traded_codes.add(code)

                if trade.pnl_pct < 0:
                    consecutive_loss += 1
                else:
                    consecutive_loss = 0
                daily_pnl += trade.pnl_pct

                win = "W" if trade.pnl_pct > 0 else "L"
                print(f"    {win} {name:12s} | "
                      f"{trade.entry_time[11:]} → {trade.exit_time[11:]} | "
                      f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")
    else:
        print(f"    ⚠ 2연패 상태 - 돌파매매 스킵")

    # 5-C. 눌림매매 (13:00~14:30)
    print(f"\n  [C] 눌림매매 (오후 되돌림)")
    if consecutive_loss < MAX_CONSECUTIVE_LOSS:
        for code in leader_codes:
            if code in traded_codes or code not in bars_dict:
                continue
            if consecutive_loss >= MAX_CONSECUTIVE_LOSS:
                print(f"    ⚠ 2연패 일일정지 - 눌림매매 중단")
                break

            bars = bars_dict[code]
            name = leaders[code]["name"]
            entry = find_pullback_entry(bars)

            if entry["valid"]:
                trade = simulate_trade(
                    bars, entry["entry_time"], entry["entry_price"],
                    "눌림", code, name
                )
                all_trades.append(trade)
                traded_codes.add(code)

                if trade.pnl_pct < 0:
                    consecutive_loss += 1
                else:
                    consecutive_loss = 0
                daily_pnl += trade.pnl_pct

                win = "W" if trade.pnl_pct > 0 else "L"
                print(f"    {win} {name:12s} | "
                      f"{trade.entry_time[11:]} → {trade.exit_time[11:]} | "
                      f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")
    else:
        print(f"    ⚠ 2연패 상태 - 눌림매매 스킵")

    # 6. 결과 요약
    print("\n" + "=" * 70)
    print("  백테스트 결과 요약")
    print("=" * 70)

    if not all_trades:
        print("  매매 없음")
        return

    total_trades = len(all_trades)
    wins = [t for t in all_trades if t.pnl_pct > 0]
    losses = [t for t in all_trades if t.pnl_pct <= 0]

    sicho_trades = [t for t in all_trades if t.method == "시초가"]
    dolpa_trades = [t for t in all_trades if t.method == "돌파"]
    nullim_trades = [t for t in all_trades if t.method == "눌림"]

    total_pnl = sum(t.pnl_pct for t in all_trades)
    wr = len(wins) / total_trades * 100 if total_trades > 0 else 0

    print(f"\n  전체: {total_trades}건 | {len(wins)}W {len(losses)}L | WR {wr:.1f}% | 수익 {total_pnl:+.2f}%")
    print(f"  ────────────────────────────────────")

    for method, trades in [("시초가", sicho_trades), ("돌파", dolpa_trades), ("눌림", nullim_trades)]:
        if trades:
            m_pnl = sum(t.pnl_pct for t in trades)
            m_wins = sum(1 for t in trades if t.pnl_pct > 0)
            m_wr = m_wins / len(trades) * 100
            print(f"  {method}: {len(trades)}건 | {m_wins}W {len(trades)-m_wins}L | WR {m_wr:.0f}% | {m_pnl:+.2f}%")

    print(f"\n  개별 매매 상세:")
    print(f"  {'#':>2} {'방법':4s} {'종목':12s} {'진입시간':>6s} {'청산시간':>6s} {'수익률':>8s} {'사유':4s}")
    print(f"  {'-'*55}")
    for i, t in enumerate(all_trades, 1):
        win_mark = "+" if t.pnl_pct > 0 else " "
        print(f"  {i:2d} {t.method:4s} {t.name:12s} {t.entry_time[11:]:>6s} {t.exit_time[11:]:>6s} {win_mark}{t.pnl_pct:+.2f}% {t.exit_reason}")

    # 시초가매매 효과 분석
    if sicho_trades:
        print(f"\n  ──── 시초가매매 효과 분석 ────")
        sicho_pnl = sum(t.pnl_pct for t in sicho_trades)
        other_pnl = sum(t.pnl_pct for t in all_trades if t.method != "시초가")
        print(f"  시초가매매 수익: {sicho_pnl:+.2f}%")
        print(f"  나머지 매매 수익: {other_pnl:+.2f}%")

        # 시초가매매가 승리한 경우, 연패 카운터에 미치는 영향
        sicho_wins = sum(1 for t in sicho_trades if t.pnl_pct > 0)
        if sicho_wins > 0:
            print(f"  → 시초가매매 {sicho_wins}승이 연패 카운터 리셋에 기여")
            print(f"  → 돌파/눌림 매매 기회 확보!")
        else:
            print(f"  → 시초가매매 전패 → 연패 카운터 악화 우려")


if __name__ == "__main__":
    run_backtest()
