"""Database connections and schema bootstrap."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb

from alpha500.config import settings

_SCHEMA_DIR = Path(__file__).parent


def _read_sql(name: str) -> str:
    return (_SCHEMA_DIR / name).read_text(encoding="utf-8")


class DatabaseBusyError(RuntimeError):
    """The analytical store is held by another process.

    DuckDB permits one read-write process or many read-only ones, never both.
    The nightly pipeline is a writer, so reads during a run must fail visibly
    rather than appear as a server error — the UI reports "pipeline running"
    instead of showing nothing.
    """


# One DuckDB connection per process, shared by every caller.
#
# DuckDB also refuses to mix modes *within* a process: opening read-write while
# a read-only connection is alive raises ConnectionException. That matters
# because `serve --with-scheduler` runs the API and the nightly pipeline in one
# process (D-6, and what §2.1 intends by in-process APScheduler). Handing every
# caller a cursor off one shared connection is what makes that combination work
# — otherwise the 18:45 run dies the first night, silently, in the dark.
_shared: duckdb.DuckDBPyConnection | None = None
_shared_read_only: bool | None = None
_shared_lock = threading.Lock()


def configure_process_connection(read_only: bool) -> None:
    """Fix this process's access mode. Call once, before first use."""
    global _shared_read_only
    with _shared_lock:
        if _shared is not None and _shared_read_only != read_only:
            raise RuntimeError(
                "analytical connection already open in "
                f"{'read-only' if _shared_read_only else 'read-write'} mode"
            )
        _shared_read_only = read_only


def close_process_connection() -> None:
    global _shared, _shared_read_only
    with _shared_lock:
        if _shared is not None:
            _shared.close()
        _shared = None
        _shared_read_only = None


@contextmanager
def analytical(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    """A cursor on this process's shared analytical connection.

    ``read_only`` is honoured only for the first open in the process; after
    that the mode is fixed. Use :func:`configure_process_connection` to state
    it explicitly at startup.
    """
    global _shared, _shared_read_only
    settings.ensure_dirs()

    with _shared_lock:
        if _shared is None:
            mode = _shared_read_only if _shared_read_only is not None else read_only
            try:
                _shared = duckdb.connect(str(settings.analytical_db), read_only=mode)
            except (duckdb.IOException, duckdb.ConnectionException) as exc:
                raise DatabaseBusyError(
                    "Analytical store is locked by another process, most likely "
                    "a pipeline run in progress."
                ) from exc
            _shared_read_only = mode
        parent = _shared

    # A cursor is an independent handle on the same database instance, which
    # is how concurrent request threads and the scheduler stay out of each
    # other's way without reopening the file.
    cursor = parent.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


@contextmanager
def app() -> Iterator[sqlite3.Connection]:
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.app_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_databases() -> None:
    """Create both stores if absent. Safe to call repeatedly.

    The analytical schema is skipped when this process holds the store
    read-only — a plain ``serve`` cannot create tables, and should not need
    to: ``alpha500 init`` does that. The SQLite store is always writable.
    """
    if _shared_read_only is not True:
        with analytical() as conn:
            conn.execute(_read_sql("schema.sql"))
            _migrate_metric_columns(conn)
    with app() as conn:
        conn.executescript(_read_sql("schema_app.sql"))


def _migrate_metric_columns(conn: duckdb.DuckDBPyConnection) -> None:
    """Add metric columns that a newer engine expects but the file predates.

    ``CREATE TABLE IF NOT EXISTS`` is a no-op once the table exists, so a schema
    change is otherwise invisible to any store that already holds data, and the
    first write fails on a column nobody added. The materialised history is
    hours of rate-limited fetching, so migrating beats rebuilding it.

    The table is rewritten rather than altered in place. ``ALTER TABLE ADD
    COLUMN`` against ``metrics_daily`` — which carries a two-column primary key
    over ~800k rows — left DuckDB's ART index inconsistent, and the next
    ``DELETE`` for a single date failed with "Failed to delete all rows from
    index. Only deleted 50 out of 500 rows", a FATAL error that killed the
    connection. Rewriting costs seconds and rebuilds the index cleanly.

    Values in the new columns stay NULL until the next recompute, which the
    engine fingerprint in ``metrics_meta`` already surfaces as staleness.
    """
    from alpha500.metrics.engine import METRIC_COLUMNS

    _rewrite_if_missing(conn, "instruments", ["float_shares", "float_shares_as_of"])

    existing = [
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'metrics_daily' ORDER BY ordinal_position"
        ).fetchall()
    ]
    if not existing:
        return
    missing = [name for name in METRIC_COLUMNS if name not in existing]
    if not missing:
        return

    carried = ", ".join(existing)
    try:
        # Secondary indexes depend on the table and block the rename;
        # schema.sql recreates them.
        conn.execute("DROP INDEX IF EXISTS idx_metrics_date_rank")
        conn.execute("ALTER TABLE metrics_daily RENAME TO metrics_daily_migrating")
        # Recreate from the current schema, primary key and all.
        conn.execute(_read_sql("schema.sql"))
        conn.execute(
            f"INSERT INTO metrics_daily ({carried}) "
            f"SELECT {carried} FROM metrics_daily_migrating"
        )
        conn.execute("DROP TABLE metrics_daily_migrating")
    except Exception:
        # Leave the original in place under its temporary name rather than
        # losing it; the failure is loud and the data is recoverable.
        raise


def _rewrite_if_missing(
    conn: duckdb.DuckDBPyConnection, table: str, expected: list[str]
) -> None:
    """Rebuild ``table`` through the current schema if any column is absent.

    Same reasoning as the metrics migration: ALTER TABLE ADD COLUMN against a
    table carrying a primary-key index corrupted DuckDB's ART index once
    already, and a rewrite costs seconds.
    """
    existing = [
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
    ]
    if not existing or all(name in existing for name in expected):
        return

    carried = ", ".join(existing)
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_migrating")
    conn.execute(_read_sql("schema.sql"))
    conn.execute(
        f"INSERT INTO {table} ({carried}) SELECT {carried} FROM {table}_migrating"
    )
    conn.execute(f"DROP TABLE {table}_migrating")
