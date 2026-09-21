"""Small persistence operations used by the trading engine and API routes."""

from sqlalchemy.orm import Session

from app.database.models import Price, Stock
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
