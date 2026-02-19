"""Shared KIS client singleton for account info queries.

Provides a server-global KIS client that can be used to fetch
balance/holdings data even when the trading engine is not running.
"""

import asyncio
import logging

from src.broker.kis_auth import KISAuth
from src.broker.kis_client import KISClient
from src.config.settings import settings

logger = logging.getLogger(__name__)

_shared_client: KISClient | None = None
_init_lock = asyncio.Lock()


async def get_shared_client() -> KISClient | None:
    """Get or create the server-global shared KIS client (singleton).

    Returns None if KIS API keys are not configured.
    """
    global _shared_client

    if not settings.kis_app_key:
        return None

    if _shared_client and _shared_client._client:
        return _shared_client

    async with _init_lock:
        # Double-check after acquiring lock
        if _shared_client and _shared_client._client:
            return _shared_client

        try:
            auth = KISAuth(
                app_key=settings.kis_app_key,
                app_secret=settings.kis_app_secret,
                account_no=settings.kis_account_no,
                is_mock=settings.kis_is_mock,
            )
            client = KISClient(auth)
            await client.start()
            _shared_client = client
            logger.info("공유 KIS 클라이언트 생성 완료")
            return _shared_client
        except Exception as e:
            logger.error(f"공유 KIS 클라이언트 생성 실패: {e}")
            return None


async def get_client_for_engine(engine) -> KISClient | None:
    """Return engine.client if available, otherwise shared client."""
    if engine.client:
        return engine.client
    return await get_shared_client()


async def cleanup():
    """Cleanup shared client on server shutdown."""
    global _shared_client
    if _shared_client:
        try:
            await _shared_client.stop()
            logger.info("공유 KIS 클라이언트 정리 완료")
        except Exception as e:
            logger.warning(f"공유 KIS 클라이언트 정리 실패: {e}")
        _shared_client = None
