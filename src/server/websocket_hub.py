"""WebSocket hub for real-time push to dashboard clients."""

import asyncio
import json
from datetime import datetime

from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    """Manages WebSocket connections for a specific channel."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections = [c for c in self._connections if c != ws]

    async def broadcast(self, data: dict) -> None:
        message = json.dumps(data, default=str)
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


class WebSocketHub:
    """Central hub managing all WebSocket channels."""

    def __init__(self):
        self.positions = ConnectionManager()
        self.orders = ConnectionManager()
        self.signals = ConnectionManager()
        self.pnl = ConnectionManager()
        self.system = ConnectionManager()
        self._pnl_task: asyncio.Task | None = None

    async def broadcast_position(self, data: dict) -> None:
        await self.positions.broadcast(data)

    async def broadcast_order(self, data: dict) -> None:
        await self.orders.broadcast(data)

    async def broadcast_signal(self, data: dict) -> None:
        await self.signals.broadcast(data)

    async def broadcast_pnl(self, data: dict) -> None:
        await self.pnl.broadcast(data)

    async def broadcast_system(self, data: dict) -> None:
        await self.system.broadcast(data)

    def start_pnl_push(self, get_pnl_fn) -> None:
        """Start periodic PnL broadcasting."""
        self._pnl_task = asyncio.create_task(self._pnl_loop(get_pnl_fn))

    async def _pnl_loop(self, get_pnl_fn) -> None:
        while True:
            try:
                if self.pnl.count > 0:
                    data = get_pnl_fn()
                    data["timestamp"] = datetime.now().isoformat()
                    await self.broadcast_pnl(data)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"PnL push 오류: {e}")
                await asyncio.sleep(5)


# Global hub instance
hub = WebSocketHub()
