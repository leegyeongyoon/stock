"""Optimized intraday backtest engine (V2) - 20~50x faster than V1.

Key optimizations:
- Pre-group data by date (O(1) date lookup vs O(N) filter)
- Pre-compute all indicators per stock per day via numpy arrays
- Fast-path signal checking using array indexing (no DataFrame slicing)
- Merged timestamp iteration across all stocks per day
"""

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


class IntradayBacktestEngineV2(IntradayBacktestEngine):
    """Optimized intraday backtest engine using pre-computed numpy arrays."""

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

                    # Stop loss
                    if low_val <= pos.stop_loss:
                        trade = self._close_position(pos, pos.stop_loss, ts, "Stop loss")
                        all_trades.append(trade)
                        capital += trade.pnl
                        day_pnl += trade.pnl
                        del positions[code]
                        continue

                    # Take profit
                    if high_val >= pos.take_profit:
                        trade = self._close_position(pos, pos.take_profit, ts, "Take profit")
                        all_trades.append(trade)
                        capital += trade.pnl
                        day_pnl += trade.pnl
                        del positions[code]
                        continue

                    # Strategy exit signal (fast path)
                    exit_signal = strategy.check_exit_fast(pos, idx, ind)
                    if exit_signal:
                        price = float(ind["close"][idx])
                        trade = self._close_position(pos, price, ts, exit_signal)
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

                    for code, idx, ind, signal, _ in pending_signals:
                        if len(positions) >= self.config.max_positions:
                            break

                        price = float(ind["close"][idx])
                        quantity = int(available_capital / price)

                        if quantity > 0:
                            stop_loss_price = price * (1 - signal.get("stop_loss", 0.02))
                            take_profit_price = price * (1 + signal.get("take_profit", 0.03))

                            positions[code] = IntradayPosition(
                                code=code,
                                entry_price=price,
                                entry_time=ts,
                                quantity=quantity,
                                strategy_name=strategy.name,
                                stop_loss=stop_loss_price,
                                take_profit=take_profit_price,
                                entry_reason=signal.get("reason", ""),
                                entry_bar_idx=idx,
                            )

                            commission = price * quantity * self.config.commission_rate
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
