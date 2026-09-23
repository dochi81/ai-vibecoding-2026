"""One-shot, paper-only automatic trade watcher for v0.1."""

from threading import Event, RLock, Thread

from app.database.db import SessionLocal
from app.strategy.moving_average import MovingAverageStrategy
from app.trader.paper_trading import PaperTradingError, execute_paper_order


class AutoBuyError(RuntimeError):
    """Raised when an automatic-buy watcher cannot be started safely."""


class AutoBuyManager:
    """Watch one symbol and make at most one local paper order.

    This class never calls a Toss order endpoint.  It checks the moving-average
    signal every 60 seconds, performs one allowed local PAPER BUY or SELL
    order, then stops itself.
    """

    interval_seconds = 60

    def __init__(self) -> None:
        self._lock = RLock()
        self._stop_event = Event()
        self._running = False
        self._state = "IDLE"
        self._stock_code: str | None = None
        self._quantity: int | None = None
        self._trade_mode = "BOTH"
        self._last_signal: str | None = None
        self._last_order: str | None = None
        self._message = "자동매수 대기 중입니다."

    def start(
        self, stock_code: str, quantity: int, trade_mode: str = "BOTH"
    ) -> dict[str, object]:
        """Start a single paper-only watcher."""
        normalized_code = stock_code.strip().upper()
        normalized_mode = trade_mode.upper()
        if not normalized_code or quantity <= 0:
            raise AutoBuyError("종목 코드와 1주 이상의 수량을 입력하세요.")
        if normalized_mode not in {"BUY", "SELL", "BOTH"}:
            raise AutoBuyError("자동 거래 방식이 올바르지 않습니다.")

        with self._lock:
            if self._running:
                raise AutoBuyError("이미 자동매수 감시가 실행 중입니다. 먼저 정지하세요.")

            self._stop_event = Event()
            self._running = True
            self._state = "WATCHING"
            self._stock_code = normalized_code
            self._quantity = quantity
            self._trade_mode = normalized_mode
            self._last_signal = None
            self._last_order = None
            self._message = "매수 신호를 확인 중입니다. 60초마다 다시 조회합니다."
            Thread(target=self._run, args=(self._stop_event,), daemon=True).start()
            return self.status()

    def stop(self) -> dict[str, object]:
        """Stop watching before a future automatic paper order is created."""
        with self._lock:
            self._stop_event.set()
            self._running = False
            self._state = "STOPPED"
            self._message = "자동매수 감시를 정지했습니다."
            return self.status()

    def status(self) -> dict[str, object]:
        """Return safe UI state without credentials or account identifiers."""
        with self._lock:
            return {
                "running": self._running,
                "state": self._state,
                "stock_code": self._stock_code,
                "quantity": self._quantity,
                "trade_mode": self._trade_mode,
                "last_signal": self._last_signal,
                "last_order": self._last_order,
                "interval_seconds": self.interval_seconds,
                "message": self._message,
            }

    def _run(self, stop_event: Event) -> None:
        while not stop_event.is_set():
            try:
                decision = MovingAverageStrategy().analyze(self._stock_code or "")
                with self._lock:
                    self._last_signal = decision.signal
                    self._message = (
                        f"{decision.stock_code}: {decision.signal} 신호 확인. "
                        "다음 확인까지 대기합니다."
                    )

                can_execute = decision.signal in {"BUY", "SELL"} and (
                    self._trade_mode == "BOTH" or self._trade_mode == decision.signal
                )
                if can_execute:
                    if stop_event.is_set():
                        return
                    db = SessionLocal()
                    try:
                        execute_paper_order(
                            db,
                            side=decision.signal,
                            stock_code=decision.stock_code,
                            quantity=self._quantity or 1,
                            execution_price=decision.current_price,
                        )
                    finally:
                        db.close()
                    with self._lock:
                        if not stop_event.is_set():
                            self._running = False
                            self._state = "COMPLETED"
                            self._last_order = decision.signal
                            self._message = (
                                f"{decision.signal} 신호로 모의 {decision.signal} 주문 1회를 완료했습니다."
                            )
                    return
            except (PaperTradingError, ValueError) as error:
                with self._lock:
                    self._running = False
                    self._state = "ERROR"
                    self._message = str(error)
                return
            except Exception:
                with self._lock:
                    self._running = False
                    self._state = "ERROR"
                    self._message = "자동매수 시세 또는 전략 조회에 실패했습니다."
                return

            stop_event.wait(self.interval_seconds)


auto_buy_manager = AutoBuyManager()
