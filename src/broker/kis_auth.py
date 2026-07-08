"""KIS OAuth2 authentication - token issuance and renewal."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from loguru import logger

from src.broker.kis_constants import (
    MOCK_BASE_URL,
    REAL_BASE_URL,
    TOKEN_PATH,
    TOKEN_REVOKE_PATH,
)
from src.broker.kis_models import TokenInfo


class KISAuth:
    """Manages KIS API OAuth2 access tokens."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_no: str,
        is_mock: bool = True,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        # 계좌번호 파싱: "50162472-01" or "5016247201" → prefix=50162472, suffix=01
        clean = account_no.replace("-", "")
        self.account_prefix = clean[:8] if len(clean) >= 8 else clean
        self.account_suffix = clean[8:10] if len(clean) > 8 else "01"
        self.is_mock = is_mock
        self.base_url = MOCK_BASE_URL if is_mock else REAL_BASE_URL
        self._token: TokenInfo | None = None
        self._lock = asyncio.Lock()
        # 토큰 디스크 캐시(24h 유효) — 재시작마다 재발급 방지(rate limit 회피). 모의/실전 분리.
        self._cache_path = Path.home() / ".config" / f"kis_token_{'mock' if is_mock else 'live'}.json"

    @property
    def token(self) -> TokenInfo | None:
        return self._token

    @property
    def is_token_valid(self) -> bool:
        if self._token is None:
            return False
        return datetime.now() < self._token.expires_at - timedelta(minutes=30)

    async def get_access_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        async with self._lock:
            if not self.is_token_valid:
                self._load_cached_token()  # 디스크에 살아있는 토큰 있으면 재사용
            if not self.is_token_valid:
                await self._issue_token()
            return self._token.access_token

    def _load_cached_token(self) -> None:
        """디스크 캐시에서 유효 토큰 로드 — 재발급(rate limit) 회피."""
        try:
            if not self._cache_path.exists():
                return
            d = json.loads(self._cache_path.read_text())
            if d.get("app_key") != self.app_key:  # 키 바뀌면 무효
                return
            expires_at = datetime.fromisoformat(d["expires_at"])
            if datetime.now() < expires_at - timedelta(minutes=30):
                self._token = TokenInfo(
                    access_token=d["access_token"],
                    token_type=d.get("token_type", "Bearer"),
                    expires_at=expires_at,
                    expires_in=int(d.get("expires_in", 86400)),
                )
                logger.info(f"KIS 토큰 디스크 캐시 재사용 ({'모의' if self.is_mock else '실전'}), "
                            f"만료 {expires_at:%m-%d %H:%M}")
        except Exception:  # noqa: BLE001
            pass

    def _save_token(self) -> None:
        """발급 토큰을 디스크에 저장(chmod 600) — 다음 프로세스가 재사용."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps({
                "app_key": self.app_key,
                "access_token": self._token.access_token,
                "token_type": self._token.token_type,
                "expires_at": self._token.expires_at.isoformat(),
                "expires_in": self._token.expires_in,
            }))
            self._cache_path.chmod(0o600)
        except Exception:  # noqa: BLE001
            pass

    async def _issue_token(self) -> None:
        """Request new access token from KIS API (with retry for rate limit)."""
        url = f"{self.base_url}{TOKEN_PATH}"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }

        max_retries = 3
        for attempt in range(max_retries):
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=body)
                data = resp.json()

            # Rate limit (EGW00133) or 403 → retry after wait
            error_code = data.get("error_code", "")
            if error_code == "EGW00133" or (resp.status_code == 403 and "access_token" not in data):
                wait_sec = 65 * (attempt + 1)
                logger.warning(
                    f"토큰 발급 Rate Limit ({error_code}), "
                    f"{wait_sec}초 대기 후 재시도 ({attempt+1}/{max_retries})"
                )
                await asyncio.sleep(wait_sec)
                continue

            if resp.status_code != 200 or "access_token" not in data:
                msg = data.get("error_description", data.get("msg1", str(data)))
                raise RuntimeError(f"KIS 토큰 발급 실패: {msg}")

            break
        else:
            raise RuntimeError("KIS 토큰 발급 실패: Rate Limit 초과 (최대 재시도 횟수 도달)")

        expires_in = int(data.get("expires_in", 86400))
        self._token = TokenInfo(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_at=datetime.now() + timedelta(seconds=expires_in),
            expires_in=expires_in,
        )
        self._save_token()

        logger.info(
            f"KIS 토큰 발급 완료 ({'모의' if self.is_mock else '실전'}), "
            f"만료: {self._token.expires_at:%H:%M:%S}"
        )

    async def revoke_token(self) -> None:
        """Revoke current access token."""
        if self._token is None:
            return

        url = f"{self.base_url}{TOKEN_REVOKE_PATH}"
        body = {
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "token": self._token.access_token,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=body)
            logger.info("KIS 토큰 폐기 완료")
        except Exception as e:
            logger.warning(f"KIS 토큰 폐기 실패: {e}")
        finally:
            self._token = None

    def get_auth_headers(self) -> dict[str, str]:
        """Build common auth headers for REST API calls."""
        if self._token is None:
            raise RuntimeError("토큰이 발급되지 않았습니다. get_access_token()을 먼저 호출하세요.")

        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._token.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
