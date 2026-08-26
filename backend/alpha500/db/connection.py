"""Database connections and schema bootstrap."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb

from alpha500.config import settings

_SCHEMA_DIR = Path(__file__).parent


def _read_sql(name: str) -> str:
    return (_SCHEMA_DIR / name).read_text(encoding="utf-8")


class DatabaseBusyError(RuntimeError):
    """The analytical store is held by a writer.

    DuckDB permits one read-write process or many read-only ones, never both.
    The nightly pipeline is a writer, so reads during a run must fail visibly
    rather than appear as a server error — the UI reports "pipeline running"
    instead of showing nothing.
    """


@contextmanager
def analytical(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    settings.ensure_dirs()
    try:
        conn = duckdb.connect(str(settings.analytical_db), read_only=read_only)
    except duckdb.IOException as exc:
        raise DatabaseBusyError(
            "Analytical store is locked by another process, most likely a "
            "pipeline run in progress."
        ) from exc
    try:
        yield conn
    finally:
        conn.close()


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
    """Create both stores if absent. Safe to call repeatedly."""
    with analytical() as conn:
        conn.execute(_read_sql("schema.sql"))
    with app() as conn:
        conn.executescript(_read_sql("schema_app.sql"))
