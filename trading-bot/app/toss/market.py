"""Market-data client for the Toss Securities Open API."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

import httpx

from app.config import settings
from app.toss.auth import TossAuthClient, TossAuthError


SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")


class TossMarketError(RuntimeError):
    """Raised when current market prices cannot be retrieved safely."""


@dataclass(frozen=True)
class MarketPrice:
    """Normalized current-price data returned by Toss Securities."""

    symbol: str
    last_price: Decimal
    currency: str
    observed_at: datetime

    def as_dict(self) -> dict[str, str]:
        """Return JSON-ready price data without broker credentials."""
        return {
            "symbol": self.symbol,
            "last_price": str(self.last_price),
            "currency": self.currency,
            "observed_at": self.observed_at.isoformat(),
        }


class TossMarketClient:
    """Fetch current prices from Toss Securities with one token-refresh retry."""

    def __init__(self, auth_client: TossAuthClient | None = None) -> None:
        self.auth_client = auth_client or TossAuthClient()

    def get_prices(self, symbols: list[str]) -> list[MarketPrice]:
        """Fetch current prices for up to 200 validated symbols."""
        normalized_symbols = self._validate_symbols(symbols)
        response = self._request_prices(normalized_symbols)

        if response.status_code == 401:
            response = self._request_prices(normalized_symbols, force_refresh=True)

        if response.status_code != 200:
            raise TossMarketError(
                f"Toss current-price request failed (HTTP {response.status_code})."
            )

        try:
            results = response.json()["result"]
            return [self._parse_price(item) for item in results]
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise TossMarketError("Toss current-price response had an unexpected format.") from error

    def _request_prices(self, symbols: list[str], *, force_refresh: bool = False) -> httpx.Response:
        try:
            token = self.auth_client.get_access_token(force_refresh=force_refresh)
            return httpx.get(
                f"{settings.toss_api_base_url}/api/v1/prices",
                params={"symbols": ",".join(symbols)},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
        except TossAuthError:
            raise
        except httpx.RequestError as error:
            raise TossMarketError("Could not reach Toss current-price API.") from error

    @staticmethod
    def _validate_symbols(symbols: list[str]) -> list[str]:
        cleaned = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        if not cleaned or len(cleaned) > 200:
            raise TossMarketError("Provide between 1 and 200 stock symbols.")
        if any(not SYMBOL_PATTERN.fullmatch(symbol) for symbol in cleaned):
            raise TossMarketError("A stock symbol has an unsupported format.")
        return cleaned

    @staticmethod
    def _parse_price(item: dict[str, str]) -> MarketPrice:
        return MarketPrice(
            symbol=item["symbol"],
            last_price=Decimal(item["lastPrice"]),
            currency=item["currency"],
            observed_at=datetime.fromisoformat(item["timestamp"]),
        )
