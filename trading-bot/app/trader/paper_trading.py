"""Transactional local paper orders. This module never calls a broker order API."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Order,
    PaperAccount,
    PaperPosition,
    PaperTradingSettings,
    Stock,
    TradeRecord,
)
from app.database.repository import get_or_create_paper_account


class PaperTradingError(RuntimeError):
    """Raised when a local paper order does not meet safety rules."""


def execute_paper_order(
    db: Session,
    *,
    side: str,
    stock_code: str,
    quantity: int,
    execution_price: Decimal,
) -> dict[str, str | int | None]:
    """Fill a BUY or SELL against local paper cash and holdings atomically."""
    normalized_side = side.upper()
    normalized_code = stock_code.strip().upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise PaperTradingError("모의 주문 방향은 BUY 또는 SELL만 가능합니다.")
    if quantity <= 0:
        raise PaperTradingError("모의 주문 수량은 1주 이상이어야 합니다.")
    if execution_price <= 0:
        raise PaperTradingError("모의 체결 가격은 0보다 커야 합니다.")

    # Creates the initial local cash account only when it does not exist yet.
    get_or_create_paper_account(db)
    account = db.execute(
        select(PaperAccount).where(PaperAccount.id == "default").with_for_update()
    ).scalar_one()
    trading_settings = db.execute(
        select(PaperTradingSettings)
        .where(PaperTradingSettings.id == "default")
        .with_for_update()
    ).scalar_one()
    position = db.execute(
        select(PaperPosition)
        .where(PaperPosition.stock_code == normalized_code)
        .with_for_update()
    ).scalar_one_or_none()
    amount = execution_price * quantity
    realized_return_rate: Decimal | None = None

    try:
        if db.get(Stock, normalized_code) is None:
            db.add(Stock(stock_code=normalized_code))
            db.flush()

        if amount > trading_settings.max_order_amount:
            raise PaperTradingError("1회 거래금액이 설정한 최대 거래 한도를 초과했습니다.")

        if normalized_side == "BUY":
            safe_buy_ceiling = account.cash_balance * (
                Decimal("1") - trading_settings.reserve_cash_rate
            )
            if amount > safe_buy_ceiling:
                raise PaperTradingError(
                    "올인 방지 규칙으로 남은 가상 현금의 90%까지만 매수할 수 있습니다."
                )
            if account.cash_balance < amount:
                raise PaperTradingError("모의 가용 현금이 부족합니다.")
            if position is None:
                position = PaperPosition(
                    stock_code=normalized_code,
                    quantity=quantity,
                    average_cost=execution_price,
                    last_price=execution_price,
                )
                db.add(position)
            else:
                total_cost = position.average_cost * position.quantity + amount
                position.quantity += quantity
                position.average_cost = total_cost / position.quantity
                position.last_price = execution_price
            account.cash_balance -= amount

        else:
            if position is None or position.quantity < quantity:
                raise PaperTradingError("매도할 모의 보유 수량이 부족합니다.")
            realized_return_rate = (
                (execution_price - position.average_cost) / position.average_cost * Decimal("100")
            )
            position.quantity -= quantity
            account.cash_balance += amount
            if position.quantity == 0:
                db.delete(position)
            else:
                position.last_price = execution_price

        order = Order(
            stock_code=normalized_code,
            side=normalized_side,
            quantity=quantity,
            requested_price=execution_price,
            trading_mode="PAPER",
            status="FILLED",
        )
        db.add(order)
        db.flush()
        db.add(
            TradeRecord(
                order_id=order.id,
                stock_code=normalized_code,
                side=normalized_side,
                quantity=quantity,
                executed_price=execution_price,
                realized_return_rate=realized_return_rate,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "order_id": order.id,
        "stock_code": normalized_code,
        "side": normalized_side,
        "quantity": quantity,
        "execution_price": str(execution_price),
        "realized_return_rate": (
            str(realized_return_rate.quantize(Decimal("0.0001")))
            if realized_return_rate is not None
            else None
        ),
    }
