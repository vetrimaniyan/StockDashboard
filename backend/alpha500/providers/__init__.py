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
    "stable_token",
]


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
