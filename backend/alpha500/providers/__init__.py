"""Market-data providers. The only package permitted to talk to a data vendor."""

from __future__ import annotations

from pathlib import Path

from alpha500.providers.base import MarketDataProvider
from alpha500.providers.csv_file import CsvFileProvider
from alpha500.providers.models import (
    ActionType,
    Candle,
    CorporateAction,
    Instrument,
    ProviderError,
    SchemaDriftError,
    stable_token,
)
from alpha500.providers.nse_archive import NseArchiveProvider
from alpha500.providers.yahoo import YahooProvider

__all__ = [
    "ActionType",
    "Candle",
    "CorporateAction",
    "CsvFileProvider",
    "Instrument",
    "MarketDataProvider",
    "NseArchiveProvider",
    "ProviderError",
    "SchemaDriftError",
    "YahooProvider",
    "get_provider",
    "get_provider_adjustment_flags",
    "stable_token",
]


def get_provider_adjustment_flags() -> dict[str, bool]:
    """``{source_name: prices_are_adjusted}`` for every known provider.

    The adjustment layer needs this to interpret stored rows, and reading it
    off the provider classes keeps the fact in one place — next to the
    reconciliation evidence that established it.
    """
    return {
        cls.name: cls.prices_are_adjusted
        for cls in (YahooProvider, NseArchiveProvider, CsvFileProvider)
    }


def get_provider(name: str, *, fixture_root: Path | str | None = None) -> MarketDataProvider:
    key = name.strip().lower()
    if key in {"nse", "nse_archive", "nse_bhavcopy"}:
        return NseArchiveProvider()
    if key in {"yahoo", "yfinance"}:
        return YahooProvider()
    if key in {"csv", "fixture", "csv_file"}:
        if fixture_root is None:
            raise ValueError("CsvFileProvider requires fixture_root")
        return CsvFileProvider(fixture_root)
    raise ValueError(f"unknown provider: {name}")
