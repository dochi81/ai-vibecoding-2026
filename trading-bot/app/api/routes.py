"""HTTP endpoints exposed by the trader service."""

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database.db import database_is_available
from app.database.db import get_db
from app.database.repository import (
    get_or_create_paper_account,
    get_paper_trading_settings,
    get_daily_paper_performance,
    get_paper_positions,
    reset_paper_trading,
    resolve_stock_queries,
    search_stock_names,
    save_price_snapshots,
    save_stock_names,
    save_strategy_signal,
    sync_stock_catalog,
    update_paper_trading_limit,
)
from app.stock_catalog import KrxCatalogClient, StockCatalogError
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
    stock_code: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=100_000)


class AutoBuyRequest(BaseModel):
    """Paper-only automatic-buy watcher configuration."""

    stock_code: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=100_000)
    trade_mode: Literal["BUY", "SELL", "BOTH"] = "BOTH"


class PaperResetRequest(BaseModel):
    """Explicit confirmation required before deleting local paper history."""

    confirm: Literal[True]


class PaperTradingLimitRequest(BaseModel):
    """Manual local per-order amount cap for paper trading."""

    max_order_amount: Decimal = Field(gt=0)


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
        TossAuthClient().get_access_token(force_refresh=True)
    except TossAuthError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return {"authenticated": True, "token_exposed": False}


@router.get("/market/prices", tags=["market"])
def get_current_prices(
    symbols: str = Query(
        ...,
        description="Comma-separated stock codes or cached company names, for example 삼성전자 or 005930.",
    ),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, str]]]:
    """Fetch Toss current prices and store them as immutable price history."""
    try:
        prices = TossMarketClient().get_prices(resolve_stock_queries(db, symbols.split(",")))
        save_price_snapshots(db, prices)
    except (TossAuthError, TossMarketError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return {"prices": [price.as_dict() for price in prices]}


@router.get("/market/chart", tags=["market"])
def get_price_chart(
    symbol: str = Query(..., description="A single stock symbol, for example 005930."),
    count: int = Query(30, ge=5, le=200, description="Number of daily closes to display."),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Return daily close history plus a freshly fetched current quote.

    The current quote is intended for a browser poll, while historical points
    remain daily candles.  This endpoint contains no order capability.
    """
    try:
        market = TossMarketClient()
        stock_code = resolve_stock_queries(db, [symbol])[0]
        current_price = market.get_prices([stock_code])[0]
        candles = market.get_daily_candles(current_price.symbol, count=count)
        save_price_snapshots(db, [current_price])
        points = [
            {
                "timestamp": candle.observed_at.isoformat(),
                "close_price": str(candle.close_price),
            }
            for candle in reversed(candles)
        ]
        return {
            "symbol": current_price.symbol,
            "name": current_price.name,
            "currency": current_price.currency,
            "current_price": str(current_price.last_price),
            "observed_at": current_price.observed_at.isoformat(),
            "interval": "1d",
            "refresh_seconds": 15,
            "points": points,
        }
    except (TossAuthError, TossMarketError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/market/search", tags=["market"])
def search_company_names(
    query: str = Query(..., min_length=3, max_length=100),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, str]]]:
    """Return cached company-name matches for browser autocomplete."""
    return {"items": search_stock_names(db, query)}


@router.post("/market/catalog/sync", tags=["market"])
def sync_korean_stock_catalog(db: Session = Depends(get_db)) -> dict[str, int | str]:
    """Refresh local company-name search from KRX's public listed-company catalog."""
    try:
        result = sync_stock_catalog(db, KrxCatalogClient().fetch_listed_stocks())
        return {"source": "KRX public listed-company catalog", **result}
    except StockCatalogError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/market/top5", tags=["market"])
def get_market_top5(db: Session = Depends(get_db)) -> dict[str, object]:
    """Return public one-day top-gainer rankings; never a buy recommendation."""
    try:
        rankings = TossMarketClient().get_top_gainers(limit=5)
        save_stock_names(db, [(ranking.symbol, ranking.name) for ranking in rankings])
        return {
            "category": "오늘 상승 TOP5 (참고용)",
            "disclaimer": "공개 시장 랭킹이며 매수 추천 또는 투자 조언이 아닙니다.",
            "items": [ranking.as_dict() for ranking in rankings],
        }
    except (TossAuthError, TossMarketError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/market/candidates", tags=["market"])
def get_budget_candidates(db: Session = Depends(get_db)) -> dict[str, object]:
    """Rank informational paper-trading candidates; never create an order."""
    try:
        ranking_items = TossMarketClient().get_top_gainers(limit=5)
        paper_settings = get_paper_trading_settings(db)
        max_buy_amount = Decimal(paper_settings["max_buy_amount"])
        candidates: list[dict[str, object]] = []
        for ranking in ranking_items:
            decision = MovingAverageStrategy().analyze(ranking.symbol)
            save_strategy_signal(db, decision)
            quantity = int(max_buy_amount / decision.current_price)
            is_budget_fit = quantity >= 1
            candidates.append(
                {
                    "rank": ranking.rank,
                    "stock_code": ranking.symbol,
                    "name": ranking.name,
                    "current_price": str(decision.current_price),
                    "currency": ranking.currency,
                    "change_rate": str(ranking.change_rate),
                    "signal": decision.signal,
                    "moving_average": str(decision.moving_average),
                    "max_quantity": quantity,
                    "is_candidate": decision.signal == "BUY" and is_budget_fit,
                    "note": (
                        "이동평균 BUY 신호와 1회 거래 한도에 맞는 참고 후보입니다."
                        if decision.signal == "BUY" and is_budget_fit
                        else "신호 또는 예산 조건을 충족하지 않아 관망합니다."
                    ),
                }
            )
        candidates.sort(key=lambda item: (not bool(item["is_candidate"]), int(item["rank"])))
        return {
            "budget": paper_settings,
            "disclaimer": "토스증권 공개 상승 랭킹과 이동평균 규칙을 조합한 참고용 정보이며 투자 추천이 아닙니다.",
            "items": candidates,
        }
    except (TossAuthError, TossMarketError, ValueError) as error:
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
    status["paper_settings"] = get_paper_trading_settings(db)
    return status


@router.post("/trader/start", tags=["trader"])
def start_trader(db: Session = Depends(get_db)) -> dict[str, object]:
    """Enable paper-mode monitoring; no brokerage order can be submitted."""
    try:
        status = trader_runtime.start()
        status["paper_account"] = get_or_create_paper_account(db)
        status["paper_settings"] = get_paper_trading_settings(db)
        return status
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/trader/stop", tags=["trader"])
def stop_trader(db: Session = Depends(get_db)) -> dict[str, object]:
    """Disable paper-mode monitoring."""
    status = trader_runtime.stop()
    status["paper_account"] = get_or_create_paper_account(db)
    status["paper_settings"] = get_paper_trading_settings(db)
    return status


@router.get("/paper-positions", tags=["paper trading"])
def list_paper_positions(db: Session = Depends(get_db)) -> dict[str, object]:
    """Return positions owned only by the local paper account."""
    return {"positions": get_paper_positions(db)}


@router.get("/paper-settings", tags=["paper trading"])
def get_paper_settings(db: Session = Depends(get_db)) -> dict[str, str]:
    """Return the current manual per-order PAPER limit."""
    return get_paper_trading_settings(db)


@router.put("/paper-settings", tags=["paper trading"])
def set_paper_settings(
    request: PaperTradingLimitRequest, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Set the manual per-order PAPER amount cap with all-in prevention."""
    try:
        return update_paper_trading_limit(db, request.max_order_amount)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/paper-performance/daily", tags=["paper trading"])
def get_daily_paper_performance_summary(
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    """Return today's local PAPER trade performance in Korea time."""
    return get_daily_paper_performance(db)


@router.post("/paper/reset", tags=["paper trading"])
def reset_local_paper_trading(
    request: PaperResetRequest, db: Session = Depends(get_db)
) -> dict[str, object]:
    """Delete only local PAPER records after an explicit UI confirmation."""
    auto_buy_manager.stop()
    trader_runtime.stop()
    result = reset_paper_trading(db)
    result["message"] = "모의 잔고와 모의 거래 기록을 초기화했습니다."
    return result


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
        stock_code = resolve_stock_queries(db, [request.stock_code])[0]
        market_price = TossMarketClient().get_prices([stock_code])[0]
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
            "paper_settings": get_paper_trading_settings(db),
            "positions": get_paper_positions(db),
        }
    except (TossAuthError, TossMarketError, PaperTradingError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/auto-buy/status", tags=["paper trading"])
def get_auto_buy_status() -> dict[str, object]:
    """Return the local paper-only automatic-buy watcher state."""
    return auto_buy_manager.status()


@router.post("/auto-buy/start", tags=["paper trading"])
def start_auto_buy(
    request: AutoBuyRequest, db: Session = Depends(get_db)
) -> dict[str, object]:
    """Start a one-shot paper BUY watcher after the paper-order gate is opened."""
    if not trader_runtime.status()["running"]:
        raise HTTPException(
            status_code=409,
            detail="먼저 대시보드에서 '모의 주문 허용'을 눌러 주세요.",
        )
    try:
        stock_code = resolve_stock_queries(db, [request.stock_code])[0]
        return auto_buy_manager.start(
            stock_code, request.quantity, request.trade_mode
        )
    except (AutoBuyError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/auto-buy/stop", tags=["paper trading"])
def stop_auto_buy() -> dict[str, object]:
    """Stop a future automatic paper buy; real orders are never possible."""
    return auto_buy_manager.stop()
