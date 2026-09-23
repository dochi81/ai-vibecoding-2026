"""Safe in-memory lifecycle control for the v0.1 paper-trading engine."""

from threading import Lock

from app.config import settings


class TraderRuntime:
    """Control whether local paper orders are allowed, never broker orders."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._running = False

    def start(self) -> dict[str, str | bool]:
        """Allow local paper orders only.

        v0.1 intentionally rejects a live-trading setting because no live order
        path is implemented or permitted here.
        """
        if settings.live_trading:
            raise RuntimeError("Live trading is not supported by this application.")
        with self._lock:
            self._running = True
            return self.status()

    def stop(self) -> dict[str, str | bool]:
        """Stop paper-mode monitoring."""
        with self._lock:
            self._running = False
            return self.status()

    def status(self) -> dict[str, str | bool]:
        """Return state suitable for the dashboard without sensitive data."""
        return {
            "running": self._running,
            "mode": "PAPER",
            "message": (
                "모의 주문이 허용되었습니다. 매수 또는 매도를 실행할 수 있습니다."
                if self._running
                else "모의 주문이 잠겨 있습니다. 실제 주문은 항상 차단됩니다."
            ),
        }


trader_runtime = TraderRuntime()
