"""5-minute bar aggregation from real-time tick data."""

from datetime import datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from src.broker.kis_models import MinuteBar, WSTickData


class BarAggregator:
    """Aggregates real-time ticks into 5-minute OHLCV bars.

    For stocks with WebSocket subscription, builds bars from tick data.
    For REST-polled stocks, accepts pre-built bars from the API.
    """

    def __init__(self, interval_minutes: int = 5):
        self.interval = interval_minutes
        # code -> list of completed MinuteBar
        self._completed_bars: dict[str, list[MinuteBar]] = {}
        # code -> current building bar state
        self._building: dict[str, dict[str, Any]] = {}

    def get_bars(self, code: str) -> list[MinuteBar]:
        """Get all completed bars for a stock today."""
        return self._completed_bars.get(code, [])

    def get_bar_count(self, code: str) -> int:
        return len(self._completed_bars.get(code, []))

    def add_tick(self, tick: WSTickData) -> MinuteBar | None:
        """Process a tick and return a completed bar if interval boundary crossed."""
        code = tick.code
        price = tick.price
        volume = tick.volume

        # Determine bar slot
        now = datetime.now()
        bar_start = self._get_bar_start(now)

        if code not in self._building:
            self._building[code] = {
                "bar_start": bar_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
            }
            return None

        building = self._building[code]

        # New bar interval → finalize previous bar
        if bar_start > building["bar_start"]:
            completed = MinuteBar(
                code=code,
                datetime=building["bar_start"],
                open=building["open"],
                high=building["high"],
                low=building["low"],
                close=building["close"],
                volume=building["volume"],
            )
            self._completed_bars.setdefault(code, []).append(completed)

            # Start new bar
            self._building[code] = {
                "bar_start": bar_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
            }
            return completed

        # Same bar interval → update OHLCV
        building["high"] = max(building["high"], price)
        building["low"] = min(building["low"], price)
        building["close"] = price
        building["volume"] += volume
        return None

    def add_rest_bars(self, code: str, bars: list[MinuteBar]) -> None:
        """Add bars fetched from REST API (for non-WebSocket stocks)."""
        existing = self._completed_bars.get(code, [])
        existing_times = {b.datetime for b in existing}

        new_bars = [b for b in bars if b.datetime not in existing_times]
        if new_bars:
            existing.extend(new_bars)
            existing.sort(key=lambda b: b.datetime)
            self._completed_bars[code] = existing

    def to_dataframe(self, code: str) -> pd.DataFrame:
        """Convert completed bars to DataFrame matching strategy expectations."""
        bars = self._completed_bars.get(code, [])
        if not bars:
            return pd.DataFrame()

        records = []
        for b in bars:
            records.append({
                "datetime": b.datetime,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            })

        df = pd.DataFrame(records)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    def clear_day(self) -> None:
        """Clear all bars (call at end of trading day)."""
        self._completed_bars.clear()
        self._building.clear()

    def _get_bar_start(self, dt: datetime) -> datetime:
        """Round down to nearest N-minute interval."""
        minute = (dt.minute // self.interval) * self.interval
        return dt.replace(minute=minute, second=0, microsecond=0)
