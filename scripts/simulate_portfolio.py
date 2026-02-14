#!/usr/bin/env python3
"""실투자 포트폴리오 시뮬레이션 - 6개 전략 통합

기존 백테스트와의 차이:
  - 자본금 1000만원 하나로 6개 전략이 경쟁
  - 동시 보유 최대 3종목 (전략 무관)
  - 매 봉마다 전 전략의 시그널을 confidence순 정렬
  - 자본금 복리 반영 (수익→다음 투자금 증가)
  - 동일 종목 중복 진입 불가
  - 수수료 0.015%×2 + 세금 0.23%

실행:
  python scripts/simulate_portfolio.py              # 60일, 홍인기 OFF vs ON
  python scripts/simulate_portfolio.py --days 20    # 20일만
  python scripts/simulate_portfolio.py --hong-only  # 홍인기 ON만
"""

import copy
import sys
from dataclasses import dataclass, field
from datetime import time, date as date_type
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

import numpy as np
import pandas as pd
from sqlalchemy import text
from tqdm import tqdm

from src.database.connection import get_backtest_engine as get_engine
from src.strategies.data_driven import get_data_driven_strategies
from src.strategies.data_driven.daily_context import DailyContextLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ─── 설정 ───
INITIAL_CAPITAL = 10_000_000  # 1000만원
MAX_POSITIONS = 3
POSITION_SIZE_PCT = 0.30      # 종목당 현재 자본의 30%
COMMISSION_RATE = 0.00015     # 매수/매도 각 0.015%
TAX_RATE = 0.0023             # 매도세 0.23%
FORCE_CLOSE_TIME = time(15, 20)
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)


@dataclass
class PortfolioPosition:
    code: str
    strategy_name: str
    entry_price: float
    entry_time: object
    quantity: int
    invested: float          # 실 투입 금액 (price * qty + commission)
    stop_loss: float
    take_profit: float
    entry_reason: str = ""
    entry_bar_idx: int = 0


@dataclass
class PortfolioTrade:
    code: str
    strategy_name: str
    entry_price: float
    entry_time: object
    exit_price: float
    exit_time: object
    quantity: int
    pnl: float              # 수수료+세금 차감 후 손익
    pnl_pct: float
    exit_reason: str
    commission_total: float  # 매수+매도 수수료+세금 합계


@dataclass
class DailyRecord:
    date: date_type
    equity: float            # 현금 + 보유주식 평가
    cash: float
    positions_count: int
    trades_count: int
    day_pnl: float


def load_intraday_data(n_days=None):
    """DB에서 5분봉 데이터 로드."""
    engine = get_engine()
    with engine.connect() as conn:
        codes = [r[0] for r in conn.execute(text(
            "SELECT code FROM ohlcv_intraday GROUP BY code HAVING COUNT(*) >= 100"
        )).fetchall()]

    data = {}
    with engine.connect() as conn:
        for code in codes:
            rows = conn.execute(text(
                "SELECT datetime, open, high, low, close, volume "
                "FROM ohlcv_intraday WHERE code = :code ORDER BY datetime"
            ), {"code": code}).fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
                df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
                data[code] = df

    # n_days 필터
    if n_days:
        all_dates = sorted(set(d for df in data.values() for d in df.index.date))
        if n_days < len(all_dates):
            target = set(all_dates[-n_days:])
            data = {c: df[df.index.map(lambda x: x.date() in target)] for c, df in data.items()}
            data = {k: v for k, v in data.items() if not v.empty}

    return data


def run_portfolio_simulation(
    strategies, data, daily_context=None, hong_enabled=True, label="",
):
    """6개 전략 통합 포트폴리오 시뮬레이션."""
    capital = float(INITIAL_CAPITAL)
    positions: dict[str, PortfolioPosition] = {}
    all_trades: list[PortfolioTrade] = []
    daily_records: list[DailyRecord] = []

    # 전략 설정
    strats = []
    for s in strategies:
        s_copy = copy.deepcopy(s)
        if not hong_enabled:
            s_copy.HONG_ENABLED = False
        else:
            # 기관 필터 비활성화 (데이터 없음)
            s_copy.HONG_MIN_INST_BIL = -999999
            s_copy.HONG_MAX_INST_BIL = 999999
        strats.append(s_copy)

    # ─── Phase 1: 날짜별 데이터 그룹핑 ───
    date_code_df: dict[object, dict[str, pd.DataFrame]] = {}
    all_dates_set = set()
    for code, df in data.items():
        for dt, day_df in df.groupby(df.index.date):
            all_dates_set.add(dt)
            if dt not in date_code_df:
                date_code_df[dt] = {}
            date_code_df[dt][code] = day_df

    all_dates = sorted(all_dates_set)

    for current_date in tqdm(all_dates, desc=f"[{label}]", leave=False):
        day_data = date_code_df.get(current_date)
        if not day_data:
            continue

        day_pnl = 0.0
        day_trades = 0

        # ─── Phase 2: 각 전략의 지표 사전 계산 ───
        # {strategy_idx: {code: indicators}}
        strat_indicators = {}
        strat_ts_to_idx = {}

        for si, strategy in enumerate(strats):
            strat_indicators[si] = {}
            strat_ts_to_idx[si] = {}
            for code, day_df in day_data.items():
                ctx = None
                if daily_context and code in daily_context:
                    ctx = daily_context[code].get(current_date)
                strategy.set_daily_context(code, current_date, ctx)

                ind = strategy.precompute_day(day_df)
                strat_indicators[si][code] = ind
                strat_ts_to_idx[si][code] = {ts: i for i, ts in enumerate(ind["timestamps"])}

        # ─── Phase 3: 전체 타임스탬프 정렬 순회 ───
        all_ts = sorted(set(ts for day_df in day_data.values() for ts in day_df.index.tolist()))

        for ts in all_ts:
            current_time = ts.time() if hasattr(ts, 'time') else ts
            if hasattr(current_time, 'hour'):
                if current_time < MARKET_OPEN or current_time > MARKET_CLOSE:
                    continue

            # ─── 강제 청산 ───
            if hasattr(current_time, 'hour') and current_time >= FORCE_CLOSE_TIME:
                for code in list(positions.keys()):
                    # 아무 전략의 indicators든 close price 사용
                    for si in range(len(strats)):
                        if code in strat_ts_to_idx[si] and ts in strat_ts_to_idx[si][code]:
                            idx = strat_ts_to_idx[si][code][ts]
                            price = float(strat_indicators[si][code]["close"][idx])
                            trade = _close_position(positions[code], price, ts, "장마감강제")
                            all_trades.append(trade)
                            capital += trade.pnl
                            actual = (trade.exit_price - trade.entry_price) * trade.quantity - trade.commission_total
                            day_pnl += actual
                            day_trades += 1
                            del positions[code]
                            break
                continue

            # ─── 보유 포지션 청산 체크 ───
            for code in list(positions.keys()):
                pos = positions[code]
                # 해당 전략의 indicators 사용
                si = _find_strategy_idx(strats, pos.strategy_name)
                if si is None or code not in strat_ts_to_idx[si] or ts not in strat_ts_to_idx[si][code]:
                    continue

                idx = strat_ts_to_idx[si][code][ts]
                ind = strat_indicators[si][code]
                low_val = float(ind["low"][idx])
                high_val = float(ind["high"][idx])

                # SL
                if low_val <= pos.stop_loss:
                    trade = _close_position(pos, pos.stop_loss, ts, "손절")
                    all_trades.append(trade)
                    capital += trade.pnl
                    actual = (trade.exit_price - trade.entry_price) * trade.quantity - trade.commission_total
                    day_pnl += actual
                    day_trades += 1
                    del positions[code]
                    continue

                # TP
                if high_val >= pos.take_profit:
                    trade = _close_position(pos, pos.take_profit, ts, "익절")
                    all_trades.append(trade)
                    capital += trade.pnl
                    actual = (trade.exit_price - trade.entry_price) * trade.quantity - trade.commission_total
                    day_pnl += actual
                    day_trades += 1
                    del positions[code]
                    continue

            # ─── 신규 진입 (모든 전략에서 시그널 수집) ───
            if len(positions) < MAX_POSITIONS:
                pending = []

                for si, strategy in enumerate(strats):
                    for code in day_data:
                        if code in positions:
                            continue
                        if code not in strat_ts_to_idx[si] or ts not in strat_ts_to_idx[si][code]:
                            continue

                        idx = strat_ts_to_idx[si][code][ts]
                        ind = strat_indicators[si][code]

                        # daily_context 재설정
                        if daily_context and code in daily_context:
                            ctx = daily_context[code].get(current_date)
                            strategy.set_daily_context(code, current_date, ctx)

                        signal = strategy.check_entry_fast(code, idx, ind)
                        if signal:
                            confidence = signal.get("confidence", 1.0)
                            pending.append({
                                "code": code,
                                "si": si,
                                "idx": idx,
                                "signal": signal,
                                "confidence": confidence,
                                "strategy_name": strategy.name,
                            })

                # confidence 내림차순 정렬
                pending.sort(key=lambda x: x["confidence"], reverse=True)

                # 동일 종목 중복 제거 (가장 높은 confidence만)
                seen_codes = set(positions.keys())
                for p in pending:
                    if len(positions) >= MAX_POSITIONS:
                        break
                    if p["code"] in seen_codes:
                        continue

                    code = p["code"]
                    si = p["si"]
                    idx = p["idx"]
                    signal = p["signal"]
                    ind = strat_indicators[si][code]

                    price = float(ind["close"][idx])
                    invest_amount = capital * POSITION_SIZE_PCT
                    quantity = int(invest_amount / price)

                    if quantity <= 0:
                        continue

                    buy_cost = price * quantity * COMMISSION_RATE
                    total_cost = price * quantity + buy_cost

                    if total_cost > capital:
                        quantity = int((capital * 0.99) / price)  # 약간 여유
                        if quantity <= 0:
                            continue
                        buy_cost = price * quantity * COMMISSION_RATE
                        total_cost = price * quantity + buy_cost

                    capital -= total_cost

                    sl_pct = signal.get("stop_loss", 0.03)
                    tp_pct = signal.get("take_profit", 0.05)

                    positions[code] = PortfolioPosition(
                        code=code,
                        strategy_name=p["strategy_name"],
                        entry_price=price,
                        entry_time=ts,
                        quantity=quantity,
                        invested=total_cost,
                        stop_loss=price * (1 - sl_pct),
                        take_profit=price * (1 + tp_pct),
                        entry_reason=signal.get("reason", ""),
                        entry_bar_idx=idx,
                    )
                    seen_codes.add(code)

        # ─── 장 종료: 남은 포지션 종가 청산 ───
        for code in list(positions.keys()):
            for si in range(len(strats)):
                if code in strat_indicators[si]:
                    ind = strat_indicators[si][code]
                    last_idx = ind["n_bars"] - 1
                    price = float(ind["close"][last_idx])
                    last_ts = ind["timestamps"][last_idx]
                    trade = _close_position(positions[code], price, last_ts, "장마감")
                    all_trades.append(trade)
                    capital += trade.pnl
                    actual = (trade.exit_price - trade.entry_price) * trade.quantity - trade.commission_total
                    day_pnl += actual
                    day_trades += 1
                    del positions[code]
                    break

        # 일별 기록
        equity = capital  # 장마감 후 모든 포지션 청산됨
        daily_records.append(DailyRecord(
            date=current_date,
            equity=equity,
            cash=capital,
            positions_count=0,
            trades_count=day_trades,
            day_pnl=day_pnl,
        ))

    return capital, all_trades, daily_records


def _find_strategy_idx(strats, name):
    for i, s in enumerate(strats):
        if s.name == name:
            return i
    return 0  # fallback


def _close_position(pos: PortfolioPosition, exit_price: float, exit_time, reason: str) -> PortfolioTrade:
    """포지션 청산 + 수수료/세금 계산."""
    sell_value = exit_price * pos.quantity
    sell_commission = sell_value * COMMISSION_RATE
    sell_tax = sell_value * TAX_RATE
    total_cost = sell_commission + sell_tax

    gross_pnl = (exit_price - pos.entry_price) * pos.quantity
    net_pnl = sell_value - total_cost  # 매도 후 받는 금액 (매수 비용은 이미 차감됨)
    pnl_pct = (exit_price / pos.entry_price - 1) * 100

    # 실질 손익 = 매도 수취액 - 매수 투입액
    actual_pnl = net_pnl - (pos.entry_price * pos.quantity)
    buy_commission = pos.entry_price * pos.quantity * COMMISSION_RATE

    return PortfolioTrade(
        code=pos.code,
        strategy_name=pos.strategy_name,
        entry_price=pos.entry_price,
        entry_time=pos.entry_time,
        exit_price=exit_price,
        exit_time=exit_time,
        quantity=pos.quantity,
        pnl=net_pnl,  # 자본에 더해질 금액
        pnl_pct=pnl_pct,
        exit_reason=reason,
        commission_total=buy_commission + sell_commission + sell_tax,
    )


def print_simulation_result(
    final_capital, trades, daily_records, label,
):
    """시뮬레이션 결과 출력."""
    total_pnl = final_capital - INITIAL_CAPITAL
    total_return = (final_capital / INITIAL_CAPITAL - 1) * 100
    n_trades = len(trades)
    n_wins = sum(1 for t in trades if t.pnl_pct > 0)
    win_rate = n_wins / n_trades * 100 if n_trades else 0
    total_commission = sum(t.commission_total for t in trades)

    # MDD
    peak = INITIAL_CAPITAL
    max_dd = 0
    for d in daily_records:
        peak = max(peak, d.equity)
        dd = (d.equity - peak) / peak * 100
        max_dd = min(max_dd, dd)

    n_days = len(daily_records)

    print(f"\n{'━' * 70}")
    print(f"  [{label}] 실투자 포트폴리오 시뮬레이션 결과")
    print(f"{'━' * 70}")
    print(f"  초기자금:     {INITIAL_CAPITAL:>14,}원")
    print(f"  최종자금:     {final_capital:>14,.0f}원")
    print(f"  총 손익:      {total_pnl:>+14,.0f}원 ({total_return:+.2f}%)")
    print(f"  거래비용:     {total_commission:>14,.0f}원")
    print(f"  거래수:       {n_trades:>14}건")
    print(f"  승률:         {win_rate:>13.1f}%  ({n_wins}W / {n_trades - n_wins}L)")
    print(f"  MDD:          {max_dd:>13.2f}%")
    print(f"  기간:         {n_days:>14}일")

    if n_days > 0:
        daily_return = total_return / n_days
        monthly_est = daily_return * 22
        print(f"  일평균:       {daily_return:>+13.2f}%")
        print(f"  월 환산:      {monthly_est:>+13.2f}%  ({total_pnl / n_days * 22:+,.0f}원/월)")

    # 전략별 성과
    strat_stats = {}
    for t in trades:
        if t.strategy_name not in strat_stats:
            strat_stats[t.strategy_name] = {"trades": 0, "wins": 0, "pnl": 0.0}
        strat_stats[t.strategy_name]["trades"] += 1
        if t.pnl_pct > 0:
            strat_stats[t.strategy_name]["wins"] += 1
        strat_stats[t.strategy_name]["pnl"] += (t.pnl - t.quantity * t.entry_price)

    print(f"\n  [전략별]")
    print(f"  {'전략':30s} {'거래':>5s} {'승률':>7s} {'손익':>14s}")
    print(f"  {'─' * 58}")
    for name in sorted(strat_stats.keys()):
        s = strat_stats[name]
        wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
        # 실제 손익 추정: pnl_pct 기반
        strat_trades = [t for t in trades if t.strategy_name == name]
        actual_pnl = sum((t.exit_price - t.entry_price) * t.quantity - t.commission_total for t in strat_trades)
        print(f"  {name:30s} {s['trades']:5d} {wr:6.1f}% {actual_pnl:>+13,.0f}원")

    # 청산사유별
    reason_stats = {}
    for t in trades:
        if t.exit_reason not in reason_stats:
            reason_stats[t.exit_reason] = {"count": 0, "pnl": 0.0}
        reason_stats[t.exit_reason]["count"] += 1
        reason_stats[t.exit_reason]["pnl"] += (t.exit_price - t.entry_price) * t.quantity - t.commission_total

    print(f"\n  [청산사유별]")
    for reason in ["익절", "손절", "장마감", "장마감강제"]:
        if reason in reason_stats:
            r = reason_stats[reason]
            print(f"  {reason:12s}: {r['count']:4d}건 | {r['pnl']:>+13,.0f}원")

    # 일별 요약 (마지막 10일)
    print(f"\n  [최근 10일]")
    print(f"  {'날짜':12s} {'거래':>4s} {'일PnL':>12s} {'자산':>14s}")
    print(f"  {'─' * 46}")
    for d in daily_records[-10:]:
        print(f"  {str(d.date):12s} {d.trades_count:4d} {d.day_pnl:>+12,.0f}원 {d.equity:>14,.0f}원")


def main():
    # 인자 파싱
    n_days = None
    hong_only = False
    for arg in sys.argv[1:]:
        if arg == "--hong-only":
            hong_only = True
        elif arg == "--days":
            pass
        elif arg.isdigit():
            n_days = int(arg)
        elif sys.argv[sys.argv.index(arg) - 1] == "--days":
            n_days = int(arg)

    if n_days is None:
        # --days N 패턴 처리
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--days" and i < len(sys.argv) - 1:
                n_days = int(sys.argv[i + 1])

    print("=" * 70)
    print("  실투자 포트폴리오 시뮬레이션")
    print(f"  자본금: {INITIAL_CAPITAL:,}원 | 최대 {MAX_POSITIONS}종목 | 종목당 {POSITION_SIZE_PCT*100:.0f}%")
    print(f"  수수료: {COMMISSION_RATE*100:.3f}% | 세금: {TAX_RATE*100:.2f}%")
    print("=" * 70)

    # 데이터 로드
    data = load_intraday_data(n_days)
    all_dates = sorted(set(d for df in data.values() for d in df.index.date))
    print(f"\n  데이터: {len(data)}종목, {len(all_dates)}거래일")
    print(f"  기간: {min(all_dates)} ~ {max(all_dates)}")

    # 일별 컨텍스트 로드
    codes = list(data.keys())
    print(f"\n  일별 컨텍스트 로딩 중...")
    loader = DailyContextLoader()
    daily_context = loader.load(codes, min(all_dates), max(all_dates))
    print(f"  컨텍스트: {sum(len(v) for v in daily_context.values())}건")

    # 전략 로드
    strategies = get_data_driven_strategies()
    print(f"  전략: {len(strategies)}개")

    # ─── 시뮬레이션 실행 ───

    if not hong_only:
        # A) 홍인기 OFF (기존 기술적만)
        print(f"\n  [A] 홍인기 OFF 시뮬레이션 중...")
        cap_a, trades_a, daily_a = run_portfolio_simulation(
            strategies, data, daily_context=None, hong_enabled=False, label="홍인기OFF",
        )
        print_simulation_result(cap_a, trades_a, daily_a, "A) 홍인기 OFF")

    # B) 홍인기 ON (전체 필터)
    print(f"\n  [B] 홍인기 ON 시뮬레이션 중...")
    cap_b, trades_b, daily_b = run_portfolio_simulation(
        strategies, data, daily_context=daily_context, hong_enabled=True, label="홍인기ON",
    )
    print_simulation_result(cap_b, trades_b, daily_b, "B) 홍인기 ON")

    # ─── 비교 요약 ───
    if not hong_only:
        ret_a = (cap_a / INITIAL_CAPITAL - 1) * 100
        ret_b = (cap_b / INITIAL_CAPITAL - 1) * 100
        print(f"\n{'━' * 70}")
        print(f"  비교 요약")
        print(f"{'━' * 70}")
        print(f"  {'':30s} {'홍인기 OFF':>15s} {'홍인기 ON':>15s}")
        print(f"  {'─' * 62}")
        print(f"  {'최종자금':30s} {cap_a:>14,.0f}원 {cap_b:>14,.0f}원")
        print(f"  {'수익률':30s} {ret_a:>+14.2f}% {ret_b:>+14.2f}%")
        print(f"  {'거래수':30s} {len(trades_a):>14}건 {len(trades_b):>14}건")

        wr_a = sum(1 for t in trades_a if t.pnl_pct > 0) / len(trades_a) * 100 if trades_a else 0
        wr_b = sum(1 for t in trades_b if t.pnl_pct > 0) / len(trades_b) * 100 if trades_b else 0
        print(f"  {'승률':30s} {wr_a:>13.1f}% {wr_b:>13.1f}%")

    print(f"\n{'=' * 70}")
    print(f"  완료!")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
