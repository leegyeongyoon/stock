"""홍인기 전략 간이 백테스트.

DB에 있는 일봉(4년) + 5분봉(60일) 데이터를 활용하여
홍인기 매매법의 핵심 로직을 백테스트합니다.

섹터 분석 → 거래대금 상위 종목으로 대체 (프록시)
뉴스 패턴 → 스킵
나머지: 일봉 자리 + 끼 점수 + 패턴 감지 + SL/TP 분할매도 전부 적용
"""

import sys
import time as time_module
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategies.hongstyle.daily_chart_analyzer import DailyChartAnalyzer
from src.strategies.hongstyle.pattern_detector import PatternDetector
from src.strategies.hongstyle.signal_generator import SignalGenerator


# ── 설정 ──────────────────────────────────────────────

@dataclass
class BacktestConfig:
    initial_capital: int = 10_000_000    # 1000만원
    max_positions: int = 5               # 최대 동시 보유
    high_confidence_pct: float = 0.15    # 확신 종목 15%
    low_confidence_pct: float = 0.05     # 애매 종목 5%
    confidence_threshold: float = 0.7    # 확신/애매 경계
    min_confidence: float = 0.6          # 최소 진입 확신도
    stop_loss: float = 0.04             # -4% 손절
    take_profit: float = 0.05           # +5% 1차 익절
    partial_sell_ratio: float = 0.7     # 70% 분할매도
    breakeven_cut: float = 0.005        # +0.5% 이하 본전컷
    commission_rate: float = 0.00015    # 0.015%
    tax_rate: float = 0.0023            # 0.23%
    max_consecutive_losses: int = 2     # 2연속 손절 → 당일 종료
    leader_top_n: int = 30              # 거래대금 상위 N종목을 "대장주"로 간주
    scan_start: time = time(9, 30)      # 스캔 시작
    scan_end: time = time(11, 0)        # 스캔 종료 (오전장 위주)
    force_close: time = time(15, 20)    # 강제 청산


@dataclass
class Position:
    code: str
    name: str
    entry_price: float
    quantity: int
    entry_time: datetime
    strategy: str           # "돌파매매" | "눌림매매"
    stop_loss_pct: float
    take_profit_pct: float
    partial_sold: bool = False
    original_quantity: int = 0


@dataclass
class Trade:
    code: str
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    quantity: int
    strategy: str
    pnl: float
    pnl_pct: float
    exit_reason: str
    trade_type: str = "full"  # "full" | "partial"


# ── 데이터 로딩 ─────────────────────────────────────────

def load_data():
    """DB에서 일봉/분봉 데이터 로드."""
    from src.database.connection import get_session
    from sqlalchemy import text

    logger.info("데이터 로딩 시작...")
    t0 = time_module.time()

    with get_session() as session:
        # 1. 5분봉 날짜 범위 확인
        r = session.execute(text(
            "SELECT DISTINCT date(datetime) FROM ohlcv_intraday ORDER BY date(datetime)"
        ))
        intraday_dates = [row[0] for row in r.fetchall()]
        logger.info(f"5분봉 거래일: {len(intraday_dates)}일 ({intraday_dates[0]} ~ {intraday_dates[-1]})")

        # 2. 5분봉 전체 로드
        r = session.execute(text("""
            SELECT code, datetime, open, high, low, close, volume
            FROM ohlcv_intraday
            ORDER BY code, datetime
        """))
        rows = r.fetchall()
        intraday_df = pd.DataFrame(rows, columns=["code", "datetime", "open", "high", "low", "close", "volume"])
        intraday_df["datetime"] = pd.to_datetime(intraday_df["datetime"])
        for col in ["open", "high", "low", "close", "volume"]:
            intraday_df[col] = intraday_df[col].astype(float)
        logger.info(f"5분봉: {len(intraday_df):,}행")

        # 3. 일봉 로드 (5분봉 시작일 -150일부터)
        daily_start = intraday_dates[0] - timedelta(days=200)
        r = session.execute(text("""
            SELECT code, date, open, high, low, close, volume, value, change_rate
            FROM ohlcv_daily
            WHERE date >= :start_date
            ORDER BY code, date
        """), {"start_date": daily_start})
        rows = r.fetchall()
        daily_df = pd.DataFrame(rows, columns=["code", "date", "open", "high", "low", "close", "volume", "value", "change_rate"])
        daily_df["date"] = pd.to_datetime(daily_df["date"]).dt.date
        for col in ["open", "high", "low", "close", "volume", "value"]:
            daily_df[col] = daily_df[col].astype(float)
        daily_df["change_rate"] = daily_df["change_rate"].astype(float)
        logger.info(f"일봉: {len(daily_df):,}행 ({daily_start} ~)")

    elapsed = time_module.time() - t0
    logger.info(f"데이터 로딩 완료: {elapsed:.1f}초")

    return intraday_dates, intraday_df, daily_df


def pregroup_data(intraday_df: pd.DataFrame, daily_df: pd.DataFrame):
    """날짜/종목별로 미리 그룹핑."""
    logger.info("데이터 그룹핑...")

    # 5분봉: {date: {code: DataFrame}}
    intraday_df["_date"] = intraday_df["datetime"].dt.date
    intraday_grouped = {}
    for (d, code), grp in intraday_df.groupby(["_date", "code"]):
        if d not in intraday_grouped:
            intraday_grouped[d] = {}
        intraday_grouped[d][code] = grp.drop(columns=["_date"]).reset_index(drop=True)

    # 일봉: {code: DataFrame (sorted by date)}
    daily_grouped = {}
    for code, grp in daily_df.groupby("code"):
        daily_grouped[code] = grp.sort_values("date").reset_index(drop=True)

    logger.info(f"그룹핑 완료: 일봉 {len(daily_grouped)}종목, 5분봉 {len(intraday_grouped)}일")
    return intraday_grouped, daily_grouped


def get_daily_bars_until(daily_grouped: dict, code: str, until_date: date, lookback: int = 120) -> pd.DataFrame:
    """특정 날짜까지의 일봉 데이터 반환."""
    df = daily_grouped.get(code)
    if df is None or df.empty:
        return pd.DataFrame()
    mask = df["date"] < until_date  # 당일 제외 (전일까지)
    filtered = df[mask].tail(lookback)
    if len(filtered) < 20:
        return pd.DataFrame()
    return filtered


def get_leader_stocks(daily_grouped: dict, target_date: date, top_n: int = 30) -> set[str]:
    """거래대금 상위 종목을 대장주로 간주 (섹터 분석 프록시).
    전일 거래대금 + 등락률로 스코어링."""
    scores = []
    for code, df in daily_grouped.items():
        # 전일 데이터
        mask = df["date"] < target_date
        recent = df[mask].tail(5)
        if len(recent) < 3:
            continue
        last = recent.iloc[-1]
        avg_volume = recent["volume"].mean()
        # 거래대금 * 양봉 여부로 스코어링
        value = last["close"] * last["volume"]
        change = last["change_rate"]
        if change > 0 and avg_volume > 0:
            score = value * (1 + change / 100)
            scores.append((code, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return {code for code, _ in scores[:top_n]}


# ── 백테스트 엔진 ───────────────────────────────────────

class HongStyleBacktest:
    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.daily_analyzer = DailyChartAnalyzer()
        self.pattern_detector = PatternDetector()
        self.signal_generator = SignalGenerator()

        # 상태
        self.cash = self.config.initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.daily_results: list[dict] = []

        # 일별 리스크
        self._consecutive_losses = 0
        self._day_stopped = False
        self._day_trades: list[Trade] = []

    def run(self, intraday_dates, intraday_grouped, daily_grouped):
        """전체 백테스트 실행."""
        logger.info(f"=== 홍인기 백테스트 시작 ({len(intraday_dates)}일) ===")
        logger.info(f"  자본금: {self.config.initial_capital:,}원")
        logger.info(f"  최대 포지션: {self.config.max_positions}개")
        logger.info(f"  손절: -{self.config.stop_loss*100:.0f}%, 익절: +{self.config.take_profit*100:.0f}%")
        logger.info(f"  대장주 기준: 거래대금 상위 {self.config.leader_top_n}종목")

        t0 = time_module.time()
        total_signals = 0
        total_entries = 0

        for i, trading_date in enumerate(intraday_dates):
            # 일일 리셋
            self._consecutive_losses = 0
            self._day_stopped = False
            self._day_trades = []

            day_codes = intraday_grouped.get(trading_date, {})
            if not day_codes:
                continue

            # 대장주 선정 (거래대금 프록시)
            leaders = get_leader_stocks(daily_grouped, trading_date, self.config.leader_top_n)

            signals_today = 0
            entries_today = 0

            # Phase 1: 진입 스캔 (대장주 중심)
            entry_candidates = []
            for code in leaders:
                if code in self.positions:
                    continue
                if code not in day_codes:
                    continue

                # 일봉 분석
                daily_bars = get_daily_bars_until(daily_grouped, code, trading_date)
                if daily_bars.empty:
                    continue

                daily_position = self.daily_analyzer.classify_daily_position(daily_bars)
                ki_score = self.daily_analyzer.calculate_ki(daily_bars)

                # 패턴 감지 (일봉 기반)
                patterns = self.pattern_detector.detect_all_patterns(
                    minute_bars=None,
                    daily_bars=daily_bars,
                    ki_score=ki_score.score,
                    is_leading_sector=True,
                    has_news_catalyst=False,
                )

                # 시그널 생성
                signal = self.signal_generator.generate_entry_signal(
                    stock_code=code,
                    daily_position=daily_position,
                    ki_score=ki_score,
                    patterns=patterns,
                    is_leader=True,
                )

                signals_today += 1

                if signal.action == "buy" and signal.confidence >= self.config.min_confidence:
                    entry_candidates.append({
                        "code": code,
                        "signal": signal,
                        "ki_score": ki_score.score,
                        "daily_position": daily_position.position_type,
                    })

            # 확신도 높은 순으로 정렬
            entry_candidates.sort(key=lambda x: x["signal"].confidence, reverse=True)

            # Phase 2: 5분봉으로 진입 + 포지션 관리
            day_intraday = day_codes
            self._simulate_day(trading_date, day_intraday, entry_candidates, daily_grouped)

            entries_today = len([t for t in self._day_trades if t.trade_type == "entry"])
            total_signals += signals_today
            total_entries += entries_today

            # 일일 결과 기록
            holdings_value = sum(
                p.entry_price * p.quantity for p in self.positions.values()
            )
            total_equity = self.cash + holdings_value
            day_pnl = sum(t.pnl for t in self._day_trades)

            self.daily_results.append({
                "date": trading_date,
                "equity": total_equity,
                "cash": self.cash,
                "positions": len(self.positions),
                "trades": len(self._day_trades),
                "pnl": day_pnl,
                "signals": signals_today,
            })

            if (i + 1) % 10 == 0 or i == len(intraday_dates) - 1:
                logger.info(
                    f"  [{i+1}/{len(intraday_dates)}] {trading_date} | "
                    f"자산={total_equity:,.0f} | 포지션={len(self.positions)} | "
                    f"오늘거래={len(self._day_trades)} | PnL={day_pnl:+,.0f}"
                )

        elapsed = time_module.time() - t0
        logger.info(f"=== 백테스트 완료: {elapsed:.1f}초 ===")
        logger.info(f"  총 시그널: {total_signals}, 총 진입: {total_entries}")

        return self._calc_metrics()

    def _simulate_day(
        self,
        trading_date: date,
        day_intraday: dict[str, pd.DataFrame],
        entry_candidates: list[dict],
        daily_grouped: dict,
    ):
        """하루 5분봉으로 시뮬레이션."""

        # 모든 보유종목 + 진입후보의 5분봉 타임스탬프를 병합
        all_timestamps = set()
        relevant_codes = set(self.positions.keys())
        for cand in entry_candidates:
            relevant_codes.add(cand["code"])

        for code in relevant_codes:
            if code in day_intraday:
                for ts in day_intraday[code]["datetime"]:
                    all_timestamps.add(ts)

        if not all_timestamps:
            return

        sorted_timestamps = sorted(all_timestamps)
        entry_done = set()  # 오늘 이미 진입한 종목

        for ts in sorted_timestamps:
            ts_time = ts.time() if isinstance(ts, datetime) else ts

            # 강제 청산 시간
            if ts_time >= self.config.force_close:
                self._force_close_all(ts, day_intraday)
                break

            # 1. 포지션 모니터 (SL/TP/패턴)
            self._monitor_positions(ts, day_intraday, daily_grouped, trading_date)

            # 2. 진입 (9:30~11:00, 당일 종료 안 됐을 때)
            if (
                self.config.scan_start <= ts_time <= self.config.scan_end
                and not self._day_stopped
                and len(self.positions) < self.config.max_positions
            ):
                for cand in entry_candidates:
                    code = cand["code"]
                    if code in self.positions or code in entry_done:
                        continue
                    if len(self.positions) >= self.config.max_positions:
                        break

                    bars = day_intraday.get(code)
                    if bars is None:
                        continue

                    # 현재 시점까지의 바 확인
                    current_bars = bars[bars["datetime"] <= ts]
                    if len(current_bars) < 2:
                        continue

                    current_price = float(current_bars.iloc[-1]["close"])
                    if current_price <= 0:
                        continue

                    # 포지션 사이징
                    signal = cand["signal"]
                    if signal.confidence >= self.config.confidence_threshold:
                        alloc_pct = self.config.high_confidence_pct
                    else:
                        alloc_pct = self.config.low_confidence_pct

                    max_amount = (self.cash + sum(
                        p.entry_price * p.quantity for p in self.positions.values()
                    )) * alloc_pct
                    qty = int(max_amount / current_price)
                    if qty <= 0:
                        continue

                    cost = current_price * qty
                    commission = cost * self.config.commission_rate
                    if cost + commission > self.cash:
                        qty = int((self.cash * 0.99) / current_price)
                        if qty <= 0:
                            continue
                        cost = current_price * qty
                        commission = cost * self.config.commission_rate

                    # 진입
                    self.cash -= (cost + commission)
                    pos = Position(
                        code=code,
                        name=code,
                        entry_price=current_price,
                        quantity=qty,
                        entry_time=ts,
                        strategy=signal.method,
                        stop_loss_pct=signal.stop_loss,
                        take_profit_pct=signal.take_profit,
                        original_quantity=qty,
                    )
                    self.positions[code] = pos
                    entry_done.add(code)

        # 장 마감 후에도 포지션이 남아있으면 강제 청산
        if self.positions:
            last_ts = sorted_timestamps[-1] if sorted_timestamps else datetime.combine(trading_date, time(15, 20))
            self._force_close_all(last_ts, day_intraday)

    def _monitor_positions(
        self, ts, day_intraday, daily_grouped, trading_date
    ):
        """5분봉 시점에서 보유 포지션 SL/TP/패턴 체크."""
        to_close = []
        to_partial = []

        for code, pos in list(self.positions.items()):
            bars = day_intraday.get(code)
            if bars is None:
                continue

            current_bars = bars[bars["datetime"] <= ts]
            if current_bars.empty:
                continue

            current_price = float(current_bars.iloc[-1]["close"])
            if current_price <= 0:
                continue

            pnl_ratio = (current_price - pos.entry_price) / pos.entry_price

            # 1. 손절
            if pnl_ratio <= -pos.stop_loss_pct:
                to_close.append((code, current_price, "손절", ts))
                self._consecutive_losses += 1
                if self._consecutive_losses >= self.config.max_consecutive_losses:
                    self._day_stopped = True
                continue

            # 2. 분할매도 (+5%, partial 안 한 경우)
            if pnl_ratio >= pos.take_profit_pct and not pos.partial_sold:
                sell_qty = int(pos.quantity * self.config.partial_sell_ratio)
                if sell_qty > 0 and sell_qty < pos.quantity:
                    to_partial.append((code, current_price, sell_qty, ts))
                    self._consecutive_losses = 0
                continue

            # 3. 본전컷 (partial_sold 후 원가 복귀)
            if pos.partial_sold and pnl_ratio <= self.config.breakeven_cut:
                to_close.append((code, current_price, "본전컷", ts))
                continue

            # 4. 수익 중이면 연속손절 리셋
            if pnl_ratio > 0:
                self._consecutive_losses = 0

        # 실행: 분할매도
        for code, price, sell_qty, exit_ts in to_partial:
            self._execute_partial_sell(code, price, sell_qty, exit_ts)

        # 실행: 전량 매도
        for code, price, reason, exit_ts in to_close:
            self._execute_close(code, price, reason, exit_ts)

    def _execute_close(self, code: str, price: float, reason: str, exit_time):
        """전량 매도."""
        pos = self.positions.pop(code, None)
        if not pos:
            return

        proceeds = price * pos.quantity
        commission = proceeds * self.config.commission_rate
        tax = proceeds * self.config.tax_rate
        self.cash += (proceeds - commission - tax)

        pnl = (price - pos.entry_price) * pos.quantity - commission - tax
        entry_cost = pos.entry_price * pos.quantity
        pnl_pct = pnl / entry_cost * 100 if entry_cost > 0 else 0

        trade = Trade(
            code=code,
            entry_price=pos.entry_price,
            exit_price=price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            quantity=pos.quantity,
            strategy=pos.strategy,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            trade_type="full",
        )
        self.trades.append(trade)
        self._day_trades.append(trade)

    def _execute_partial_sell(self, code: str, price: float, sell_qty: int, exit_time):
        """분할매도."""
        pos = self.positions.get(code)
        if not pos:
            return

        proceeds = price * sell_qty
        commission = proceeds * self.config.commission_rate
        tax = proceeds * self.config.tax_rate
        self.cash += (proceeds - commission - tax)

        pnl = (price - pos.entry_price) * sell_qty - commission - tax
        entry_cost = pos.entry_price * sell_qty
        pnl_pct = pnl / entry_cost * 100 if entry_cost > 0 else 0

        trade = Trade(
            code=code,
            entry_price=pos.entry_price,
            exit_price=price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            quantity=sell_qty,
            strategy=pos.strategy,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason="1차익절",
            trade_type="partial",
        )
        self.trades.append(trade)
        self._day_trades.append(trade)

        pos.quantity -= sell_qty
        pos.partial_sold = True

    def _force_close_all(self, ts, day_intraday):
        """강제 전량 청산."""
        for code in list(self.positions.keys()):
            bars = day_intraday.get(code)
            if bars is not None and not bars.empty:
                price = float(bars.iloc[-1]["close"])
            else:
                price = self.positions[code].entry_price
            self._execute_close(code, price, "장마감", ts)

    def _calc_metrics(self) -> dict:
        """성과 지표 계산."""
        if not self.trades:
            return {"error": "거래 없음"}

        # 전체 거래 (partial 포함)
        all_trades = self.trades
        # 실질 청산 (partial + full close만, 진입 제외)
        close_trades = [t for t in all_trades if t.exit_reason != "entry"]

        total = len(close_trades)
        wins = [t for t in close_trades if t.pnl > 0]
        losses = [t for t in close_trades if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in close_trades)
        win_rate = len(wins) / total * 100 if total > 0 else 0

        avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0
        avg_loss = np.mean([t.pnl_pct for t in losses]) if losses else 0

        # 전략별 분석
        by_strategy = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for t in close_trades:
            by_strategy[t.strategy]["trades"] += 1
            if t.pnl > 0:
                by_strategy[t.strategy]["wins"] += 1
            by_strategy[t.strategy]["pnl"] += t.pnl

        # 청산 사유별 분석
        by_reason = defaultdict(lambda: {"count": 0, "pnl": 0.0})
        for t in close_trades:
            by_reason[t.exit_reason]["count"] += 1
            by_reason[t.exit_reason]["pnl"] += t.pnl

        # 일별 equity curve
        equity_curve = [r["equity"] for r in self.daily_results]
        peak = self.config.initial_capital
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

        final_equity = self.cash
        total_return = (final_equity - self.config.initial_capital) / self.config.initial_capital * 100

        return {
            "initial_capital": self.config.initial_capital,
            "final_equity": int(final_equity),
            "total_return_pct": round(total_return, 2),
            "total_pnl": int(total_pnl),
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "by_strategy": dict(by_strategy),
            "by_reason": dict(by_reason),
            "trading_days": len(self.daily_results),
        }


def print_results(metrics: dict):
    """결과 출력."""
    print("\n" + "=" * 70)
    print("  홍인기 전략 백테스트 결과")
    print("=" * 70)

    print(f"\n  기간: {metrics['trading_days']}거래일")
    print(f"  초기자본: {metrics['initial_capital']:>15,}원")
    print(f"  최종자산: {metrics['final_equity']:>15,}원")
    print(f"  총수익률: {metrics['total_return_pct']:>+14.2f}%")
    print(f"  총손익:   {metrics['total_pnl']:>+15,}원")

    print(f"\n  ── 거래 통계 ──")
    print(f"  총 거래:  {metrics['total_trades']}건")
    print(f"  승리:     {metrics['winning_trades']}건")
    print(f"  패배:     {metrics['losing_trades']}건")
    print(f"  승률:     {metrics['win_rate']:.1f}%")
    print(f"  평균 수익: {metrics['avg_win_pct']:+.2f}%")
    print(f"  평균 손실: {metrics['avg_loss_pct']:+.2f}%")
    print(f"  최대낙폭: {metrics['max_drawdown_pct']:.2f}%")

    print(f"\n  ── 전략별 성과 ──")
    for strategy, stats in metrics["by_strategy"].items():
        wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
        print(f"  {strategy:>8s}: {stats['trades']:>3}건 | 승률 {wr:>5.1f}% | PnL {stats['pnl']:>+10,.0f}원")

    print(f"\n  ── 청산 사유별 ──")
    for reason, stats in metrics["by_reason"].items():
        print(f"  {reason:>8s}: {stats['count']:>3}건 | PnL {stats['pnl']:>+10,.0f}원")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")

    # 데이터 로드
    intraday_dates, intraday_df, daily_df = load_data()

    # 그룹핑
    intraday_grouped, daily_grouped = pregroup_data(intraday_df, daily_df)

    # 백테스트 실행
    bt = HongStyleBacktest()
    metrics = bt.run(intraday_dates, intraday_grouped, daily_grouped)

    # 결과 출력
    print_results(metrics)
