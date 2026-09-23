"""Small persistence operations used by the trading engine and API routes."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import (
    PaperAccount,
    PaperPosition,
    PaperTradingSettings,
    Order,
    Price,
    Stock,
    StrategySignal,
    TradeRecord,
)
from app.strategy.moving_average import StrategyDecision
from app.toss.market import MarketPrice
from app.stock_catalog import CatalogStock


def save_price_snapshots(db: Session, prices: list[MarketPrice]) -> None:
    """Persist one history record per price returned by the market API."""
    for market_price in prices:
        stock = db.get(Stock, market_price.symbol)
        if stock is None:
            db.add(Stock(stock_code=market_price.symbol, name=market_price.name))
        elif market_price.name:
            stock.name = market_price.name

    # Ensure newly added stock rows exist before inserting price rows with FKs.
    db.flush()

    for market_price in prices:
        db.add(
            Price(
                stock_code=market_price.symbol,
                current_price=market_price.last_price,
                observed_at=market_price.observed_at,
            )
        )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def save_stock_names(db: Session, stocks: list[tuple[str, str]]) -> None:
    """Cache display names received from public Toss market endpoints."""
    for stock_code, name in stocks:
        normalized_code = stock_code.strip().upper()
        stock = db.get(Stock, normalized_code)
        if stock is None:
            db.add(Stock(stock_code=normalized_code, name=name))
        elif name:
            stock.name = name
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def sync_stock_catalog(
    db: Session, catalog: list[CatalogStock]
) -> dict[str, int]:
    """Upsert a full KRX company catalog without deleting user trade records."""
    deduplicated = {stock.stock_code: stock for stock in catalog}
    existing = {
        stock.stock_code: stock
        for stock in db.scalars(
            select(Stock).where(Stock.stock_code.in_(deduplicated))
        ).all()
    }
    inserted = 0
    updated = 0
    for stock_code, catalog_stock in deduplicated.items():
        stock = existing.get(stock_code)
        if stock is None:
            db.add(
                Stock(
                    stock_code=stock_code,
                    name=catalog_stock.name,
                    market=catalog_stock.market,
                )
            )
            inserted += 1
        else:
            stock.name = catalog_stock.name
            stock.market = catalog_stock.market
            updated += 1
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"total": len(deduplicated), "inserted": inserted, "updated": updated}


def resolve_stock_queries(db: Session, queries: list[str]) -> list[str]:
    """Resolve local company-name matches to stock codes for quote lookup."""
    resolved: list[str] = []
    for query in queries:
        normalized = query.strip()
        if not normalized:
            continue
        direct_code = normalized.upper()
        is_symbol_format = direct_code.isascii() and all(
            character.isalnum() or character in ".-" for character in direct_code
        )
        if db.get(Stock, direct_code) is not None or is_symbol_format:
            resolved.append(direct_code)
            continue

        exact_matches = db.scalars(
            select(Stock)
            .where(func.lower(Stock.name) == normalized.lower())
            .order_by(Stock.stock_code)
        ).all()
        prefix_matches = exact_matches or db.scalars(
            select(Stock)
            .where(Stock.name.ilike(f"{normalized}%"))
            .order_by(Stock.stock_code)
            .limit(2)
        ).all()
        partial_matches = prefix_matches
        if not partial_matches and len(normalized) >= 3:
            partial_matches = db.scalars(
                select(Stock)
                .where(Stock.name.ilike(f"%{normalized}%"))
                .order_by(Stock.stock_code)
                .limit(2)
            ).all()
        if not partial_matches:
            minimum_hint = "회사명은 3글자 이상 입력하세요. " if len(normalized) < 3 else ""
            raise ValueError(
                f"{minimum_hint}'{normalized}' 회사명을 찾지 못했습니다. 시세 조회 또는 TOP5에 표시된 회사명을 입력하세요."
            )
        resolved.append(partial_matches[0].stock_code)

    if not resolved:
        raise ValueError("회사명 또는 종목코드를 입력하세요.")
    return resolved


def search_stock_names(db: Session, query: str, limit: int = 8) -> list[dict[str, str]]:
    """Return cached company-name suggestions for a three-character query."""
    normalized = query.strip()
    if len(normalized) < 3:
        return []
    matches = db.scalars(
        select(Stock)
        .where(Stock.name.ilike(f"%{normalized}%"))
        .limit(max(limit * 3, limit))
    ).all()
    matches.sort(
        key=lambda stock: (
            stock.name != normalized,
            not stock.name.startswith(normalized),
            stock.name,
            stock.stock_code,
        )
    )
    return [
        {"stock_code": stock.stock_code, "name": stock.name or stock.stock_code}
        for stock in matches[:limit]
    ]


def get_or_create_paper_account(db: Session) -> dict[str, str]:
    """Create the local paper account once, preserving its balance afterwards."""
    account = db.get(PaperAccount, "default")
    needs_commit = False
    if account is None:
        account = PaperAccount(
            id="default",
            initial_cash=settings.paper_initial_cash,
            cash_balance=settings.paper_initial_cash,
        )
        db.add(account)
        needs_commit = True
    if db.get(PaperTradingSettings, "default") is None:
        db.add(
            PaperTradingSettings(
                id="default",
                max_order_amount=settings.paper_initial_cash * Decimal("0.10"),
                reserve_cash_rate=Decimal("0.10"),
            )
        )
        needs_commit = True
    if needs_commit:
        db.commit()
        db.refresh(account)

    position_value = db.scalar(
        select(func.coalesce(func.sum(PaperPosition.last_price * PaperPosition.quantity), 0))
    )
    total_available_assets = account.cash_balance + Decimal(str(position_value))
    return {
        "initial_cash": str(account.initial_cash),
        "cash_balance": str(account.cash_balance),
        "total_available_assets": str(total_available_assets),
        "currency": "KRW",
    }


def get_paper_trading_settings(db: Session) -> dict[str, str]:
    """Return the per-order limit and the cash reserve safety rule."""
    account_data = get_or_create_paper_account(db)
    setting = db.get(PaperTradingSettings, "default")
    if setting is None:  # Defensive: account setup above always creates it.
        raise RuntimeError("Paper trading settings could not be initialized.")
    cash_balance = Decimal(account_data["cash_balance"])
    reserve_cash = cash_balance * Decimal(str(setting.reserve_cash_rate))
    max_buy_amount = min(
        Decimal(str(setting.max_order_amount)),
        max(cash_balance - reserve_cash, Decimal("0")),
    )
    return {
        "max_order_amount": str(setting.max_order_amount),
        "reserve_cash_rate": str(setting.reserve_cash_rate),
        "max_buy_amount": str(max_buy_amount),
        "cash_balance": str(cash_balance),
        "currency": "KRW",
    }


def update_paper_trading_limit(
    db: Session, max_order_amount: Decimal
) -> dict[str, str]:
    """Set a local per-order cap while preventing a paper-account all-in."""
    if max_order_amount <= 0:
        raise ValueError("1회 거래 한도는 0원보다 커야 합니다.")
    get_or_create_paper_account(db)
    account = db.get(PaperAccount, "default")
    setting = db.get(PaperTradingSettings, "default")
    if account is None or setting is None:
        raise RuntimeError("Paper trading settings could not be initialized.")
    safe_ceiling = account.cash_balance * (
        Decimal("1") - Decimal(str(setting.reserve_cash_rate))
    )
    if max_order_amount > safe_ceiling:
        raise ValueError(
            "1회 거래 한도는 남은 가상 현금의 90%를 초과할 수 없습니다."
        )
    setting.max_order_amount = max_order_amount
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_paper_trading_settings(db)


def save_strategy_signal(db: Session, decision: StrategyDecision) -> None:
    """Persist the decision and its plain-language reason for later auditing."""
    if db.get(Stock, decision.stock_code) is None:
        db.add(Stock(stock_code=decision.stock_code))
        db.flush()
    db.add(
        StrategySignal(
            stock_code=decision.stock_code,
            strategy_name="MA_5",
            current_price=decision.current_price,
            moving_average=decision.moving_average,
            signal=decision.signal,
            reason=decision.reason,
        )
    )
    db.commit()


def get_paper_positions(db: Session) -> list[dict[str, str | int]]:
    """Return the local paper positions using their latest paper execution price."""
    positions = db.scalars(select(PaperPosition).order_by(PaperPosition.stock_code)).all()
    return [
        {
            "stock_code": position.stock_code,
            "quantity": position.quantity,
            "average_cost": str(position.average_cost),
            "last_price": str(position.last_price),
            "market_value": str(position.last_price * position.quantity),
        }
        for position in positions
    ]


def get_daily_paper_performance(db: Session) -> dict[str, str | int]:
    """Summarize today's local PAPER executions in the Korea time zone.

    Only filled local paper trades are included.  Realized P/L is calculated
    from each recorded sell price and the realized rate stored at execution.
    """
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    trades = db.scalars(
        select(TradeRecord)
        .where(TradeRecord.executed_at >= day_start)
        .order_by(TradeRecord.executed_at)
    ).all()

    buy_amount = Decimal("0")
    sell_amount = Decimal("0")
    realized_profit_loss = Decimal("0")
    buy_count = 0
    sell_count = 0

    for trade in trades:
        amount = Decimal(str(trade.executed_price)) * trade.quantity
        if trade.side == "BUY":
            buy_count += 1
            buy_amount += amount
            continue

        if trade.side == "SELL":
            sell_count += 1
            sell_amount += amount
            if trade.realized_return_rate is not None:
                rate = Decimal(str(trade.realized_return_rate)) / Decimal("100")
                realized_profit_loss += amount - (amount / (Decimal("1") + rate))

    return {
        "date": now.date().isoformat(),
        "trade_count": len(trades),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "buy_amount": str(buy_amount),
        "sell_amount": str(sell_amount),
        "realized_profit_loss": str(realized_profit_loss.quantize(Decimal("0.01"))),
        "currency": "KRW",
    }


def reset_paper_trading(db: Session) -> dict[str, int | dict[str, str]]:
    """Reset only local PAPER cash, positions, orders, and completed trades."""
    paper_order_ids = select(Order.id).where(Order.trading_mode == "PAPER")
    try:
        deleted_trades = db.execute(
            delete(TradeRecord).where(TradeRecord.order_id.in_(paper_order_ids))
        ).rowcount
        deleted_orders = db.execute(
            delete(Order).where(Order.trading_mode == "PAPER")
        ).rowcount
        deleted_positions = db.execute(delete(PaperPosition)).rowcount

        account = db.get(PaperAccount, "default")
        if account is None:
            account = PaperAccount(
                id="default",
                initial_cash=settings.paper_initial_cash,
                cash_balance=settings.paper_initial_cash,
            )
            db.add(account)
        else:
            account.initial_cash = settings.paper_initial_cash
            account.cash_balance = settings.paper_initial_cash
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "deleted_trades": deleted_trades or 0,
        "deleted_orders": deleted_orders or 0,
        "deleted_positions": deleted_positions or 0,
        "paper_account": get_or_create_paper_account(db),
    }
