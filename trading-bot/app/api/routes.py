"""HTTP endpoints exposed by the trader service."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database.db import database_is_available
from app.database.db import get_db
from app.database.repository import save_price_snapshots
from app.toss.auth import TossAuthClient, TossAuthError
from app.toss.market import TossMarketClient, TossMarketError

router = APIRouter()


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str | bool]:
    """Return service and PostgreSQL readiness without external broker calls."""
    database_available = database_is_available()
    return {
        "status": "ok" if database_available else "degraded",
        "service": "auto-trading-trader",
        "version": "0.1.0",
        "database": database_available,
        "live_trading": settings.live_trading,
    }


@router.post("/auth/verify", tags=["auth"])
def verify_toss_authentication() -> dict[str, bool | str]:
    """Request a Toss token and confirm configuration without exposing it."""
    try:
        TossAuthClient().get_access_token()
    except TossAuthError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return {"authenticated": True, "token_exposed": False}


@router.get("/market/prices", tags=["market"])
def get_current_prices(
    symbols: str = Query(
        ...,
        description="Comma-separated stock symbols, for example 005930 or AAPL,MSFT.",
    ),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, str]]]:
    """Fetch Toss current prices and store them as immutable price history."""
    try:
        prices = TossMarketClient().get_prices(symbols.split(","))
        save_price_snapshots(db, prices)
    except (TossAuthError, TossMarketError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return {"prices": [price.as_dict() for price in prices]}
