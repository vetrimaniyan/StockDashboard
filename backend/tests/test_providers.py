"""Provider contract tests (NFR-5.3).

Run against recorded fixtures with no network access. AR-1 is the most
important structural requirement in the SRS, so these assert the boundary
holds as much as they assert behaviour.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from alpha500.providers import (
    CsvFileProvider,
    MarketDataProvider,
    NseArchiveProvider,
    YahooProvider,
    get_provider,
    get_provider_adjustment_flags,
    stable_token,
)
from alpha500.providers.models import ProviderError, SchemaDriftError
from alpha500.providers.nse_archive import _require_columns


# --- the AR-1 boundary ---------------------------------------------------


def test_every_provider_implements_the_interface():
    for cls in (YahooProvider, NseArchiveProvider, CsvFileProvider):
        assert issubclass(cls, MarketDataProvider)
        for method in ("list_instruments", "get_daily_candles", "get_corporate_actions"):
            assert callable(getattr(cls, method))


def test_no_module_outside_the_provider_package_imports_a_vendor_sdk():
    """AR-1: NSE endpoints and broker APIs both change without notice.

    Keeping vendor imports and URL construction inside one package is what
    makes that a one-file change rather than a hunt.
    """
    root = Path(__file__).resolve().parents[1] / "alpha500"
    offenders: list[str] = []

    for path in root.rglob("*.py"):
        if "providers" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("import yfinance", "nseindia.com", "nsearchives", "kiteconnect"):
            if needle in text:
                offenders.append(f"{path.relative_to(root)}: {needle}")

    assert not offenders, "vendor access leaked outside the provider package: " + str(offenders)


def test_provider_factory_resolves_known_names():
    assert isinstance(get_provider("yahoo"), YahooProvider)
    assert isinstance(get_provider("nse"), NseArchiveProvider)
    with pytest.raises(ValueError, match="unknown provider"):
        get_provider("bloomberg")


def test_adjustment_flags_are_declared_not_guessed():
    """FR-3.2 forbids assuming either way, so each provider must state it."""
    flags = get_provider_adjustment_flags()
    assert flags["YAHOO"] is True
    assert flags["NSE_BHAVCOPY"] is False


# --- stable tokens -------------------------------------------------------


def test_token_is_stable_across_calls():
    """AR-4: metric output must be reproducible, so ids cannot drift."""
    assert stable_token("INE002A01018", "RELIANCE") == stable_token(
        "INE002A01018", "RELIANCE"
    )


def test_token_follows_isin_not_symbol():
    """A rename must not orphan a decade of price history."""
    before = stable_token("INE002A01018", "OLDNAME")
    after = stable_token("INE002A01018", "NEWNAME")
    assert before == after


def test_token_differs_between_instruments():
    assert stable_token("INE002A01018", "RELIANCE") != stable_token(
        "INE009A01021", "INFY"
    )


def test_token_falls_back_to_symbol_without_isin():
    assert stable_token(None, "RELIANCE") == stable_token(None, "RELIANCE")
    assert stable_token(None, "RELIANCE") != stable_token(None, "INFY")


def test_token_fits_in_a_signed_64_bit_column():
    for symbol in ("RELIANCE", "INFY", "M&M", "BAJAJ-AUTO", "360ONE"):
        assert 0 < stable_token(None, symbol) < 2**63


# --- schema drift (FR-2.6) ----------------------------------------------


def test_missing_columns_raise_rather_than_yield_nulls():
    """FR-2.6: the template is volatile and must fail loudly.

    Silently producing nulls is precisely the failure this guards against —
    it would look like a quiet day rather than a broken parser.
    """
    with pytest.raises(SchemaDriftError, match="Missing columns"):
        _require_columns(["TradDt", "TckrSymb"], frozenset({"TradDt", "ClsPric"}), "test")


def test_present_columns_pass():
    _require_columns(["A", "B", "C"], frozenset({"A", "B"}), "test")


# --- CsvFileProvider -----------------------------------------------------


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    (tmp_path / "candles").mkdir()
    (tmp_path / "actions").mkdir()
    (tmp_path / "index").mkdir()

    with (tmp_path / "instruments.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["tradingsymbol", "name", "isin", "series", "industry", "sector"])
        writer.writerow(["ACME", "Acme Ltd", "INE000A01001", "EQ", "Capital Goods", "Industrials"])
        writer.writerow(["BETA", "Beta Ltd", "INE000A01002", "BE", "Financial Services", "Finance"])

    with (tmp_path / "candles" / "ACME.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["trade_date", "open", "high", "low", "close", "volume", "delivery_pct"])
        for day, price in ((1, 100), (2, 102), (3, 101), (4, 105)):
            writer.writerow([f"2026-01-0{day}", price, price + 1, price - 1, price, 10_000, 0.5])

    with (tmp_path / "actions" / "ACME.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ex_date", "action_type", "ratio_from", "ratio_to", "amount"])
        writer.writerow(["2026-01-03", "SPLIT", 1, 2, ""])

    return tmp_path


def test_csv_provider_lists_instruments(fixture_root: Path):
    provider = CsvFileProvider(fixture_root)
    instruments = provider.list_instruments()
    assert [i.tradingsymbol for i in instruments] == ["ACME", "BETA"]
    assert instruments[0].isin == "INE000A01001"


def test_csv_provider_returns_candles_in_date_order(fixture_root: Path):
    provider = CsvFileProvider(fixture_root)
    instrument = provider.list_instruments()[0]
    candles = provider.get_daily_candles(instrument, date(2026, 1, 1), date(2026, 1, 4))

    assert len(candles) == 4
    assert [c.trade_date for c in candles] == sorted(c.trade_date for c in candles)
    assert candles[-1].close == 105


def test_csv_provider_honours_the_date_range(fixture_root: Path):
    provider = CsvFileProvider(fixture_root)
    instrument = provider.list_instruments()[0]
    candles = provider.get_daily_candles(instrument, date(2026, 1, 2), date(2026, 1, 3))
    assert len(candles) == 2


def test_csv_provider_returns_empty_for_an_unknown_symbol(fixture_root: Path):
    provider = CsvFileProvider(fixture_root)
    beta = provider.list_instruments()[1]
    assert provider.get_daily_candles(beta, date(2026, 1, 1), date(2026, 1, 4)) == ()


def test_csv_provider_reads_corporate_actions(fixture_root: Path):
    provider = CsvFileProvider(fixture_root)
    instrument = provider.list_instruments()[0]
    actions = provider.get_corporate_actions(instrument)
    assert len(actions) == 1
    assert actions[0].action_type == "SPLIT"
    assert actions[0].ratio_to == 2.0


def test_csv_provider_rejects_a_missing_root():
    with pytest.raises(ProviderError, match="does not exist"):
        CsvFileProvider("/no/such/path")


# --- Yahoo -------------------------------------------------------------


def test_yahoo_refuses_to_serve_the_universe():
    """The constituent list is NSE's to publish (FR-1.2)."""
    with pytest.raises(NotImplementedError):
        YahooProvider().list_instruments()


def test_yahoo_symbol_mapping():
    from alpha500.providers.yahoo import to_yahoo_symbol

    assert to_yahoo_symbol("RELIANCE") == "RELIANCE.NS"
    assert to_yahoo_symbol("bajaj-auto") == "BAJAJ-AUTO.NS"
