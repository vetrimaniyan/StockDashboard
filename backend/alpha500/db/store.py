"""Persistence for the analytical store.

Every write is an upsert keyed on the natural key (AR-3), so re-running the
pipeline for a date already processed cannot duplicate rows.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable, Sequence

import duckdb

from alpha500.providers.models import Candle, CorporateAction, Instrument


_OHLCV_STAGE_COLUMNS = (
    "instrument_token", "trade_date", "open", "high", "low", "close", "volume",
    "traded_value", "vwap", "num_trades", "delivery_qty", "delivery_pct",
    "source", "ingested_at",
)

# The columns a universe sync actually knows about. Deliberately not "every
# column in instruments": float_shares, float_shares_as_of and index_tier are
# owned by the marketcap and indices commands, and a sync must leave them
# alone. Naming them here also keeps the INSERT below independent of the
# table's width, so adding a column cannot silently break the nightly run.
_INSTRUMENT_STAGE_COLUMNS = (
    "instrument_token", "exchange_token", "tradingsymbol", "name", "isin",
    "series", "exchange", "industry", "sector", "basic_industry",
    "lot_size", "tick_size", "is_active", "first_seen_date", "last_seen_date",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stage_rows(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    columns: Sequence[str],
    rows: Sequence[tuple],
) -> None:
    """Bulk-load rows into a temp table via Arrow.

    Row-at-a-time ``executemany`` costs milliseconds per row in DuckDB, which
    turns a 625k-row backfill into a long wait. Handing over one Arrow table
    instead keeps the write proportional to the data rather than the row count.
    """
    import pyarrow as pa

    arrays = list(zip(*rows)) if rows else [() for _ in columns]
    arrow_table = pa.table({name: pa.array(values) for name, values in zip(columns, arrays)})
    conn.register("_bulk_stage", arrow_table)
    try:
        conn.execute(f"CREATE OR REPLACE TEMP TABLE {table} AS SELECT * FROM _bulk_stage")
    finally:
        conn.unregister("_bulk_stage")


def upsert_instruments(conn: duckdb.DuckDBPyConnection, instruments: Sequence[Instrument],
                       seen_on: date) -> int:
    if not instruments:
        return 0
    rows = [
        (
            i.instrument_token, i.exchange_token, i.tradingsymbol, i.name, i.isin,
            i.series, i.exchange, i.industry, i.sector, i.basic_industry,
            i.lot_size, i.tick_size, True, seen_on, seen_on,
        )
        for i in instruments
    ]
    cols = ", ".join(_INSTRUMENT_STAGE_COLUMNS)
    placeholders = ",".join("?" * len(_INSTRUMENT_STAGE_COLUMNS))
    conn.execute(
        f"CREATE OR REPLACE TEMP TABLE _inst_stage AS "
        f"SELECT {cols} FROM instruments LIMIT 0"
    )
    conn.executemany(f"INSERT INTO _inst_stage ({cols}) VALUES ({placeholders})", rows)
    conn.execute(
        """
        UPDATE instruments AS t
           SET tradingsymbol = s.tradingsymbol,
               name           = COALESCE(s.name, t.name),
               isin           = COALESCE(s.isin, t.isin),
               series         = COALESCE(s.series, t.series),
               industry       = COALESCE(s.industry, t.industry),
               sector         = COALESCE(s.sector, t.sector),
               basic_industry = COALESCE(s.basic_industry, t.basic_industry),
               is_active      = TRUE,
               last_seen_date = s.last_seen_date
          FROM _inst_stage AS s
         WHERE t.instrument_token = s.instrument_token
        """
    )
    # Named on both sides for the same reason as the stage load: an unnamed
    # INSERT ... SELECT s.* breaks the moment instruments gains a column the
    # sync does not populate. Columns omitted here take their schema default.
    conn.execute(
        f"""
        INSERT INTO instruments ({cols})
        SELECT {', '.join('s.' + c for c in _INSTRUMENT_STAGE_COLUMNS)}
          FROM _inst_stage s
         WHERE NOT EXISTS (
            SELECT 1 FROM instruments t WHERE t.instrument_token = s.instrument_token
        )
        """
    )
    return len(rows)


def upsert_candles(
    conn: duckdb.DuckDBPyConnection,
    instrument_token: int,
    candles: Iterable[Candle],
    source: str,
) -> int:
    ingested_at = _now()
    rows = [
        (
            instrument_token, c.trade_date, c.open, c.high, c.low, c.close,
            c.volume, c.traded_value, c.vwap, c.num_trades,
            c.delivery_qty, c.delivery_pct, source, ingested_at,
        )
        for c in candles
    ]
    if not rows:
        return 0
    _stage_rows(conn, "_ohlcv_stage", _OHLCV_STAGE_COLUMNS, rows)
    _merge_stage_into_ohlcv(conn)
    return len(rows)


def upsert_session_candles(
    conn: duckdb.DuckDBPyConnection,
    session_date: date,
    by_token: dict[int, Candle],
    source: str,
) -> int:
    """Bulk-write one session across many instruments (the bhavcopy shape)."""
    ingested_at = _now()
    rows = [
        (
            token, c.trade_date, c.open, c.high, c.low, c.close, c.volume,
            c.traded_value, c.vwap, c.num_trades, c.delivery_qty, c.delivery_pct,
            source, ingested_at,
        )
        for token, c in by_token.items()
    ]
    if not rows:
        return 0
    _stage_rows(conn, "_ohlcv_stage", _OHLCV_STAGE_COLUMNS, rows)
    _merge_stage_into_ohlcv(conn)
    return len(rows)


def _merge_stage_into_ohlcv(conn: duckdb.DuckDBPyConnection) -> None:
    # COALESCE on the optional columns so a source that lacks delivery data
    # cannot erase values a richer source already wrote for the same key.
    conn.execute(
        """
        UPDATE ohlcv_daily AS t
           SET open = s.open, high = s.high, low = s.low, close = s.close,
               volume = s.volume,
               traded_value = COALESCE(s.traded_value, t.traded_value),
               vwap         = COALESCE(s.vwap, t.vwap),
               num_trades   = COALESCE(s.num_trades, t.num_trades),
               delivery_qty = COALESCE(s.delivery_qty, t.delivery_qty),
               delivery_pct = COALESCE(s.delivery_pct, t.delivery_pct),
               source = s.source, ingested_at = s.ingested_at
          FROM _ohlcv_stage AS s
         WHERE t.instrument_token = s.instrument_token
           AND t.trade_date = s.trade_date
        """
    )
    conn.execute(
        """
        INSERT INTO ohlcv_daily (
            instrument_token, trade_date, open, high, low, close, volume,
            traded_value, vwap, num_trades, delivery_qty, delivery_pct,
            source, ingested_at
        )
        SELECT s.instrument_token, s.trade_date, s.open, s.high, s.low, s.close,
               s.volume, s.traded_value, s.vwap, s.num_trades,
               s.delivery_qty, s.delivery_pct, s.source, s.ingested_at
          FROM _ohlcv_stage s
         WHERE NOT EXISTS (
            SELECT 1 FROM ohlcv_daily t
             WHERE t.instrument_token = s.instrument_token
               AND t.trade_date = s.trade_date
         )
        """
    )


def update_delivery(
    conn: duckdb.DuckDBPyConnection, session_date: date, by_token: dict[int, tuple[int, float]]
) -> int:
    if not by_token:
        return 0
    rows = [(qty, pct, token, session_date) for token, (qty, pct) in by_token.items()]
    conn.executemany(
        """
        UPDATE ohlcv_daily SET delivery_qty = ?, delivery_pct = ?
         WHERE instrument_token = ? AND trade_date = ?
        """,
        rows,
    )
    return len(rows)


def upsert_index_candles(
    conn: duckdb.DuckDBPyConnection, index_name: str, candles: Sequence[Candle], source: str
) -> int:
    if not candles:
        return 0
    ingested_at = _now()
    rows = [
        (index_name, c.trade_date, c.open, c.high, c.low, c.close, c.volume,
         source, ingested_at)
        for c in candles
    ]
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _idx_stage (
            index_name VARCHAR, trade_date DATE,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
            source VARCHAR, ingested_at TIMESTAMP
        )
        """
    )
    conn.executemany("INSERT INTO _idx_stage VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.execute(
        """
        UPDATE index_ohlcv_daily AS t
           SET open = s.open, high = s.high, low = s.low, close = s.close,
               volume = s.volume, source = s.source, ingested_at = s.ingested_at
          FROM _idx_stage AS s
         WHERE t.index_name = s.index_name AND t.trade_date = s.trade_date
        """
    )
    conn.execute(
        """
        INSERT INTO index_ohlcv_daily
        SELECT s.* FROM _idx_stage s
        WHERE NOT EXISTS (
            SELECT 1 FROM index_ohlcv_daily t
             WHERE t.index_name = s.index_name AND t.trade_date = s.trade_date
        )
        """
    )
    return len(rows)


def upsert_corporate_actions(
    conn: duckdb.DuckDBPyConnection, instrument_token: int, actions: Sequence[CorporateAction]
) -> int:
    if not actions:
        return 0
    rows = [
        (instrument_token, a.ex_date, str(a.action_type), a.ratio_from, a.ratio_to,
         a.amount, a.raw_purpose)
        for a in actions
    ]
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _ca_stage (
            instrument_token BIGINT, ex_date DATE, action_type VARCHAR,
            ratio_from DOUBLE, ratio_to DOUBLE, amount DOUBLE, raw_purpose VARCHAR
        )
        """
    )
    conn.executemany("INSERT INTO _ca_stage VALUES (?,?,?,?,?,?,?)", rows)
    conn.execute(
        """
        DELETE FROM corporate_actions t
         WHERE EXISTS (
            SELECT 1 FROM _ca_stage s
             WHERE s.instrument_token = t.instrument_token
               AND s.ex_date = t.ex_date AND s.action_type = t.action_type
         )
        """
    )
    conn.execute("INSERT INTO corporate_actions SELECT * FROM _ca_stage")
    return len(rows)


def sync_index_membership(
    conn: duckdb.DuckDBPyConnection,
    index_name: str,
    current_tokens: set[int],
    as_of: date,
) -> tuple[list[int], list[int]]:
    """Maintain membership as a slowly-changing dimension (FR-1.4).

    Returns ``(added_tokens, removed_tokens)``. History is closed off with a
    ``valid_to`` rather than deleted — a departed constituent's price history
    is required for unbiased backtests.
    """
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT instrument_token FROM index_membership "
            "WHERE index_name = ? AND valid_to IS NULL",
            [index_name],
        ).fetchall()
    }
    added = sorted(current_tokens - existing)
    removed = sorted(existing - current_tokens)

    if removed:
        conn.executemany(
            "UPDATE index_membership SET valid_to = ? "
            "WHERE index_name = ? AND instrument_token = ? AND valid_to IS NULL",
            [(as_of, index_name, t) for t in removed],
        )
    if added:
        conn.executemany(
            "INSERT INTO index_membership VALUES (?,?,?,NULL) "
            "ON CONFLICT DO NOTHING",
            [(index_name, t, as_of) for t in added],
        )
    return added, removed


def last_trade_date(conn: duckdb.DuckDBPyConnection, instrument_token: int) -> date | None:
    row = conn.execute(
        "SELECT max(trade_date) FROM ohlcv_daily WHERE instrument_token = ?",
        [instrument_token],
    ).fetchone()
    return row[0] if row and row[0] else None


def latest_stored_date(conn: duckdb.DuckDBPyConnection) -> date | None:
    row = conn.execute("SELECT max(trade_date) FROM ohlcv_daily").fetchone()
    return row[0] if row and row[0] else None


def active_universe(conn: duckdb.DuckDBPyConnection, index_name: str) -> list[Instrument]:
    rows = conn.execute(
        """
        SELECT i.instrument_token, i.tradingsymbol, i.name, i.isin, i.series,
               i.industry, i.sector, i.basic_industry
          FROM instruments i
          JOIN index_membership m ON m.instrument_token = i.instrument_token
         WHERE m.index_name = ? AND m.valid_to IS NULL
         ORDER BY i.tradingsymbol
        """,
        [index_name],
    ).fetchall()
    return [
        Instrument(
            instrument_token=r[0], tradingsymbol=r[1], name=r[2], isin=r[3],
            series=r[4], industry=r[5], sector=r[6], basic_industry=r[7],
        )
        for r in rows
    ]
