"""Ingestion stages.

AR-2: raw data is persisted verbatim before any transformation, so every
derived metric can be rebuilt offline from what is stored.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Callable, Sequence

import duckdb

from alpha500.config import settings
from alpha500.db import store
from alpha500.mktcal import calendar as cal
from alpha500.pipeline.adjust import apply_adjustments
from alpha500.providers import (
    Instrument,
    NseArchiveProvider,
    ProviderError,
    YahooProvider,
)

log = logging.getLogger(__name__)

Progress = Callable[[str, int, int], None]


def _noop(_msg: str, _done: int, _total: int) -> None:
    return None


def sync_universe(
    conn: duckdb.DuckDBPyConnection,
    provider: NseArchiveProvider,
    as_of: date | None = None,
) -> tuple[int, list[str], list[str]]:
    """Refresh instruments and index membership. Returns (count, added, removed)."""
    as_of = as_of or date.today()
    instruments = provider.list_instruments()
    store.upsert_instruments(conn, instruments, as_of)

    tokens = {i.instrument_token for i in instruments}
    added, removed = store.sync_index_membership(conn, settings.index_name, tokens, as_of)

    by_token = {i.instrument_token: i.tradingsymbol for i in instruments}
    added_symbols = [by_token.get(t, str(t)) for t in added]
    removed_symbols = [
        conn.execute(
            "SELECT tradingsymbol FROM instruments WHERE instrument_token = ?", [t]
        ).fetchone()[0]
        for t in removed
    ]
    return len(instruments), added_symbols, removed_symbols


def backfill_prices(
    conn: duckdb.DuckDBPyConnection,
    instruments: Sequence[Instrument],
    years: int = 5,
    provider: YahooProvider | None = None,
    progress: Progress = _noop,
    force: bool = False,
) -> tuple[int, list[str]]:
    """Bulk history load (FR-2.2).

    Never triggered automatically (FR-2.5): a full backfill is hours of
    rate-limited calls and is always an explicit command.

    Checkpoints per symbol (FR-5.3) — a symbol that already holds enough
    history is skipped, so a crash resumes rather than restarting.
    """
    provider = provider or YahooProvider()
    end = date.today()
    start = end - timedelta(days=int(years * 365.25) + 10)

    total_rows = 0
    failures: list[str] = []
    total = len(instruments)

    for i, instrument in enumerate(instruments, start=1):
        progress(instrument.tradingsymbol, i, total)
        if not force:
            existing = conn.execute(
                "SELECT count(*), min(trade_date) FROM ohlcv_daily WHERE instrument_token = ?",
                [instrument.instrument_token],
            ).fetchone()
            if existing[0] >= settings.min_history_days and existing[1] is not None:
                if existing[1] <= start + timedelta(days=45):
                    continue

        try:
            candles = provider.get_daily_candles(instrument, start, end)
        except ProviderError as exc:
            log.warning("backfill failed for %s: %s", instrument.tradingsymbol, exc)
            failures.append(instrument.tradingsymbol)
            continue

        if not candles:
            failures.append(instrument.tradingsymbol)
            continue

        total_rows += store.upsert_candles(
            conn, instrument.instrument_token, candles, provider.name
        )

    return total_rows, failures


def backfill_index(
    conn: duckdb.DuckDBPyConnection,
    years: int = 5,
    provider: YahooProvider | None = None,
) -> int:
    provider = provider or YahooProvider()
    end = date.today()
    start = end - timedelta(days=int(years * 365.25) + 10)
    candles = provider.get_index_candles(settings.index_name, start, end)
    return store.upsert_index_candles(conn, settings.index_name, candles, provider.name)


def incremental_prices(
    conn: duckdb.DuckDBPyConnection,
    provider: NseArchiveProvider,
    through: date | None = None,
    overlap_sessions: int = 5,
    progress: Progress = _noop,
) -> tuple[int, list[date]]:
    """Daily incremental fetch (FR-2.5).

    Re-fetches the last few stored sessions on purpose: late corrections and
    restatements land after the fact, and the overlap is what lets them
    replace the provisional values.
    """
    through = through or date.today()
    latest = store.latest_stored_date(conn)

    if latest is None:
        start = through - timedelta(days=10)
    else:
        recent = cal.trading_days_between(conn, latest - timedelta(days=30), latest)
        start = recent[-overlap_sessions] if len(recent) >= overlap_sessions else latest

    symbol_to_token = {
        row[0]: int(row[1])
        for row in conn.execute(
            """
            SELECT i.tradingsymbol, i.instrument_token
              FROM instruments i
              JOIN index_membership m ON m.instrument_token = i.instrument_token
             WHERE m.index_name = ? AND m.valid_to IS NULL
            """,
            [settings.index_name],
        ).fetchall()
    }

    sessions = cal.trading_days_between(conn, start, through)
    written: list[date] = []
    total_rows = 0

    for i, session_date in enumerate(sessions, start=1):
        progress(str(session_date), i, len(sessions))
        try:
            by_symbol = provider.fetch_session(session_date)
        except ProviderError as exc:
            log.info("no bhavcopy for %s: %s", session_date, exc)
            continue
        if not by_symbol:
            continue

        by_token = {
            symbol_to_token[sym]: candle
            for sym, candle in by_symbol.items()
            if sym in symbol_to_token
        }
        if not by_token:
            continue

        total_rows += store.upsert_session_candles(
            conn, session_date, by_token, provider.name
        )

        delivery = provider.fetch_delivery(session_date)
        if delivery:
            store.update_delivery(
                conn,
                session_date,
                {
                    symbol_to_token[sym]: value
                    for sym, value in delivery.items()
                    if sym in symbol_to_token
                },
            )
        written.append(session_date)

    return total_rows, written


def incremental_index(
    conn: duckdb.DuckDBPyConnection,
    provider: YahooProvider | None = None,
    lookback_days: int = 30,
) -> int:
    provider = provider or YahooProvider()
    end = date.today()
    candles = provider.get_index_candles(
        settings.index_name, end - timedelta(days=lookback_days), end
    )
    return store.upsert_index_candles(conn, settings.index_name, candles, provider.name)


def sync_corporate_actions(
    conn: duckdb.DuckDBPyConnection,
    instruments: Sequence[Instrument],
    provider: YahooProvider | None = None,
    progress: Progress = _noop,
) -> int:
    """Fetch CA events and recompute adj_factor for affected symbols."""
    provider = provider or YahooProvider()
    total = 0
    for i, instrument in enumerate(instruments, start=1):
        progress(instrument.tradingsymbol, i, len(instruments))
        try:
            actions = provider.get_corporate_actions(instrument)
        except ProviderError as exc:
            log.warning("corporate actions failed for %s: %s", instrument.tradingsymbol, exc)
            continue
        if actions:
            total += store.upsert_corporate_actions(
                conn, instrument.instrument_token, actions
            )
        apply_adjustments(conn, instrument.instrument_token)
    return total


def cross_source_sample(
    conn: duckdb.DuckDBPyConnection,
    session_date: date,
    nse_rows: dict[str, float],
    sample_size: int = 10,
) -> dict[str, tuple[float, float]]:
    """Stored close vs freshly-fetched NSE close for a deterministic sample (V9).

    The sample is seeded from the date rather than the clock, so a run is
    reproducible (AR-4).
    """
    rows = conn.execute(
        """
        SELECT i.tradingsymbol, o.close
          FROM ohlcv_daily o
          JOIN instruments i ON i.instrument_token = o.instrument_token
         WHERE o.trade_date = ?
         ORDER BY hash(i.tradingsymbol || ?)
         LIMIT ?
        """,
        [session_date, session_date.isoformat(), sample_size],
    ).fetchall()
    return {
        sym: (float(stored), float(nse_rows[sym]))
        for sym, stored in rows
        if sym in nse_rows
    }
