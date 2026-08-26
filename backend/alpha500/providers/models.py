"""Transport types shared across providers.

These are the only shapes that cross the provider boundary (AR-1). Nothing
vendor-specific — no Kite dicts, no NSE column names — may leak past here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


def stable_token(isin: str | None, tradingsymbol: str) -> int:
    """Deterministic surrogate for Kite's ``instrument_token``.

    The schema is keyed on an integer token because it was designed against
    Kite. Free sources supply no such id, so we derive one. ISIN is preferred
    over symbol: symbols get renamed, ISINs do not, and a rename must not
    orphan a decade of price history.
    """
    seed = (isin or f"SYM:{tradingsymbol}").strip().upper()
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFF_FFFF_FFFF_FFFF


class ActionType(StrEnum):
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    DIVIDEND = "DIVIDEND"
    RIGHTS = "RIGHTS"
    MERGER = "MERGER"


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_token: int
    tradingsymbol: str
    name: str | None = None
    isin: str | None = None
    series: str | None = None
    exchange: str = "NSE"
    industry: str | None = None
    sector: str | None = None
    basic_industry: str | None = None
    exchange_token: int | None = None
    lot_size: int | None = None
    tick_size: float | None = None


@dataclass(frozen=True, slots=True)
class Candle:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    traded_value: float | None = None
    vwap: float | None = None
    num_trades: int | None = None
    delivery_qty: int | None = None
    delivery_pct: float | None = None


@dataclass(frozen=True, slots=True)
class CorporateAction:
    ex_date: date
    action_type: ActionType
    ratio_from: float | None = None
    ratio_to: float | None = None
    amount: float | None = None
    raw_purpose: str | None = None


class ProviderError(RuntimeError):
    """Raised on any provider-layer failure. Callers must not see vendor errors."""


class SchemaDriftError(ProviderError):
    """Upstream file/response no longer matches the expected shape.

    FR-2.6 requires this to fail loudly rather than silently yield nulls.
    """
