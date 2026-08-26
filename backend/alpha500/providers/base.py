"""The MarketDataProvider interface (AR-1).

No module outside this package may import a vendor SDK or construct an
exchange URL. NSE endpoints and broker APIs both change without notice; this
boundary is what keeps that a one-file change.
"""

from __future__ import annotations

import random
import threading
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Callable, Sequence, TypeVar

from alpha500.providers.models import Candle, CorporateAction, Instrument, ProviderError

T = TypeVar("T")


class TokenBucket:
    """Rate limiter (FR-2.4). Thread-safe; the pipeline must not exceed it."""

    def __init__(self, rate_per_s: float, burst: int = 1) -> None:
        if rate_per_s <= 0:
            raise ValueError("rate_per_s must be positive")
        self._rate = rate_per_s
        self._capacity = float(max(burst, 1))
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._last) * self._rate
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                time.sleep((1.0 - self._tokens) / self._rate)


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_retries: int,
    base_delay: float = 1.0,
    label: str = "request",
) -> T:
    """Exponential backoff with jitter (FR-2.4)."""
    last: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - vendor errors are opaque here
            last = exc
            if attempt == max_retries:
                break
            delay = base_delay * (2**attempt) + random.uniform(0, base_delay)
            time.sleep(delay)
    raise ProviderError(f"{label} failed after {max_retries} retries: {last}") from last


class MarketDataProvider(ABC):
    """Every market-data access in the system goes through this interface."""

    name: str

    #: Whether this source already back-adjusts its history for splits and
    #: bonuses. FR-3.2 forbids assuming either way, so each provider declares
    #: it and the reconciliation test proves the declaration correct.
    #: Getting this wrong in either direction corrupts every derived metric:
    #: too little adjustment leaves a spurious -50% return on the ex-date,
    #: too much leaves a spurious +100% one.
    prices_are_adjusted: bool = False

    @abstractmethod
    def list_instruments(self) -> Sequence[Instrument]:
        """Return the tradeable universe this provider knows about."""

    @abstractmethod
    def get_daily_candles(
        self, instrument: Instrument, start: date, end: date
    ) -> Sequence[Candle]:
        """Daily OHLCV for ``instrument`` over the inclusive date range."""

    @abstractmethod
    def get_corporate_actions(self, instrument: Instrument) -> Sequence[CorporateAction]:
        """Splits, bonuses, dividends and similar events for ``instrument``."""

    def get_index_candles(
        self, index_name: str, start: date, end: date
    ) -> Sequence[Candle]:
        """Index level series. Optional — not every provider can serve it."""
        raise NotImplementedError(f"{self.name} cannot serve index candles")

    def supports_delivery_data(self) -> bool:
        return False
