"""HTTP endpoints exposed by the trader service."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database.db import database_is_available
from app.database.db import get_db
from app.database.repository import (
    get_or_create_paper_account,
    get_daily_paper_performance,
    get_paper_positions,
    save_price_snapshots,
    save_strategy_signal,
)
from app.strategy.moving_average import MovingAverageStrategy
from app.toss.auth import TossAuthClient, TossAuthError
from app.toss.account import TossAccountClient, TossAccountError
from app.toss.market import TossMarketClient, TossMarketError
from app.trader.auto_buy import AutoBuyError, auto_buy_manager
from app.trader.runtime import trader_runtime
from app.trader.paper_trading import PaperTradingError, execute_paper_order

router = APIRouter()


class PaperOrderRequest(BaseModel):
    """A strictly local paper order request from the dashboard."""

    side: Literal["BUY", "SELL"]
    stock_code: str = Field(min_length=1, max_length=12)
    quantity: int = Field(ge=1, le=100_000)


class AutoBuyRequest(BaseModel):
    """Paper-only automatic-buy watcher configuration."""

    stock_code: str = Field(min_length=1, max_length=12)
    quantity: int = Field(ge=1, le=100_000)


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str | bool]:
    """Return service and PostgreSQL readiness without external broker calls."""
    database_available = database_is_available()
    return {
        "status": "ok" if database_available else "degraded",
        "service": "toss-auto-trader",
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


@router.get("/market/top5", tags=["market"])
def get_market_top5() -> dict[str, object]:
    """Return public one-day top-gainer rankings; never a buy recommendation."""
    try:
        rankings = TossMarketClient().get_top_gainers(limit=5)
        return {
            "category": "오늘 상승 TOP5 (참고용)",
            "disclaimer": "공개 시장 랭킹이며 매수 추천 또는 투자 조언이 아닙니다.",
            "items": [ranking.as_dict() for ranking in rankings],
        }
    except (TossAuthError, TossMarketError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/accounts", tags=["account"])
def get_accounts() -> dict[str, list[dict[str, str]]]:
    """Return linked Toss accounts with masked account numbers."""
    try:
        return {"accounts": TossAccountClient().get_accounts()}
    except (TossAuthError, TossAccountError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/accounts/{account_seq}/holdings", tags=["account"])
def get_holdings(account_seq: str) -> dict[str, object]:
    """Return summary and holdings for the selected linked account."""
    try:
        return TossAccountClient().get_holdings(account_seq)
    except (TossAuthError, TossAccountError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/strategy/moving-average", tags=["strategy"])
def analyze_moving_average(
    symbol: str = Query(..., description="A stock symbol, for example 005930 or AAPL."),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Evaluate, record, and return the five-day moving-average signal."""
    try:
        decision = MovingAverageStrategy().analyze(symbol)
        save_strategy_signal(db, decision)
        return decision.as_dict()
    except (TossAuthError, TossMarketError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/trader/status", tags=["trader"])
def get_trader_status(db: Session = Depends(get_db)) -> dict[str, object]:
    """Return the v0.1 paper-trading engine state."""
    status = trader_runtime.status()
    status["paper_account"] = get_or_create_paper_account(db)
    return status


@router.post("/trader/start", tags=["trader"])
def start_trader(db: Session = Depends(get_db)) -> dict[str, object]:
    """Enable paper-mode monitoring; no brokerage order can be submitted."""
    try:
        status = trader_runtime.start()
        status["paper_account"] = get_or_create_paper_account(db)
        return status
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/trader/stop", tags=["trader"])
def stop_trader(db: Session = Depends(get_db)) -> dict[str, object]:
    """Disable paper-mode monitoring."""
    status = trader_runtime.stop()
    status["paper_account"] = get_or_create_paper_account(db)
    return status


@router.get("/paper-positions", tags=["paper trading"])
def list_paper_positions(db: Session = Depends(get_db)) -> dict[str, object]:
    """Return positions owned only by the local paper account."""
    return {"positions": get_paper_positions(db)}


@router.get("/paper-performance/daily", tags=["paper trading"])
def get_daily_paper_performance_summary(
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    """Return today's local PAPER trade performance in Korea time."""
    return get_daily_paper_performance(db)


@router.post("/paper-orders", tags=["paper trading"])
def create_paper_order(
    request: PaperOrderRequest, db: Session = Depends(get_db)
) -> dict[str, object]:
    """Fill a local paper order at the latest Toss quote; no broker order is sent."""
    if not trader_runtime.status()["running"]:
        raise HTTPException(
            status_code=409,
            detail="모의 주문이 잠겨 있습니다. 먼저 '모의 주문 허용'을 누르세요.",
        )
    try:
        market_price = TossMarketClient().get_prices([request.stock_code])[0]
        order = execute_paper_order(
            db,
            side=request.side,
            stock_code=market_price.symbol,
            quantity=request.quantity,
            execution_price=market_price.last_price,
        )
        return {
            "order": order,
            "paper_account": get_or_create_paper_account(db),
            "positions": get_paper_positions(db),
        }
    except (TossAuthError, TossMarketError, PaperTradingError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/auto-buy/status", tags=["paper trading"])
def get_auto_buy_status() -> dict[str, object]:
    """Return the local paper-only automatic-buy watcher state."""
    return auto_buy_manager.status()


@router.post("/auto-buy/start", tags=["paper trading"])
def start_auto_buy(request: AutoBuyRequest) -> dict[str, object]:
    """Start a one-shot paper BUY watcher after the paper-order gate is opened."""
    if not trader_runtime.status()["running"]:
        raise HTTPException(
            status_code=409,
            detail="먼저 대시보드에서 '모의 주문 허용'을 눌러 주세요.",
        )
    try:
        return auto_buy_manager.start(request.stock_code, request.quantity)
    except AutoBuyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/auto-buy/stop", tags=["paper trading"])
def stop_auto_buy() -> dict[str, object]:
    """Stop a future automatic paper buy; real orders are never possible."""
    return auto_buy_manager.stop()
