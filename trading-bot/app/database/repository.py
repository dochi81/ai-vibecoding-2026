"""Small persistence operations used by the trading engine and API routes."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import (
    PaperAccount,
    PaperPosition,
    Price,
    Stock,
    StrategySignal,
    TradeRecord,
)
from app.strategy.moving_average import StrategyDecision
from app.toss.market import MarketPrice


def save_price_snapshots(db: Session, prices: list[MarketPrice]) -> None:
    """Persist one history record per price returned by the market API."""
    for market_price in prices:
        if db.get(Stock, market_price.symbol) is None:
            db.add(Stock(stock_code=market_price.symbol))

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


def get_or_create_paper_account(db: Session) -> dict[str, str]:
    """Create the local paper account once, preserving its balance afterwards."""
    account = db.get(PaperAccount, "default")
    if account is None:
        account = PaperAccount(
            id="default",
            initial_cash=settings.paper_initial_cash,
            cash_balance=settings.paper_initial_cash,
        )
        db.add(account)
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
