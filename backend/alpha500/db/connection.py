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
    with app() as conn:
        conn.executescript(_read_sql("schema_app.sql"))
