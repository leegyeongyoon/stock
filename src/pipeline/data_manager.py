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
    - WebSocket (held positions ≤40): real-time tick → bar aggregation
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

    def get_today_df(self, code: str) -> pd.DataFrame:
        """Get today's full DataFrame for a stock.

        This is fed directly into strategy.precompute_day(day_df).
        """
        return self.aggregator.to_dataframe(code)

    def get_bar_count(self, code: str) -> int:
        return self.aggregator.get_bar_count(code)

    def on_tick(self, tick: WSTickData) -> None:
        """Handle a WebSocket tick event."""
        self.aggregator.add_tick(tick)

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
        """Round-robin poll all stock groups every 5 minutes."""
        groups = self.universe.get_polling_groups(group_size=50)
        if not groups:
            logger.warning("폴링할 종목이 없습니다")
            return

        group_idx = 0

        while self._running:
            try:
                # Pick current group
                group = groups[group_idx % len(groups)]
                group_idx += 1

                # Poll each stock in the group
                tasks = [
                    self._fetch_bars_safe(code)
                    for code in group
                ]
                await asyncio.gather(*tasks)

                # Wait until next polling cycle
                # Spread groups: if 10 groups, poll 1 group every 30 seconds
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
