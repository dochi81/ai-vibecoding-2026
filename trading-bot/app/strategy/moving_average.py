"""A deliberately simple five-day moving-average paper strategy."""

from dataclasses import dataclass
from decimal import Decimal

from app.toss.market import TossMarketClient


@dataclass(frozen=True)
class StrategyDecision:
    """The explainable output of one moving-average evaluation."""

    stock_code: str
    current_price: Decimal
    moving_average: Decimal
    signal: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "stock_code": self.stock_code,
            "current_price": str(self.current_price),
            "moving_average": str(self.moving_average.quantize(Decimal("0.01"))),
            "signal": self.signal,
            "reason": self.reason,
        }


class MovingAverageStrategy:
    """Signal BUY above 5-day MA, SELL below it, otherwise HOLD."""

    name = "MA_5"

    def __init__(self, market_client: TossMarketClient | None = None) -> None:
        self.market_client = market_client or TossMarketClient()

    def analyze(self, stock_code: str) -> StrategyDecision:
        """Compare the latest current price with the last five daily closes."""
        price = self.market_client.get_prices([stock_code])[0]
        candles = self.market_client.get_daily_candles(stock_code, count=5)
        if len(candles) < 5:
            raise ValueError("Five daily candles are required for the MA_5 strategy.")

        moving_average = sum((candle.close_price for candle in candles), Decimal("0")) / Decimal(
            len(candles)
        )
        if price.last_price > moving_average:
            signal, reason = "BUY", "현재가가 5일 이동평균보다 높습니다."
        elif price.last_price < moving_average:
            signal, reason = "SELL", "현재가가 5일 이동평균보다 낮습니다."
        else:
            signal, reason = "HOLD", "현재가와 5일 이동평균이 같습니다."

        return StrategyDecision(
            stock_code=price.symbol,
            current_price=price.last_price,
            moving_average=moving_average,
            signal=signal,
            reason=reason,
        )
