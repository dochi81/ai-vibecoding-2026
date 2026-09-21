"""OAuth 2.0 client-credentials authentication for Toss Securities Open API."""

from dataclasses import dataclass
from threading import Lock
from time import monotonic

import httpx

from app.config import settings


class TossAuthError(RuntimeError):
    """Raised when an access token cannot be issued or validated."""


@dataclass(frozen=True)
class AccessToken:
    """A token held only in process memory until just before expiry."""

    value: str
    expires_at: float


class TossAuthClient:
    """Get and cache the one active Toss access token for this process."""

    _cached_token: AccessToken | None = None
    _lock = Lock()

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        """Issue an OAuth token only when a cached valid token is unavailable."""
        with self._lock:
            cached = type(self)._cached_token
            if not force_refresh and cached and cached.expires_at > monotonic():
                return cached.value

            return self._request_token()

    def _request_token(self) -> str:
        if not settings.toss_client_id or not settings.toss_client_secret:
            raise TossAuthError("Toss client credentials are missing from .env.")

        try:
            response = httpx.post(
                f"{settings.toss_api_base_url}/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.toss_client_id,
                    "client_secret": settings.toss_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
        except httpx.RequestError as error:
            raise TossAuthError("Could not reach Toss Securities Open API.") from error

        if response.status_code != 200:
            # Do not include response content: it can contain sensitive context.
            if response.status_code == 403:
                raise TossAuthError(
                    "Toss rejected the request (HTTP 403). Check that this machine's "
                    "public IP is registered in WTS Open API Allowed IP settings."
                )
            raise TossAuthError(
                f"Toss token request was rejected (HTTP {response.status_code})."
            )

        try:
            payload = response.json()
            token = payload["access_token"]
            expires_in = int(payload.get("expires_in", 3600))
        except (TypeError, ValueError, KeyError) as error:
            raise TossAuthError("Toss token response had an unexpected format.") from error

        if not token or expires_in <= 0:
            raise TossAuthError("Toss token response did not contain a usable token.")

        # Renew 60 seconds early so downstream requests do not race expiry.
        expires_at = monotonic() + max(expires_in - 60, 1)
        type(self)._cached_token = AccessToken(value=token, expires_at=expires_at)
        return token
