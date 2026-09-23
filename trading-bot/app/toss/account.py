"""Account and holding queries for the Toss Securities Open API."""

from collections.abc import Mapping
from time import sleep

import httpx

from app.config import settings
from app.toss.auth import TossAuthClient, TossAuthError


class TossAccountError(RuntimeError):
    """Raised when account or holdings data cannot be retrieved."""


class TossAccountClient:
    """Read-only client for the account and holdings endpoints."""

    def __init__(self, auth_client: TossAuthClient | None = None) -> None:
        self.auth_client = auth_client or TossAuthClient()

    def get_accounts(self) -> list[dict[str, str]]:
        """Return accounts with masked account numbers for dashboard use."""
        payload = self._get("/api/v1/accounts")
        try:
            accounts = payload["result"]
            return [
                {
                    "account_seq": str(account["accountSeq"]),
                    "account_number": self._mask_account_number(str(account["accountNo"])),
                    "account_type": str(account["accountType"]),
                }
                for account in accounts
            ]
        except (KeyError, TypeError) as error:
            raise TossAccountError("Toss account response had an unexpected format.") from error

    def get_holdings(self, account_seq: str) -> dict[str, object]:
        """Return the holdings summary and items for one authorized account."""
        if not account_seq.strip().isdigit():
            raise TossAccountError("The account sequence must be numeric.")

        payload = self._get(
            "/api/v1/holdings",
            account_seq=account_seq.strip(),
        )
        try:
            result = payload["result"]
            if not isinstance(result, Mapping):
                raise TypeError
            return {
                "summary": {key: value for key, value in result.items() if key != "items"},
                "items": result.get("items", []),
            }
        except (KeyError, TypeError) as error:
            raise TossAccountError("Toss holdings response had an unexpected format.") from error

    def _get(self, path: str, *, account_seq: str | None = None) -> dict[str, object]:
        response = self._request(path, account_seq=account_seq)
        if response.status_code == 401:
            response = self._request(path, account_seq=account_seq, force_refresh=True)

        if response.status_code != 200:
            raise TossAccountError(f"Toss account request failed (HTTP {response.status_code}).")

        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError
            return payload
        except (TypeError, ValueError) as error:
            raise TossAccountError("Toss account response was not valid JSON.") from error

    def _request(
        self,
        path: str,
        *,
        account_seq: str | None = None,
        force_refresh: bool = False,
    ) -> httpx.Response:
        token = self.auth_client.get_access_token(force_refresh=force_refresh)
        headers = {"Authorization": f"Bearer {token}"}
        if account_seq:
            headers["X-Tossinvest-Account"] = account_seq

        for attempt in range(2):
            try:
                return httpx.get(
                    f"{settings.toss_api_base_url}{path}", headers=headers, timeout=10.0
                )
            except httpx.RequestError as error:
                if attempt == 0:
                    # Account API limits are low; wait before one safe retry.
                    sleep(1.1)
                    continue
                raise TossAccountError(
                    "토스증권 계좌 API에 연결하지 못했습니다. 잠시 후 다시 시도해주세요."
                ) from error

        raise AssertionError("Unreachable retry state")

    @staticmethod
    def _mask_account_number(account_number: str) -> str:
        """Avoid returning a full account number to the browser."""
        if len(account_number) <= 4:
            return "*" * len(account_number)
        return "*" * (len(account_number) - 4) + account_number[-4:]
