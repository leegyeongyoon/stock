"""Data manager - maintains per-stock daily DataFrames and coordinates polling."""

import asyncio
from datetime import datetime, time

import pandas as pd
from loguru import logger

from src.broker.kis_client import KISClient
from src.broker.kis_models import WSTickData
from src.pipeline.bar_aggregator import BarAggregator
from src.pipeline.stock_universe import StockUniverse


class DataManager:
    """Manages real-time data collection for all stocks in the universe.

    Hybrid approach:
    - REST polling (all 462 stocks): 5-min bar API, round-robin groups
    - Priority polling (held + near-entry): every cycle instead of round-robin
    - WebSocket (held positions ≤40): real-time tick → bar aggregation
    - Current price API: real-time price for order execution & SL/TP monitoring
    """

    def __init__(
        self,
        client: KISClient,
        universe: StockUniverse,
        bar_interval: int = 5,
    ):
        self.client = client
        self.universe = universe
        self.aggregator = BarAggregator(interval_minutes=bar_interval)
        self._polling_task: asyncio.Task | None = None
        self._running = False

        # Priority codes: polled every cycle (held positions + near-entry candidates)
        self._priority_codes: set[str] = set()
        # Current price cache: code → (price, timestamp)
        self._price_cache: dict[str, tuple[int, float]] = {}

    def get_today_df(self, code: str) -> pd.DataFrame:
        """Get today's full DataFrame for a stock.

        This is fed directly into strategy.precompute_day(day_df).
        """
        return self.aggregator.to_dataframe(code)

    def get_bar_count(self, code: str) -> int:
        return self.aggregator.get_bar_count(code)

    def get_stock_name(self, code: str) -> str:
        """Get stock name from universe."""
        return self.universe.get_name(code)

    # ── Priority Codes ────────────────────────────────────

    def set_priority_codes(self, codes: set[str]) -> None:
        """Update the set of priority codes (held + near-entry)."""
        old_count = len(self._priority_codes)
        self._priority_codes = set(codes)
        if len(self._priority_codes) != old_count:
            logger.debug(
                f"우선 폴링 종목 업데이트: {len(self._priority_codes)}개"
            )

    def add_priority_codes(self, codes: set[str]) -> None:
        """Add codes to priority set."""
        self._priority_codes |= codes

    def remove_priority_codes(self, codes: set[str]) -> None:
        """Remove codes from priority set."""
        self._priority_codes -= codes

    # ── Current Price API ─────────────────────────────────

    async def fetch_current_price(self, code: str) -> int:
        """Fetch real-time current price for a single stock.

        Returns 0 on failure (caller should fallback to last bar close).
        """
        try:
            sp = await self.client.get_current_price(code)
            price = sp.current_price
            if price > 0:
                self._price_cache[code] = (price, asyncio.get_event_loop().time())
            return price
        except Exception as e:
            logger.debug(f"현재가 조회 실패 {code}: {e}")
            return 0

    async def fetch_current_prices(self, codes: list[str]) -> dict[str, int]:
        """Batch fetch current prices. Returns {code: price}."""
        results: dict[str, int] = {}
        for code in codes:
            price = await self.fetch_current_price(code)
            if price > 0:
                results[code] = price
            # Small delay to respect rate limit (20 req/sec)
            await asyncio.sleep(0.06)
        return results

    def get_cached_price(self, code: str, max_age: float = 10.0) -> int:
        """Get cached current price if fresh enough. Returns 0 if stale/missing."""
        cached = self._price_cache.get(code)
        if cached is None:
            return 0
        price, ts = cached
        now = asyncio.get_event_loop().time()
        if now - ts > max_age:
            return 0
        return price

    def on_tick(self, tick: WSTickData) -> None:
        """Handle a WebSocket tick event."""
        self.aggregator.add_tick(tick)
        # Also update price cache from ticks (most real-time source)
        if tick.price > 0:
            self._price_cache[tick.code] = (
                tick.price,
                asyncio.get_event_loop().time(),
            )

    async def start_polling(self) -> None:
        """Start the REST polling loop for all stocks."""
        self._running = True
        self._polling_task = asyncio.create_task(self._polling_loop())
        logger.info("데이터 폴링 시작")

    async def stop_polling(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        logger.info("데이터 폴링 중지")

    async def _polling_loop(self) -> None:
        """Priority-aware polling loop.

        Every cycle:
        1. Poll ALL priority codes (held + near-entry) → ~6sec interval
        2. Poll ONE normal group (round-robin) → full cycle ~60sec

        Result: priority codes updated every ~6sec, others every ~60sec.
        """
        groups = self.universe.get_polling_groups(group_size=50)
        if not groups:
            logger.warning("폴링할 종목이 없습니다")
            return

        group_idx = 0

        while self._running:
            try:
                # 1. Priority codes first (every cycle)
                if self._priority_codes:
                    priority_list = list(self._priority_codes)
                    tasks = [self._fetch_bars_safe(c) for c in priority_list]
                    await asyncio.gather(*tasks)

                # 2. One normal group (skip priority codes to avoid duplicate)
                group = groups[group_idx % len(groups)]
                group_idx += 1
                normal_codes = [
                    c for c in group if c not in self._priority_codes
                ]
                if normal_codes:
                    tasks = [self._fetch_bars_safe(c) for c in normal_codes]
                    await asyncio.gather(*tasks)

                # Spread groups: if 10 groups, poll 1 group every ~6 seconds
                interval = max(60.0 / len(groups), 3.0)
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"폴링 루프 오류: {e}")
                await asyncio.sleep(5)

    async def _fetch_bars_safe(self, code: str) -> None:
        """Fetch minute bars for a single stock with error handling."""
        try:
            bars = await self.client.get_minute_bars(code, time_unit="5", count=50)
            if bars:
                self.aggregator.add_rest_bars(code, bars)
        except Exception as e:
            logger.debug(f"분봉 조회 실패 {code}: {e}")

    async def fetch_all_current_bars(self) -> None:
        """Fetch current bars for all stocks once (used at market open)."""
        codes = self.universe.codes
        logger.info(f"전체 {len(codes)}종목 분봉 일괄 조회 시작")

        for i in range(0, len(codes), 50):
            batch = codes[i:i + 50]
            tasks = [self._fetch_bars_safe(c) for c in batch]
            await asyncio.gather(*tasks)
            await asyncio.sleep(1)  # rate limit between batches

        logger.info("전체 종목 분봉 일괄 조회 완료")

    def clear_day(self) -> None:
        """Reset all data for a new trading day."""
        self.aggregator.clear_day()
        logger.info("일간 데이터 초기화")
