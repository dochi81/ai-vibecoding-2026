"""Persistent records for the v0.1 paper-trading workflow."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class Stock(Base):
    """A tradeable stock instrument."""

    __tablename__ = "stocks"

    stock_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    market: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Price(Base):
    """One observed price snapshot for a stock."""

    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stocks.stock_code"), index=True, nullable=False
    )
    current_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


class Order(Base):
    """A requested paper or future live order."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stocks.stock_code"), index=True, nullable=False
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY or SELL
    quantity: Mapped[int] = mapped_column(nullable=False)
    requested_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    trading_mode: Mapped[str] = mapped_column(String(10), default="PAPER", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TradeRecord(Base):
    """A completed execution record linked to its source order."""

    __tablename__ = "trade_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=False)
    stock_code: Mapped[str] = mapped_column(
        ForeignKey("stocks.stock_code"), index=True, nullable=False
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    executed_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    realized_return_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

