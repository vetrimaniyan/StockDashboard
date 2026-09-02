"""Materialise ``metrics_daily`` across a date range.

The nightly path computes one session: it runs the per-symbol pass over the
full price history, keeps the last row, and discards the rest. A backtest needs
every row it discards — the metrics as they stood on each historical session,
computed only from data available by then.

Doing that naively runs out of memory. The per-symbol pass produces ~55 columns
over ~1 250 sessions for 500 symbols, and the boolean columns are object arrays
of Python objects, so holding every symbol at once costs several hundred
megabytes. But the cross-sectional pass (RS rating, ranks, composite z) needs
all symbols present at a single date, which is the opposite access pattern.

So this runs in two passes: the per-symbol series metrics are staged to a table
one symbol at a time, then the cross-sectional pass reads that table back in
date-ordered chunks. Memory stays bounded by one symbol in pass 1 and one chunk
of dates in pass 2.

AR-4 still holds: the output is a function of stored prices alone, and
recomputing the same range produces the same rows.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Sequence

import duckdb
import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from alpha500.config import settings
from alpha500.metrics import periods as p
from alpha500.metrics.engine import (
    _BOOL_COLUMNS,
    _DATE_COLUMNS,
    _INT_COLUMNS,
    _TEXT_COLUMNS,
    METRIC_COLUMNS,
    _finalise_cross_section,
    _load_prices,
)
from alpha500.metrics.fingerprint import engine_fingerprint
from alpha500.metrics.series import compute_series_metrics

# Columns the cross-sectional pass produces; everything else comes from the
# per-symbol pass and can be staged.
CROSS_SECTIONAL: frozenset[str] = frozenset(
    {
        "is_eligible", "ineligible_reason",
        "rs_1m", "rs_3m", "rs_6m", "rs_12m", "rs_rating",
        "trend_template_score", "is_trend_template", "is_pullback",
        "momentum_rank", "composite_z",
    }
)

SERIES_COLUMNS: tuple[str, ...] = tuple(
    name for name in METRIC_COLUMNS if name not in CROSS_SECTIONAL
)

# Carried through the staging table because the cross-sectional pass needs
# them, though they are not themselves published metrics.
HELPER_COLUMNS: tuple[str, ...] = ("trend_template_partial", "close_adj")

_STAGE_COLUMNS: tuple[str, ...] = SERIES_COLUMNS + HELPER_COLUMNS

STAGE_TABLE = "metrics_stage"


def _sql_type(name: str) -> str:
    if name in _DATE_COLUMNS:
        return "DATE"
    if name in _TEXT_COLUMNS:
        return "VARCHAR"
    if name in _BOOL_COLUMNS:
        return "BOOLEAN"
    if name in _INT_COLUMNS:
        return "BIGINT"
    return "DOUBLE"


def _arrow_type(name: str) -> pa.DataType:
    if name in _DATE_COLUMNS:
        return pa.date32()
    if name in _TEXT_COLUMNS:
        return pa.string()
    if name in _BOOL_COLUMNS:
        return pa.bool_()
    if name in _INT_COLUMNS:
        return pa.int64()
    return pa.float64()


def _clean(name: str, values: NDArray[Any]) -> list[Any]:
    """Convert a metric column to Python values Arrow can type strictly.

    Non-finite floats become NULL rather than NaN so the stored metric is
    absent rather than silently poisoning comparisons downstream — FR-6.1
    requires a metric with insufficient history to be null, never zero.
    """
    out: list[Any] = []
    is_date = name in _DATE_COLUMNS
    is_text = name in _TEXT_COLUMNS
    is_bool = name in _BOOL_COLUMNS
    is_int = name in _INT_COLUMNS
    for value in values:
        if value is None:
            out.append(None)
            continue
        if is_date:
            # A date carries no numeric reading, so it must never reach the
            # float path below — that raises, which is how the FR-17 columns
            # took the historical materialiser down while the nightly path
            # (engine._coerce) handled them correctly all along.
            out.append(value if isinstance(value, date) else None)
            continue
        if is_text:
            text = str(value).strip()
            out.append(text or None)
            continue
        if is_bool:
            if isinstance(value, (bool, np.bool_)):
                out.append(bool(value))
            else:
                numeric = float(value)
                out.append(None if not np.isfinite(numeric) else bool(numeric))
            continue
        numeric = float(value)
        if not np.isfinite(numeric):
            out.append(None)
        elif is_int:
            out.append(int(round(numeric)))
        else:
            out.append(numeric)
    return out


def _index_return_series(
    conn: duckdb.DuckDBPyConnection, index_name: str
) -> dict[int, dict[date, float]]:
    """Index return over each window, per session (FR-6.3)."""
    rows = conn.execute(
        "SELECT trade_date, close FROM index_ohlcv_daily "
        "WHERE index_name = ? ORDER BY trade_date",
        [index_name],
    ).fetchall()
    dates = [r[0] for r in rows]
    closes = np.array([float(r[1]) for r in rows], dtype=np.float64)

    out: dict[int, dict[date, float]] = {}
    for window in (p.MONTH, p.QUARTER, p.HALF_YEAR, p.YEAR):
        mapping: dict[date, float] = {}
        if closes.size > window:
            prior = closes[:-window]
            current = closes[window:]
            with np.errstate(divide="ignore", invalid="ignore"):
                rets = np.where(prior > 0, current / prior - 1.0, np.nan)
            for day, value in zip(dates[window:], rets):
                if np.isfinite(value):
                    mapping[day] = float(value)
        out[window] = mapping
    return out


def _create_stage(conn: duckdb.DuckDBPyConnection) -> None:
    cols = ",\n    ".join(f"{name} {_sql_type(name)}" for name in _STAGE_COLUMNS)
    conn.execute(f"DROP TABLE IF EXISTS {STAGE_TABLE}")
    conn.execute(
        f"""
        CREATE TABLE {STAGE_TABLE} (
            instrument_token BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            {cols}
        )
        """
    )


def _stage_symbol(
    conn: duckdb.DuckDBPyConnection,
    token: int,
    data: dict[str, NDArray[Any]],
) -> int:
    computed = compute_series_metrics(
        trade_date=data["trade_date"],
        open_=data["open"],
        high=data["high"],
        low=data["low"],
        close=data["close"],
        volume=data["volume"],
        delivery_pct=data.get("delivery_pct"),
    )
    n = len(data["trade_date"])
    if n == 0:
        return 0

    arrays: dict[str, pa.Array] = {
        "instrument_token": pa.array([token] * n, pa.int64()),
        "trade_date": pa.array(list(data["trade_date"]), pa.date32()),
    }
    for name in _STAGE_COLUMNS:
        column = computed.columns.get(name)
        if column is None:
            arrays[name] = pa.nulls(n, _arrow_type(name))
        else:
            arrays[name] = pa.array(_clean(name, column), _arrow_type(name))

    table = pa.table(arrays)
    conn.register("_stage_batch", table)
    conn.execute(f"INSERT INTO {STAGE_TABLE} SELECT * FROM _stage_batch")
    conn.unregister("_stage_batch")
    return n


def materialise_history(
    conn: duckdb.DuckDBPyConnection,
    start: date,
    end: date,
    index_name: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Compute and persist metrics for every session in ``[start, end]``.

    Returns the number of metric rows written.
    """
    index_name = index_name or settings.index_name
    say = progress or (lambda _msg: None)

    universe = conn.execute(
        """
        SELECT i.instrument_token, i.tradingsymbol, COALESCE(i.series, 'EQ')
          FROM instruments i
          JOIN index_membership m ON m.instrument_token = i.instrument_token
         WHERE m.index_name = ? AND m.valid_to IS NULL
         ORDER BY i.tradingsymbol
        """,
        [index_name],
    ).fetchall()
    if not universe:
        return 0

    tokens = [int(r[0]) for r in universe]
    symbol_of = {int(r[0]): str(r[1]) for r in universe}
    series_of = {int(r[0]): str(r[2]) for r in universe}

    # Pass 1 — per-symbol series metrics, staged one symbol at a time.
    say(f"pass 1/2  series metrics for {len(tokens)} symbols")
    _create_stage(conn)
    prices = _load_prices(conn, tokens, end)
    staged = 0
    for position, token in enumerate(tokens, start=1):
        data = prices.get(token)
        if data is None or data["close"].size == 0:
            continue
        staged += _stage_symbol(conn, token, data)
        if position % 100 == 0:
            say(f"  staged {position}/{len(tokens)} symbols, {staged:,} rows")
    del prices

    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_stage_date ON {STAGE_TABLE} (trade_date)"
    )

    # Pass 2 — cross-sections, date by date.
    sessions = [
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT trade_date FROM {STAGE_TABLE} "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [start, end],
        ).fetchall()
    ]
    say(f"pass 2/2  cross-sections for {len(sessions)} sessions")

    index_returns = _index_return_series(conn, index_name)
    written = 0
    stamp = datetime.now(timezone.utc)
    fingerprint = engine_fingerprint()

    conn.execute("DELETE FROM metrics_daily WHERE trade_date BETWEEN ? AND ?", [start, end])
    conn.execute("DELETE FROM metrics_meta WHERE trade_date BETWEEN ? AND ?", [start, end])

    for position, session in enumerate(sessions, start=1):
        rows = _cross_section_for_date(
            conn, session, symbol_of, series_of, index_returns
        )
        if rows:
            _bulk_write(conn, rows)
            conn.execute(
                "INSERT INTO metrics_meta VALUES (?,?,?,?)",
                [session, fingerprint, stamp, len(rows["instrument_token"])],
            )
            written += len(rows["instrument_token"])
        if position % 100 == 0:
            say(f"  {position}/{len(sessions)} sessions, {written:,} rows")

    conn.execute(f"DROP TABLE IF EXISTS {STAGE_TABLE}")
    say(f"done: {written:,} metric rows across {len(sessions)} sessions")
    return written


def _cross_section_for_date(
    conn: duckdb.DuckDBPyConnection,
    session: date,
    symbol_of: dict[int, str],
    series_of: dict[int, str],
    index_returns: dict[int, dict[date, float]],
) -> dict[str, Any] | None:
    table = conn.execute(
        f"SELECT * FROM {STAGE_TABLE} WHERE trade_date = ? ORDER BY instrument_token",
        [session],
    ).fetch_arrow_table()
    if table.num_rows == 0:
        return None

    tokens = table.column("instrument_token").to_pylist()
    symbols = [symbol_of.get(t, "") for t in tokens]
    codes = [series_of.get(t, "EQ") for t in tokens]

    # Only numeric columns can go into a float array. Dates, text and booleans
    # each need an object array: FR-17 staged the first two for the first time,
    # and reading either back as a float is what took this path down.
    arrays: dict[str, NDArray[Any]] = {}
    for name in _STAGE_COLUMNS:
        values = table.column(name).to_pylist()
        if name in _DATE_COLUMNS:
            arrays[name] = np.array(
                [v if isinstance(v, date) else None for v in values], dtype=object
            )
        elif name in _TEXT_COLUMNS:
            arrays[name] = np.array(
                [None if v is None else str(v) for v in values], dtype=object
            )
        elif name in _BOOL_COLUMNS:
            arrays[name] = np.array(
                [None if v is None else bool(v) for v in values], dtype=object
            )
        else:
            arrays[name] = np.array(
                [np.nan if v is None else v for v in values], dtype=np.float64
            )

    # Cross-sectional columns are filled in by the shared finaliser, so the
    # historical path and the nightly path cannot drift apart.
    for name in CROSS_SECTIONAL:
        arrays.setdefault(name, np.full(len(tokens), np.nan))

    idx_for_date = {
        window: mapping.get(session) for window, mapping in index_returns.items()
    }
    _finalise_cross_section(arrays, symbols, codes, idx_for_date, None)

    out: dict[str, Any] = {
        "instrument_token": tokens,
        "trade_date": [session] * len(tokens),
    }
    for name in METRIC_COLUMNS:
        out[name] = _clean(name, arrays[name])
    return out


def _bulk_write(conn: duckdb.DuckDBPyConnection, rows: dict[str, Any]) -> None:
    arrays = {
        "instrument_token": pa.array(rows["instrument_token"], pa.int64()),
        "trade_date": pa.array(rows["trade_date"], pa.date32()),
    }
    for name in METRIC_COLUMNS:
        arrays[name] = pa.array(rows[name], _arrow_type(name))
    table = pa.table(arrays)
    conn.register("_metrics_batch", table)
    columns = ", ".join(("instrument_token", "trade_date", *METRIC_COLUMNS))
    conn.execute(
        f"INSERT INTO metrics_daily ({columns}) SELECT * FROM _metrics_batch"
    )
    conn.unregister("_metrics_batch")
