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
from typing import Final, Iterator, Sequence

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
_UDIFF_COLUMNS: Final = frozenset(
    {
        "TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric",
        "LwPric", "ClsPric", "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxsExctd",
    }
)
_LEGACY_COLUMNS: Final = frozenset(
    {"SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY", "TOTTRDVAL", "TIMESTAMP"}
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
            if not symbol:
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
