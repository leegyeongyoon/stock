"""Optimized intraday backtest engine (V2) - 20~50x faster than V1.

Key optimizations:
- Pre-group data by date (O(1) date lookup vs O(N) filter)
- Pre-compute all indicators per stock per day via numpy arrays
- Fast-path signal checking using array indexing (no DataFrame slicing)
- Merged timestamp iteration across all stocks per day
"""

from dataclasses import replace
from datetime import time

import numpy as np
import pandas as pd
from tqdm import tqdm

from src.backtest.intraday_engine import (
    IntradayBacktestConfig,
    IntradayBacktestEngine,
    IntradayMetrics,
    IntradayPosition,
    IntradayTrade,
    MARKET_OPEN,
    MARKET_CLOSE,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _vol_avg_at(ind: dict, idx: int):
    """precompute의 20일 평균 거래량(있으면)을 NaN-safe하게 반환. realism 슬리피지용."""
    arr = ind.get("vol_avg_20")
    if arr is None or idx >= len(arr):
        return None
    v = float(arr[idx])
    return v if v == v and v > 0 else None  # NaN 체크


def _normalize_exit(exit_signal) -> tuple[str, str, float]:
    """check_exit_fast 반환을 (action, reason, fraction)으로 정규화.

    - str  → 전체청산 ("close")
    - dict → {"action": "close"|"partial", "reason": str, "fraction": float}
    """
    if isinstance(exit_signal, dict):
        action = exit_signal.get("action", "close")
        reason = exit_signal.get("reason", action)
        fraction = float(exit_signal.get("fraction", 1.0))
        return action, reason, fraction
    return "close", str(exit_signal), 1.0


class IntradayBacktestEngineV2(IntradayBacktestEngine):
    """Optimized intraday backtest engine using pre-computed numpy arrays."""

    def _sell_fill(self, realism, level_price: float, ind: dict, idx: int, qty: int) -> float:
        """매도 체결가. realism이 있으면 슬리피지로 레벨을 뚫고 불리하게 체결."""
        if realism is None:
            return level_price
        return realism.apply_slippage(
            "sell", level_price,
            float(ind["high"][idx]), float(ind["low"][idx]), float(ind["volume"][idx]),
            qty, _vol_avg_at(ind, idx),
        )

    def run(
        self,
        strategy,
        data: dict[str, pd.DataFrame],
        show_progress: bool = True,
        daily_context: dict = None,
    ) -> tuple[IntradayMetrics, list[IntradayTrade]]:
        logger.info(f"[V2] Starting intraday backtest for {strategy.name}")
        logger.info(f"Initial capital: {self.config.initial_capital:,}원")
        logger.info(f"Stocks: {len(data)}")

        capital = self.config.initial_capital
        positions: dict[str, IntradayPosition] = {}
        all_trades: list[IntradayTrade] = []
        equity_curve = [capital]
        daily_pnl = {}

        # --- Phase 1: Pre-group all data by date ---
        # {date: {code: day_df}} - O(1) lookup per date/code
        date_code_df: dict[object, dict[str, pd.DataFrame]] = {}
        all_dates = set()

        for code, df in data.items():
            grouped = df.groupby(df.index.date)
            for dt, day_df in grouped:
                all_dates.add(dt)
                if dt not in date_code_df:
                    date_code_df[dt] = {}
                date_code_df[dt][code] = day_df

        all_dates = sorted(all_dates)
        logger.info(f"Trading days: {len(all_dates)}")

        force_close_time = self.config.force_close_time
        realism = self.config.realism            # None이면 기존 동작
        execution = self.config.execution         # "signal_close" | "next_open"

        for current_date in tqdm(all_dates, desc="Backtesting [V2]", disable=not show_progress):
            day_pnl = 0.0
            day_data = date_code_df.get(current_date)
            if not day_data:
                continue

            # --- Phase 2: Pre-compute indicators for each stock this day ---
            indicators: dict[str, dict] = {}
            ts_to_idx: dict[str, dict] = {}  # code -> {timestamp: bar_idx}

            for code, day_df in day_data.items():
                # daily_context 주입 (홍인기 필터용)
                ctx = None
                if daily_context and code in daily_context:
                    ctx = daily_context[code].get(current_date)
                strategy.set_daily_context(code, current_date, ctx)

                ind = strategy.precompute_day(day_df)
                indicators[code] = ind
                ts_to_idx[code] = {ts: i for i, ts in enumerate(ind["timestamps"])}

            # --- Phase 3: Merge all timestamps, iterate once ---
            all_timestamps_set = set()
            for code, day_df in day_data.items():
                all_timestamps_set.update(day_df.index.tolist())
            all_timestamps = sorted(all_timestamps_set)

            for ts in all_timestamps:
                current_time = ts.time() if hasattr(ts, 'time') else ts

                if hasattr(current_time, 'hour'):
                    if current_time < MARKET_OPEN or current_time > MARKET_CLOSE:
                        continue

                # Force close before market close
                if hasattr(current_time, 'hour') and current_time >= force_close_time:
                    for code in list(positions.keys()):
                        if code in indicators and ts in ts_to_idx.get(code, {}):
                            idx = ts_to_idx[code][ts]
                            ind = indicators[code]
                            price = float(ind["close"][idx])
                            trade = self._close_position(
                                positions[code], price, ts, "Market close",
                            )
                            all_trades.append(trade)
                            capital += trade.pnl
                            day_pnl += trade.pnl
                            del positions[code]
                    continue

                # --- Check existing positions for exit ---
                for code in list(positions.keys()):
                    if code not in ts_to_idx or ts not in ts_to_idx[code]:
                        continue

                    idx = ts_to_idx[code][ts]
                    ind = indicators[code]
                    pos = positions[code]

                    low_val = float(ind["low"][idx])
                    high_val = float(ind["high"][idx])

                    # 트레일링용 최고가 갱신 (불변: 새 객체로 교체). 전략이 pos.peak_price로 트레일링 구현 가능
                    if high_val > pos.peak_price:
                        pos = positions[code] = replace(pos, peak_price=high_val)

                    # Stop loss
                    if low_val <= pos.stop_loss:
                        fill = self._sell_fill(realism, pos.stop_loss, ind, idx, pos.quantity)
                        trade = self._close_position(pos, fill, ts, "Stop loss")
                        all_trades.append(trade)
                        capital += trade.pnl
                        day_pnl += trade.pnl
                        del positions[code]
                        continue

                    # Take profit
                    if high_val >= pos.take_profit:
                        fill = self._sell_fill(realism, pos.take_profit, ind, idx, pos.quantity)
                        trade = self._close_position(pos, fill, ts, "Take profit")
                        all_trades.append(trade)
                        capital += trade.pnl
                        day_pnl += trade.pnl
                        del positions[code]
                        continue

                    # Strategy exit signal (fast path) — str(전체청산) 또는 dict(부분/트레일링)
                    exit_signal = strategy.check_exit_fast(pos, idx, ind)
                    if exit_signal:
                        close_px = float(ind["close"][idx])
                        action, reason, fraction = _normalize_exit(exit_signal)
                        if action == "partial":
                            sold = int(pos.quantity * fraction)
                            if 0 < sold < pos.quantity:
                                fill = self._sell_fill(realism, close_px, ind, idx, sold)
                                trade = self._close_position_qty(pos, fill, ts, reason, sold)
                                all_trades.append(trade)
                                capital += trade.pnl
                                day_pnl += trade.pnl
                                # 불변: 부분익절 후 잔량/플래그를 새 객체로 교체
                                positions[code] = replace(
                                    pos, quantity=pos.quantity - sold, partial_done=True
                                )
                                continue
                            # sold가 전체 이상이면 전체청산으로 처리
                        fill = self._sell_fill(realism, close_px, ind, idx, pos.quantity)
                        trade = self._close_position(pos, fill, ts, reason)
                        all_trades.append(trade)
                        capital += trade.pnl
                        day_pnl += trade.pnl
                        del positions[code]

                # --- Check for new entries (with priority ranking) ---
                if len(positions) < self.config.max_positions:
                    available_capital = capital * self.config.position_size

                    # 모든 시그널 수집
                    pending_signals = []
                    for code in day_data:
                        if code in positions:
                            continue
                        if code not in ts_to_idx or ts not in ts_to_idx[code]:
                            continue

                        idx = ts_to_idx[code][ts]
                        ind = indicators[code]

                        # daily_context 설정 (코드별)
                        if daily_context and code in daily_context:
                            ctx = daily_context[code].get(current_date)
                            strategy.set_daily_context(code, current_date, ctx)

                        signal = strategy.check_entry_fast(code, idx, ind)
                        if signal:
                            confidence = signal.get("confidence", 1.0)
                            pending_signals.append((code, idx, ind, signal, confidence))

                    # 확신도 내림차순 정렬
                    pending_signals.sort(key=lambda x: x[4], reverse=True)

                    for code, sig_idx, ind, signal, _ in pending_signals:
                        if len(positions) >= self.config.max_positions:
                            break

                        # 체결 시점: next_open이면 다음 봉 시가, 아니면 신호 봉 종가
                        if execution == "next_open":
                            fill_idx = sig_idx + 1
                            if fill_idx >= ind["n_bars"]:
                                continue  # 다음 봉 없음 → 진입 불가
                            base_price = float(ind["open"][fill_idx])
                            entry_ts = ind["timestamps"][fill_idx]
                        else:
                            fill_idx = sig_idx
                            base_price = float(ind["close"][sig_idx])
                            entry_ts = ts

                        if base_price <= 0:
                            continue
                        desired_qty = int(available_capital / base_price)
                        if desired_qty <= 0:
                            continue

                        # 체결 게이트 (realism): 상한가 잠김/유동성/슬리피지 반영
                        if realism is not None:
                            res = realism.can_fill(
                                "buy", base_price,
                                float(ind["high"][fill_idx]), float(ind["low"][fill_idx]),
                                float(ind["volume"][fill_idx]), desired_qty,
                                is_limit_locked=bool(signal.get("limit_locked", False)),
                                vol_avg_20=_vol_avg_at(ind, fill_idx),
                            )
                            if res.filled_qty <= 0:
                                continue
                            qty = res.filled_qty
                            entry_price = res.fill_price
                        else:
                            qty = desired_qty
                            entry_price = base_price

                        stop_loss_price = entry_price * (1 - signal.get("stop_loss", 0.02))
                        take_profit_price = entry_price * (1 + signal.get("take_profit", 0.03))

                        positions[code] = IntradayPosition(
                            code=code,
                            entry_price=entry_price,
                            entry_time=entry_ts,
                            quantity=qty,
                            strategy_name=strategy.name,
                            stop_loss=stop_loss_price,
                            take_profit=take_profit_price,
                            entry_reason=signal.get("reason", ""),
                            entry_bar_idx=fill_idx,
                            peak_price=entry_price,
                            original_quantity=qty,
                        )

                        commission = entry_price * qty * self.config.commission_rate
                        capital -= commission

            # Close remaining positions at end of day
            for code in list(positions.keys()):
                if code in indicators:
                    ind = indicators[code]
                    last_idx = ind["n_bars"] - 1
                    last_price = float(ind["close"][last_idx])
                    last_ts = ind["timestamps"][last_idx]
                    trade = self._close_position(
                        positions[code], last_price, last_ts, "End of day",
                    )
                    all_trades.append(trade)
                    capital += trade.pnl
                    day_pnl += trade.pnl
                    del positions[code]

            daily_pnl[current_date] = day_pnl
            equity_curve.append(capital)

        metrics = self._calculate_metrics(
            all_trades, equity_curve, daily_pnl, len(all_dates),
        )

        logger.info(f"[V2] Backtest completed: {metrics.total_trades} trades")
        logger.info(f"Win rate: {metrics.win_rate:.1f}%")
        logger.info(f"Total return: {metrics.total_return_pct:.2f}%")
        logger.info(f"Total P&L: {metrics.total_pnl:,.0f}원")

        return metrics, all_trades
