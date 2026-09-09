"""NseArchiveProvider — free EOD data straight from NSE's public archive.

The SRS specifies this as the fallback behind Kite Connect. Kite Connect is a
paid subscription this deployment does not hold, so it is the primary source
for incremental daily data instead. That is a deviation from section 2.1 and
is recorded in DECISIONS.md.

Three files matter:
  * the Nifty 500 constituent list (universe)
  * the UDiFF full bhavcopy (one file per session, all symbols)
  * the securities delivery position file (delivery quantity / percentage)

All three have changed format historically. Every parse validates its header
against an expected column set and raises SchemaDriftError on mismatch, per
FR-2.6 — silently producing nulls is the failure mode this guards against.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from typing import Any, Final, Iterator, Sequence

from alpha500.providers.base import MarketDataProvider
from alpha500.providers.models import (
    Candle,
    CorporateAction,
    Instrument,
    ProviderError,
    SchemaDriftError,
    stable_token,
)
from alpha500.providers.nse_http import NSE_ARCHIVES, NseSession

# FR-1.2: verify against https://www.nseindia.com/all-reports at build time.
NIFTY500_LIST_URL: Final = f"{NSE_ARCHIVES}/content/indices/ind_nifty500list.csv"

# The NIFTY 500 is exactly its four size tiers: 50 + 50 + 150 + 250. Microcap
# 250 covers ranks 501-750 and is deliberately absent — it is outside the
# universe, though its valuation is still worth tracking.
TIER_LIST_URLS: Final[dict[str, str]] = {
    "NIFTY50": f"{NSE_ARCHIVES}/content/indices/ind_nifty50list.csv",
    "NIFTYNEXT50": f"{NSE_ARCHIVES}/content/indices/ind_niftynext50list.csv",
    "NIFTYMIDCAP150": f"{NSE_ARCHIVES}/content/indices/ind_niftymidcap150list.csv",
    "NIFTYSMALLCAP250": f"{NSE_ARCHIVES}/content/indices/ind_niftysmallcap250list.csv",
}

# FR-18.1: constituent list per tracked index. Verified live 2026-09-07 — all
# 24 resolve, and every one carries the same header as the NIFTY 500 list, so
# `list_instruments`' parser and its drift guard apply unchanged.
#
# Two slugs break the obvious pattern with an underscore before "list"; they
# cost a request each to find and are not guessable. Nifty Capital Markets is
# absent because no candidate slug resolved (B-10).
INDEX_CONSTITUENT_SLUGS: Final[dict[str, str]] = {
    "Nifty Bank": "ind_niftybanklist.csv",
    "Nifty IT": "ind_niftyitlist.csv",
    "Nifty Auto": "ind_niftyautolist.csv",
    "Nifty Pharma": "ind_niftypharmalist.csv",
    "Nifty FMCG": "ind_niftyfmcglist.csv",
    "Nifty Metal": "ind_niftymetallist.csv",
    "Nifty Realty": "ind_niftyrealtylist.csv",
    "Nifty Media": "ind_niftymedialist.csv",
    "Nifty PSU Bank": "ind_niftypsubanklist.csv",
    "Nifty Private Bank": "ind_nifty_privatebanklist.csv",
    "Nifty Financial Services": "ind_niftyfinancelist.csv",
    "Nifty Healthcare Index": "ind_niftyhealthcarelist.csv",
    "Nifty Consumer Durables": "ind_niftyconsumerdurableslist.csv",
    "Nifty Oil & Gas": "ind_niftyoilgaslist.csv",
    "Nifty Energy": "ind_niftyenergylist.csv",
    "Nifty Infrastructure": "ind_niftyinfralist.csv",
    "Nifty Commodities": "ind_niftycommoditieslist.csv",
    "Nifty India Consumption": "ind_niftyconsumptionlist.csv",
    "Nifty CPSE": "ind_cpselist.csv",
    "Nifty PSE": "ind_niftypselist.csv",
    "Nifty MNC": "ind_niftymnclist.csv",
    "Nifty Services Sector": "ind_niftyservicelist.csv",
    "Nifty India Defence": "ind_niftyindiadefence_list.csv",
    "Nifty India Manufacturing": "ind_niftyindiamanufacturing_list.csv",
}

# Daily close file carrying P/E, P/B and dividend yield for every published
# index. Verify the path at build time; NSE archive URLs are volatile (R-1).
INDEX_CLOSE_URL: Final = f"{NSE_ARCHIVES}/content/indices/ind_close_all_{{ddmmyyyy}}.csv"

# FR-2.6: UDiFF bhavcopy, current format (NSE migrated to this in July 2024).
UDIFF_BHAVCOPY_URL: Final = (
    NSE_ARCHIVES + "/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
)
# Pre-UDiFF layout, still needed for any backfill reaching before 2024-07-08.
LEGACY_BHAVCOPY_URL: Final = (
    NSE_ARCHIVES + "/content/historical/EQUITIES/{yyyy}/{MMM}/cm{ddMMMyyyy}bhav.csv.zip"
)
UDIFF_CUTOVER: Final = date(2024, 7, 8)

DELIVERY_URL: Final = NSE_ARCHIVES + "/archives/equities/mto/MTO_{ddmmyyyy}.DAT"

_NIFTY500_COLUMNS: Final = frozenset(
    {"Company Name", "Industry", "Symbol", "Series", "ISIN Code"}
)

# NSE lists a placeholder constituent while a corporate action is in flight —
# "DUMMYHEG" for the HEG demerger, carrying ISIN "DUM545A01024" where a real
# Indian security's ISIN begins "IN". It never trades, so it arrives with no
# price history and no eligibility, and every screen filters it out anyway.
# The cost of keeping it is elsewhere: it inflates the constituent count and,
# worse, surfaces in the Universe changes panel as a new entrant, which is
# exactly the signal that panel exists to make trustworthy (FR-1.2).
#
# Matched on the symbol prefix, which is NSE's own convention, rather than on
# the ISIN — a real listing with an unusual ISIN is a thing that could happen,
# a real company named DUMMY-something is not.
_PLACEHOLDER_SYMBOL_PREFIX: Final = "DUMMY"

_UDIFF_COLUMNS: Final = frozenset(
    {
        "TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric",
        "LwPric", "ClsPric", "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxsExctd",
    }
)
_LEGACY_COLUMNS: Final = frozenset(
    {"SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY", "TOTTRDVAL", "TIMESTAMP"}
)
# Only the fields actually read below. The file carries open/high/low, points
# change and turnover too, and NSE may reasonably add or reorder those without
# it meaning anything to us — requiring the whole header would turn a harmless
# addition into a nightly failure.
_INDEX_CLOSE_COLUMNS: Final = frozenset(
    {"Index Name", "Closing Index Value", "P/E", "P/B", "Div Yield"}
)


def _require_columns(actual: Sequence[str], expected: frozenset[str], what: str) -> None:
    missing = expected - {c.strip() for c in actual}
    if missing:
        raise SchemaDriftError(
            f"{what}: upstream schema changed. Missing columns {sorted(missing)}. "
            f"Got {list(actual)}. Refusing to parse rather than emit nulls."
        )


def _f(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text or text in {"-", "NA"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class NseArchiveProvider(MarketDataProvider):
    name = "NSE_BHAVCOPY"

    # The bhavcopy is the raw exchange print for that session and is never
    # back-adjusted, so every split after a row's own trade date applies to it.
    prices_are_adjusted = False

    def __init__(self, session: NseSession | None = None) -> None:
        self._session = session or NseSession()

    # --- universe --------------------------------------------------------

    def list_instruments(self) -> Sequence[Instrument]:
        """FR-1.1/FR-1.2: current NIFTY 500 constituents."""
        resp = self._session.get(NIFTY500_LIST_URL)
        text = resp.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise SchemaDriftError("Nifty 500 list: empty response")
        _require_columns(reader.fieldnames, _NIFTY500_COLUMNS, "Nifty 500 list")

        instruments: list[Instrument] = []
        for row in reader:
            symbol = (row.get("Symbol") or "").strip()
            if not symbol or symbol.upper().startswith(_PLACEHOLDER_SYMBOL_PREFIX):
                continue
            isin = (row.get("ISIN Code") or "").strip() or None
            instruments.append(
                Instrument(
                    instrument_token=stable_token(isin, symbol),
                    tradingsymbol=symbol,
                    name=(row.get("Company Name") or "").strip() or None,
                    isin=isin,
                    series=(row.get("Series") or "EQ").strip() or "EQ",
                    industry=(row.get("Industry") or "").strip() or None,
                )
            )
        if len(instruments) < 400:
            raise SchemaDriftError(
                f"Nifty 500 list returned only {len(instruments)} rows; expected ~500"
            )
        return instruments

    # --- prices ----------------------------------------------------------

    def get_daily_candles(
        self, instrument: Instrument, start: date, end: date
    ) -> Sequence[Candle]:
        """Single-symbol slice of the bhavcopy range.

        Inefficient by design of the source: the bhavcopy is a per-session file
        covering every symbol, so fetching one symbol over N sessions costs N
        downloads. Backfill must use :meth:`iter_session_candles` instead;
        this method exists to satisfy the interface and serve small gap fills.
        """
        out: list[Candle] = []
        for _session_date, rows in self.iter_session_candles(start, end):
            candle = rows.get(instrument.tradingsymbol)
            if candle is not None:
                out.append(candle)
        return out

    def iter_session_candles(
        self, start: date, end: date
    ) -> Iterator[tuple[date, dict[str, Candle]]]:
        """Yield ``(session_date, {symbol: candle})`` for each session in range.

        One HTTP request per session covers the entire universe, which is what
        makes this source practical for a nightly incremental run.
        """
        current = start
        while current <= end:
            if current.weekday() < 5:  # cheap pre-filter; the calendar is authoritative
                try:
                    yield current, self.fetch_session(current)
                except ProviderError:
                    # Holiday or not-yet-published: the caller's validation gate
                    # (V7/V8) decides whether a missing session is a problem.
                    pass
            current = date.fromordinal(current.toordinal() + 1)

    def fetch_session(self, session_date: date) -> dict[str, Candle]:
        if session_date >= UDIFF_CUTOVER:
            return self._fetch_udiff(session_date)
        return self._fetch_legacy(session_date)

    def _unzip_single_csv(self, payload: bytes, what: str) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not names:
                    raise SchemaDriftError(f"{what}: archive contains no CSV")
                return zf.read(names[0]).decode("utf-8-sig")
        except zipfile.BadZipFile as exc:
            raise ProviderError(f"{what}: not a zip archive (likely a 404 page)") from exc

    def _fetch_udiff(self, session_date: date) -> dict[str, Candle]:
        url = UDIFF_BHAVCOPY_URL.format(yyyymmdd=session_date.strftime("%Y%m%d"))
        text = self._unzip_single_csv(
            self._session.get(url).content, f"UDiFF bhavcopy {session_date}"
        )
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise SchemaDriftError(f"UDiFF bhavcopy {session_date}: empty")
        _require_columns(reader.fieldnames, _UDIFF_COLUMNS, f"UDiFF bhavcopy {session_date}")

        out: dict[str, Candle] = {}
        for row in reader:
            if (row.get("SctySrs") or "").strip() not in {"EQ", "BE"}:
                continue
            symbol = (row.get("TckrSymb") or "").strip()
            close = _f(row.get("ClsPric"))
            if not symbol or close is None:
                continue
            out[symbol] = Candle(
                trade_date=session_date,
                open=_f(row.get("OpnPric")) or close,
                high=_f(row.get("HghPric")) or close,
                low=_f(row.get("LwPric")) or close,
                close=close,
                volume=int(_f(row.get("TtlTradgVol")) or 0),
                traded_value=_f(row.get("TtlTrfVal")),
                num_trades=int(_f(row.get("TtlNbOfTxsExctd")) or 0) or None,
            )
        return out

    def _fetch_legacy(self, session_date: date) -> dict[str, Candle]:
        url = LEGACY_BHAVCOPY_URL.format(
            yyyy=session_date.strftime("%Y"),
            MMM=session_date.strftime("%b").upper(),
            ddMMMyyyy=session_date.strftime("%d%b%Y").upper(),
        )
        text = self._unzip_single_csv(
            self._session.get(url).content, f"legacy bhavcopy {session_date}"
        )
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise SchemaDriftError(f"legacy bhavcopy {session_date}: empty")
        _require_columns(reader.fieldnames, _LEGACY_COLUMNS, f"legacy bhavcopy {session_date}")

        out: dict[str, Candle] = {}
        for row in reader:
            if (row.get("SERIES") or "").strip() not in {"EQ", "BE"}:
                continue
            symbol = (row.get("SYMBOL") or "").strip()
            close = _f(row.get("CLOSE"))
            if not symbol or close is None:
                continue
            out[symbol] = Candle(
                trade_date=session_date,
                open=_f(row.get("OPEN")) or close,
                high=_f(row.get("HIGH")) or close,
                low=_f(row.get("LOW")) or close,
                close=close,
                volume=int(_f(row.get("TOTTRDQTY")) or 0),
                traded_value=_f(row.get("TOTTRDVAL")),
            )
        return out

    # --- delivery (FR-2.7) ----------------------------------------------

    def supports_delivery_data(self) -> bool:
        return True

    def fetch_delivery(self, session_date: date) -> dict[str, tuple[int, float]]:
        """``{symbol: (delivery_qty, delivery_pct)}`` for one session.

        FR-2.7: failure here is a warning, not a pipeline failure, so this
        returns an empty mapping rather than raising when the file is absent.
        """
        url = DELIVERY_URL.format(ddmmyyyy=session_date.strftime("%d%m%Y"))
        try:
            payload = self._session.get(url).content.decode("utf-8", errors="replace")
        except ProviderError:
            return {}

        out: dict[str, tuple[int, float]] = {}
        for line in payload.splitlines():
            parts = [p.strip() for p in line.split(",")]
            # Record layout: 20,<seq>,<symbol>,<series>,<traded qty>,<delivery qty>,<pct>
            if len(parts) < 7 or parts[0] != "20":
                continue
            if parts[3] not in {"EQ", "BE"}:
                continue
            qty = _f(parts[5])
            pct = _f(parts[6])
            if qty is None or pct is None:
                continue
            out[parts[2]] = (int(qty), pct / 100.0)
        return out

    # --- corporate actions ----------------------------------------------

    def get_corporate_actions(self, instrument: Instrument) -> Sequence[CorporateAction]:
        """Not served here.

        NSE's corporate-action archive is a separate, differently-shaped feed
        (open item B-2). YahooProvider supplies split and dividend history for
        now; returning an empty sequence keeps this provider honest rather
        than pretending to cover it.
        """
        return ()

    def close(self) -> None:
        self._session.close()

    def get_index_tiers(self) -> dict[str, str]:
        """Symbol -> size tier across the four NIFTY 500 constituent lists.

        A symbol belongs to exactly one tier, so the last write wins only if
        NSE publishes an overlap, which would itself be worth knowing about.
        """
        tiers: dict[str, str] = {}
        for tier, url in TIER_LIST_URLS.items():
            resp = self._session.get(url)
            for row in csv.DictReader(io.StringIO(resp.text)):
                symbol = (row.get("Symbol") or "").strip().upper()
                if symbol:
                    tiers[symbol] = tier
        return tiers

    def get_index_constituents(self, index_name: str) -> list[str]:
        """Trading symbols of one tracked index (FR-18.1).

        The list carries no weight column — no NSE constituent file does — so
        FR-18.9 derives weight from free-float market cap instead.
        """
        slug = INDEX_CONSTITUENT_SLUGS.get(index_name)
        if slug is None:
            raise ProviderError(f"no constituent list mapped for index {index_name}")
        resp = self._session.get(f"{NSE_ARCHIVES}/content/indices/{slug}")
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))
        if reader.fieldnames is None:
            raise SchemaDriftError(f"{index_name} constituents: empty response")
        _require_columns(reader.fieldnames, _NIFTY500_COLUMNS, f"{index_name} constituents")
        out = [(r.get("Symbol") or "").strip().upper() for r in reader]
        # Same placeholder rows appear here: HEG sits in Nifty Metal, so its
        # stand-in does too, and a member the NIFTY 500 no longer carries would
        # fail the member-floor check for reasons that have nothing to do with
        # the index.
        return [
            s for s in out
            if s and not s.startswith(_PLACEHOLDER_SYMBOL_PREFIX)
        ]

    def get_index_valuations(self, on: date) -> list[dict[str, Any]]:
        """P/E, P/B and dividend yield for every index on one session.

        Returns an empty list when the file is absent, which is how a holiday
        or a not-yet-published session presents. The caller decides whether
        that is a gap worth reporting.
        """
        url = INDEX_CLOSE_URL.format(ddmmyyyy=on.strftime("%d%m%Y"))
        try:
            resp = self._session.get(url)
        except ProviderError:
            return []

        # utf-8-sig, as the constituent lists use: the first column is the one
        # read below, so a byte-order mark would attach to "Index Name" itself
        # and every row would parse as nameless.
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))
        if reader.fieldnames is None:
            raise SchemaDriftError(f"index close {on}: empty response")
        # A rename here is invisible without this. index_name keeps parsing, so
        # rows still insert and the stage still reports a non-zero row count,
        # while every ratio silently becomes NULL and the medians built on them
        # quietly thin out. That is the failure this module exists to refuse.
        _require_columns(reader.fieldnames, _INDEX_CLOSE_COLUMNS, f"index close {on}")

        out: list[dict[str, Any]] = []
        for row in reader:
            name = (row.get("Index Name") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "index_name": name,
                    # A level or a valuation multiple at or below zero is not a
                    # number to compare against, but a dividend yield of zero
                    # is a real reading: it means no constituent paid out.
                    "close": _positive(_to_float(row.get("Closing Index Value"))),
                    "pe": _positive(_to_float(row.get("P/E"))),
                    "pb": _positive(_to_float(row.get("P/B"))),
                    "div_yield": _non_negative(_to_float(row.get("Div Yield"))),
                }
            )
        return out


def _to_float(text: Any) -> float | None:
    """Parse one cell. NSE writes '-' for an index with no meaningful ratio.

    Deliberately does no sign filtering: which values are meaningful depends on
    the field, and folding that in here once applied the P/E rule to dividend
    yield too, turning a genuine zero payout into a missing reading.
    """
    if text is None:
        return None
    cleaned = str(text).strip().replace(",", "")
    if not cleaned or cleaned in {"-", "NA", "N.A."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _positive(value: float | None) -> float | None:
    """For levels and valuation multiples.

    A zero or negative P/E is an aggregate of loss-making constituents and is
    not a valuation; store it as absent rather than as a number to median.
    """
    return value if value is not None and value > 0 else None


def _non_negative(value: float | None) -> float | None:
    """For dividend yield, where zero is a reading and not an absence."""
    return value if value is not None and value >= 0 else None
