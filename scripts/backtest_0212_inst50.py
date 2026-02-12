"""
2026-02-12 하루 백테스트: 기관 50~200억 스위트스팟 전략

조건:
  1. 전일(2/11) 거래대금 TOP20 + 강세(+3%+)
  2. 전일 기관 순매수 50~200억 (필수)
  3. 끼(과거 90일 내 +15% 이력) → 우선순위
  4. 10:00~11:00 돌파 / 13:00~14:30 눌림
  5. SL -4%, TP +5%
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from pykrx import stock as pykrx_stock
from datetime import datetime, timedelta
from dataclasses import dataclass

TARGET_DATE = "20260212"
PREV_DATE = "20260211"

SL_PCT = -0.04
TP_PCT = 0.05
TP_PARTIAL = 0.70

INST_MIN = 5_000_000_000    # 50억
INST_MAX = 20_000_000_000   # 200억
KKI_MIN_CHANGE = 15.0

_kosdaq_set = None

def get_kosdaq_set():
    global _kosdaq_set
    if _kosdaq_set is None:
        _kosdaq_set = set(pykrx_stock.get_market_ticker_list(TARGET_DATE, market="KOSDAQ"))
    return _kosdaq_set

def code_to_ticker(code):
    return f"{code}{'.KQ' if code in get_kosdaq_set() else '.KS'}"


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


def step1_prev_day_screening():
    """전일(2/11) 스크리닝: 거래대금 TOP20 + 강세 + 기관 50~200억"""
    print("=" * 70)
    print("  1. 전일(2/11) 스크리닝")
    print("=" * 70)

    df_prev = pykrx_stock.get_market_ohlcv_by_ticker(PREV_DATE, market="ALL")
    df_prev = df_prev[df_prev["거래량"] > 0]

    top20 = df_prev.nlargest(20, "거래대금")

    print(f"\n  전일 거래대금 TOP20 + 강세(+3%+) + 기관 50~200억:")
    print(f"  {'종목':12s} | {'등락률':>6s} | {'거래대금':>10s} | {'기관':>8s} | {'외국인':>8s} | 끼  | 판정")
    print(f"  {'─'*80}")

    candidates = []

    for code in top20.index:
        row = df_prev.loc[code]
        name = pykrx_stock.get_market_ticker_name(code) or code
        change = row["등락률"]
        value = row["거래대금"]
        prev_close = row["종가"]
        prev_high = row["고가"]

        if change < 3.0:
            continue

        # 기관/외국인 수급
        inst_net = 0
        foreign_net = 0
        try:
            inv = pykrx_stock.get_market_trading_value_by_date(PREV_DATE, PREV_DATE, code)
            if not inv.empty:
                inst_net = inv.iloc[0].get("기관합계", 0)
                foreign_net = inv.iloc[0].get("외국인합계", 0)
        except Exception:
            pass

        # 기관 구간
        if INST_MIN <= inst_net <= INST_MAX:
            inst_tag = "★스위트"
        elif inst_net > INST_MAX:
            inst_tag = "대량"
        elif inst_net > 0:
            inst_tag = "소폭"
        else:
            inst_tag = "매도"

        # 끼: 과거 90일 내 +15% 이력
        kki_ok = False
        kki_detail = ""
        try:
            start_date = (datetime.strptime(PREV_DATE, "%Y%m%d") - timedelta(days=180)).strftime("%Y%m%d")
            hist = pykrx_stock.get_market_ohlcv_by_date(start_date, PREV_DATE, code)
            if not hist.empty:
                # 전일 제외하고 90 거래일
                before = hist.iloc[:-1].tail(90)
                for idx, hrow in before.iterrows():
                    if hrow.get("등락률", 0) >= KKI_MIN_CHANGE:
                        kki_ok = True
                        kki_detail = f"{idx.strftime('%m/%d')} +{hrow['등락률']:.0f}%"
                        break
        except Exception:
            pass

        # 차트 위치: 20일 고가 근접
        chart_ok = False
        try:
            if not hist.empty:
                recent20 = hist.iloc[:-1].tail(20)
                high_20d = recent20["고가"].max()
                if high_20d > 0:
                    chart_ok = prev_close / high_20d >= 0.95
        except Exception:
            pass

        verdict = ""
        if inst_tag == "★스위트":
            if kki_ok:
                verdict = "◎ 최우선"
            else:
                verdict = "○ 대상"
        elif inst_tag == "대량":
            verdict = "△ 참고"
        else:
            verdict = "✗ 제외"

        kki_s = f"O({kki_detail[:8]})" if kki_ok else "X"

        print(f"  {name:12s} | {change:+5.1f}% | {value/1e8:>8,.0f}억 | "
              f"{inst_net/1e8:+7,.0f}억 | {foreign_net/1e8:+7,.0f}억 | "
              f"{kki_s:10s} | {verdict}")

        candidates.append({
            "code": code, "name": name,
            "prev_close": prev_close, "prev_high": prev_high,
            "prev_change": change, "prev_value": value,
            "inst_net": inst_net, "foreign_net": foreign_net,
            "inst_tag": inst_tag,
            "kki_ok": kki_ok, "kki_detail": kki_detail,
            "chart_ok": chart_ok,
        })

    # 필터링
    sweet = [c for c in candidates if c["inst_tag"] == "★스위트"]
    sweet_kki = [c for c in sweet if c["kki_ok"]]

    print(f"\n  필터 결과:")
    print(f"    전일 TOP20 강세(+3%+): {len(candidates)}개")
    print(f"    기관 50~200억:         {len(sweet)}개")
    print(f"    + 끼 있음:             {len(sweet_kki)}개")

    # 비교군도 포함 (기관O 전체)
    inst_all = [c for c in candidates if c["inst_net"] > 0]
    print(f"    기관 순매수 전체:       {len(inst_all)}개")

    return candidates, sweet, sweet_kki


def step2_fetch_5min(candidates):
    """5분봉 수집"""
    print("\n" + "=" * 70)
    print("  2. 5분봉 수집")
    print("=" * 70)

    codes = [c["code"] for c in candidates]
    tickers = [code_to_ticker(c) for c in codes]

    bars_dict = {}
    batch_size = 20
    for bs in range(0, len(tickers), batch_size):
        batch_codes = codes[bs:bs + batch_size]
        batch_tickers = tickers[bs:bs + batch_size]
        try:
            data = yf.download(" ".join(batch_tickers), period="5d", interval="5m",
                               progress=False, threads=True)
            if data.empty:
                continue
            for code in batch_codes:
                ticker = code_to_ticker(code)
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if ticker in data.columns.get_level_values(1):
                            df = data.xs(ticker, level=1, axis=1).copy()
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
                    day_mask = df.index.date == pd.Timestamp("2026-02-12").date()
                    day_bars = df[day_mask]
                    if len(day_bars) >= 10:
                        bars_dict[code] = day_bars
                except Exception:
                    continue
        except Exception:
            continue

    print(f"  수집: {len(bars_dict)}개 / {len(codes)}개")
    return bars_dict


def step3_morning_check(bars_dict, candidates):
    """9:30~10:00 오전 모멘텀 체크"""
    print("\n" + "=" * 70)
    print("  3. 오전 9:30~10:00 모멘텀 체크")
    print("=" * 70)

    results = {}
    for c in candidates:
        code = c["code"]
        if code not in bars_dict:
            continue

        bars = bars_dict[code]
        morning = bars[
            ((bars.index.hour == 9) & (bars.index.minute >= 30)) |
            ((bars.index.hour == 10) & (bars.index.minute == 0))
        ]
        if len(morning) < 3:
            results[code] = {"ok": False, "detail": "데이터부족"}
            continue

        bull = sum(1 for _, b in morning.iterrows() if b["Close"] >= b["Open"])
        br = bull / len(morning)
        pchg = (morning["Close"].iloc[-1] / morning["Open"].iloc[0] - 1) * 100
        vol_trend = morning["Volume"].iloc[-1] / morning["Volume"].iloc[0] if morning["Volume"].iloc[0] > 0 else 0

        ok = br >= 0.5 and pchg > 0
        detail = f"양봉{br*100:.0f}% 변동{pchg:+.1f}% 거래량추세{vol_trend:.1f}x"
        results[code] = {"ok": ok, "detail": detail}

        mark = "O" if ok else "X"
        print(f"  {mark} {c['name']:12s} | {c['inst_tag']:6s} | {detail}")

    return results


def find_breakout(bars):
    """돌파 진입: 10:00~11:00"""
    window = bars[
        (bars.index.hour == 10) |
        ((bars.index.hour == 11) & (bars.index.minute == 0))
    ]
    if len(window) < 6:
        return None

    for i in range(5, len(window)):
        ph = window["High"].iloc[i-5:i].max()
        bar = window.iloc[i]
        if bar["High"] > ph and bar["Close"] > ph:
            av = window["Volume"].iloc[i-5:i].mean()
            if av > 0 and bar["Volume"] >= av * 1.5:
                return {"price": bar["Close"], "time": window.index[i]}
    return None


def find_pullback(bars):
    """눌림 진입: 13:00~14:30"""
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


def simulate(bars, entry, method, code, name, note=""):
    """SL/TP 시뮬"""
    ep, et = entry["price"], entry["time"]
    after = bars[bars.index > et]

    trade = Trade(code=code, name=name, method=method,
                  entry_time=str(et)[:16], entry_price=ep, note=note)

    for ts, bar in after.iterrows():
        lo = (bar["Low"] / ep) - 1
        hi = (bar["High"] / ep) - 1

        if lo <= SL_PCT:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = ep * (1 + SL_PCT)
            trade.pnl_pct = SL_PCT * 100
            trade.exit_reason = "손절-4%"
            return trade

        if hi >= TP_PCT:
            trade.exit_time = str(ts)[:16]
            trade.exit_price = ep * (1 + TP_PCT * TP_PARTIAL)
            trade.pnl_pct = TP_PCT * TP_PARTIAL * 100
            trade.exit_reason = "익절+5%"
            return trade

    if len(after) > 0:
        last = after.iloc[-1]
        trade.exit_time = str(after.index[-1])[:16]
        trade.exit_price = last["Close"]
        trade.pnl_pct = ((last["Close"] / ep) - 1) * 100
        trade.exit_reason = "장마감"

    return trade


def step4_execute(candidates, sweet, sweet_kki, bars_dict, morning_check):
    """매매 실행: 돌파+눌림 (시초가X, 2연패정지X, 기관필터X)"""
    print("\n" + "=" * 70)
    print("  4. 매매 실행 (돌파+눌림, 전종목, 제한없음)")
    print("=" * 70)

    all_trades = []
    traded_codes = set()

    # 전일 거래대금순 정렬
    sorted_all = sorted(candidates, key=lambda x: -x["prev_value"])

    # ── A: 돌파 (10:00~11:00) ──
    print(f"\n  [A. 돌파매매 10:00~11:00]")
    for c in sorted_all:
        code = c["code"]
        name = c["name"]
        if code in traded_codes or code not in bars_dict:
            continue

        bars = bars_dict[code]
        entry = find_breakout(bars)
        if entry is None:
            continue

        note = f"{c['inst_tag']} 기관{c['inst_net']/1e8:+,.0f}억"
        if c["kki_ok"]:
            note += " 끼O"

        trade = simulate(bars, entry, "돌파", code, name, note)
        all_trades.append(trade)
        traded_codes.add(code)

        w = "W" if trade.pnl_pct > 0 else "L"
        mom = morning_check.get(code, {})
        mom_s = "모멘텀O" if mom.get("ok") else "모멘텀X"
        print(f"    {w} {name:12s} | {note} | {mom_s} | "
              f"{trade.entry_time[11:]}→{trade.exit_time[11:]} | "
              f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")

    # ── B: 눌림 (13:00~14:30) ──
    print(f"\n  [B. 눌림매매 13:00~14:30]")
    for c in sorted_all:
        code = c["code"]
        name = c["name"]
        if code in traded_codes or code not in bars_dict:
            continue

        bars = bars_dict[code]
        entry = find_pullback(bars)
        if entry is None:
            continue

        note = f"{c['inst_tag']} 기관{c['inst_net']/1e8:+,.0f}억"
        if c["kki_ok"]:
            note += " 끼O"

        trade = simulate(bars, entry, "눌림", code, name, note)
        all_trades.append(trade)
        traded_codes.add(code)

        w = "W" if trade.pnl_pct > 0 else "L"
        mom = morning_check.get(code, {})
        mom_s = "모멘텀O" if mom.get("ok") else "모멘텀X"
        print(f"    {w} {name:12s} | {note} | {mom_s} | "
              f"{trade.entry_time[11:]}→{trade.exit_time[11:]} | "
              f"{trade.pnl_pct:+.2f}% ({trade.exit_reason})")

    return all_trades


def step5_summary(all_trades, candidates, sweet, sweet_kki):
    """결과 요약"""
    print("\n" + "=" * 70)
    print("  5. 결과 요약: 2026-02-12")
    print("=" * 70)

    if not all_trades:
        print("  매매 없음")
        return

    total = len(all_trades)
    wins = [t for t in all_trades if t.pnl_pct > 0]
    total_pnl = sum(t.pnl_pct for t in all_trades)
    wr = len(wins) / total * 100

    print(f"\n  전체: {total}건 | {len(wins)}W {total-len(wins)}L | "
          f"WR {wr:.0f}% | 합계 {total_pnl:+.2f}%")

    # 방법별
    for m in ["돌파", "눌림"]:
        ts = [t for t in all_trades if t.method == m]
        if ts:
            mw = sum(1 for t in ts if t.pnl_pct > 0)
            mp = sum(t.pnl_pct for t in ts)
            print(f"  {m}: {len(ts)}건 | {mw}W {len(ts)-mw}L | {mp:+.2f}%")

    # 스위트 vs 비교군
    sweet_codes = {c["code"] for c in sweet}
    sweet_trades = [t for t in all_trades if t.code in sweet_codes]
    other_trades = [t for t in all_trades if t.code not in sweet_codes]

    print(f"\n  ┌─── 기관구간별 ───┐")
    if sweet_trades:
        sw = sum(1 for t in sweet_trades if t.pnl_pct > 0)
        sp = sum(t.pnl_pct for t in sweet_trades)
        print(f"  │ ★스위트50~200: {len(sweet_trades)}건 | {sw}W {len(sweet_trades)-sw}L | {sp:+.2f}%")
    if other_trades:
        ow = sum(1 for t in other_trades if t.pnl_pct > 0)
        op = sum(t.pnl_pct for t in other_trades)
        print(f"  │   기타:          {len(other_trades)}건 | {ow}W {len(other_trades)-ow}L | {op:+.2f}%")
    print(f"  └────────────────┘")

    # 상세
    print(f"\n  상세:")
    print(f"  {'#':>2} {'방법':4s} {'종목':12s} {'진입':>6s} {'청산':>6s} "
          f"{'수익률':>8s} {'사유':8s} {'비고'}")
    print(f"  {'─'*78}")
    for i, t in enumerate(all_trades, 1):
        print(f"  {i:2d} {t.method:4s} {t.name:12s} {t.entry_time[11:]:>6s} "
              f"{t.exit_time[11:]:>6s} {t.pnl_pct:+6.2f}% {t.exit_reason:8s} {t.note}")

    # V2 대비 비교
    print(f"\n  ┌─── 이전 버전 대비 ───┐")
    print(f"  │ V1(단순돌파+눌림):  11건, 7W 4L, +4.17%")
    print(f"  │ V2(시초가+2연패):   2건, 0W 2L, -7.00%")
    print(f"  │ V3(돌파+눌림,필터X): {total}건, {len(wins)}W {total-len(wins)}L, {total_pnl:+.2f}%")
    print(f"  └────────────────────┘")


def main():
    # 1. 전일 스크리닝
    candidates, sweet, sweet_kki = step1_prev_day_screening()

    # 2. 5분봉 수집
    bars_dict = step2_fetch_5min(candidates)

    # 3. 오전 모멘텀
    morning_check = step3_morning_check(bars_dict, candidates)

    # 4. 매매 실행
    all_trades = step4_execute(candidates, sweet, sweet_kki, bars_dict, morning_check)

    # 5. 결과
    step5_summary(all_trades, candidates, sweet, sweet_kki)


if __name__ == "__main__":
    main()
