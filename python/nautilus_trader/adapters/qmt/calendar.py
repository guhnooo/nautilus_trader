"""QMT trading-calendar helpers backed by the Rust adapter transport."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Self

from nautilus_trader._libnautilus.qmt import QmtCalendarClient


class QmtTradingCalendar:
    """Cache QMT A-share trading dates and expose session queries."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._trading_days: set[date] = set()
        self._loaded = False
        self.last_error: str | None = None

    @classmethod
    def from_env(cls) -> Self:
        return cls(QmtCalendarClient.from_env())

    @property
    def loaded(self) -> bool:
        return self._loaded

    def refresh(self, *, today: date | None = None) -> bool:
        if self._client is None:
            return False
        current = today or datetime.now().astimezone().date()
        start = (current - timedelta(days=7)).strftime("%Y%m%d")
        end = (current + timedelta(days=370)).strftime("%Y%m%d")
        try:
            values = self._client.get_trading_dates(
                market="SH",
                start_time=start,
                end_time=end,
                count=-1,
            )
            parsed = {
                date(int(text[:4]), int(text[4:6]), int(text[6:8]))
                for value in (values if isinstance(values, list) else [])
                if len(text := str(value)) == 8
            }
            if not parsed:
                raise RuntimeError("QMT returned an empty trading calendar")
            self._trading_days = parsed
            self._loaded = True
            self.last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 - calendar failure falls back to weekday
            self.last_error = f"{type(exc).__name__}: {exc}"
            if not self._trading_days:
                self._loaded = False
            return False

    def is_trading_day(self, value: date) -> bool:
        if self._loaded:
            return value in self._trading_days
        return value.weekday() < 5

    def get_trade_times(self, stockcode: str) -> Any:
        """Return native QMT sessions when the bridge/SDK supports them."""
        if self._client is None:
            raise RuntimeError("QMT calendar client is not configured")
        return self._client.get_trade_times(stockcode=stockcode)
