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


@dataclass(frozen=True)
class DailyCandle:
    """A normalized daily OHLCV candle used by strategies."""

    close_price: Decimal
    observed_at: datetime


@dataclass(frozen=True)
class MarketRanking:
    """One public market-ranking item, not an investment recommendation."""

    rank: int
    symbol: str
    name: str
    price: Decimal
    change_rate: Decimal
    currency: str
    trading_amount: str
    ranked_at: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "name": self.name,
            "price": str(self.price),
            "change_rate": str(self.change_rate),
            "currency": self.currency,
            "trading_amount": self.trading_amount,
            "ranked_at": self.ranked_at,
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

    def get_daily_candles(self, symbol: str, count: int = 5) -> list[DailyCandle]:
        """Fetch recent daily candles, returned newest first by Toss."""
        normalized_symbol = self._validate_symbols([symbol])[0]
        if not 1 <= count <= 200:
            raise TossMarketError("Candle count must be between 1 and 200.")

        response = self._request_candles(normalized_symbol, count)
        if response.status_code == 401:
            response = self._request_candles(normalized_symbol, count, force_refresh=True)
        if response.status_code != 200:
            raise TossMarketError(f"Toss daily-candle request failed (HTTP {response.status_code}).")

        try:
            candles = response.json()["result"]["candles"]
            return [
                DailyCandle(
                    close_price=Decimal(candle["closePrice"]),
                    observed_at=datetime.fromisoformat(candle["timestamp"]),
                )
                for candle in candles
            ]
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise TossMarketError("Toss daily-candle response had an unexpected format.") from error

    def get_top_gainers(self, limit: int = 5) -> list[MarketRanking]:
        """Return public Korean one-day top-gainer rankings for display only."""
        if not 1 <= limit <= 20:
            raise TossMarketError("Ranking limit must be between 1 and 20.")

        response = self._request_rankings()
        if response.status_code == 401:
            response = self._request_rankings(force_refresh=True)
        if response.status_code != 200:
            raise TossMarketError(f"Toss ranking request failed (HTTP {response.status_code}).")

        try:
            result = response.json()["result"]
            rankings = result["rankings"][:limit]
            ranked_at = str(result["rankedAt"])
            symbols = [str(item["symbol"]) for item in rankings]
        except (KeyError, TypeError, ValueError) as error:
            raise TossMarketError("Toss ranking response had an unexpected format.") from error

        stock_response = self._request_stocks(symbols)
        if stock_response.status_code == 401:
            stock_response = self._request_stocks(symbols, force_refresh=True)
        if stock_response.status_code != 200:
            raise TossMarketError(f"Toss stock-info request failed (HTTP {stock_response.status_code}).")

        try:
            names = {
                str(stock["symbol"]): str(stock["name"])
                for stock in stock_response.json()["result"]
            }
            return [
                MarketRanking(
                    rank=int(item["rank"]),
                    symbol=str(item["symbol"]),
                    name=names.get(str(item["symbol"]), str(item["symbol"])),
                    price=Decimal(item["price"]["lastPrice"]),
                    change_rate=Decimal(item["price"]["changeRate"]),
                    currency=str(item["currency"]),
                    trading_amount=str(item["tradingAmount"]),
                    ranked_at=ranked_at,
                )
                for item in rankings
            ]
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise TossMarketError("Toss ranking item had an unexpected format.") from error

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

    def _request_candles(
        self, symbol: str, count: int, *, force_refresh: bool = False
    ) -> httpx.Response:
        try:
            token = self.auth_client.get_access_token(force_refresh=force_refresh)
            return httpx.get(
                f"{settings.toss_api_base_url}/api/v1/candles",
                params={"symbol": symbol, "interval": "1d", "count": count},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
        except TossAuthError:
            raise
        except httpx.RequestError as error:
            raise TossMarketError("Could not reach Toss daily-candle API.") from error

    def _request_rankings(self, *, force_refresh: bool = False) -> httpx.Response:
        try:
            token = self.auth_client.get_access_token(force_refresh=force_refresh)
            return httpx.get(
                f"{settings.toss_api_base_url}/api/v1/rankings",
                params={"type": "TOP_GAINERS", "marketCountry": "KR", "duration": "1d"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
        except TossAuthError:
            raise
        except httpx.RequestError as error:
            raise TossMarketError("Could not reach Toss ranking API.") from error

    def _request_stocks(
        self, symbols: list[str], *, force_refresh: bool = False
    ) -> httpx.Response:
        try:
            token = self.auth_client.get_access_token(force_refresh=force_refresh)
            return httpx.get(
                f"{settings.toss_api_base_url}/api/v1/stocks",
                params={"symbols": ",".join(symbols)},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
        except TossAuthError:
            raise
        except httpx.RequestError as error:
            raise TossMarketError("Could not reach Toss stock-info API.") from error

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
