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


@contextmanager
def analytical(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    settings.ensure_dirs()
    conn = duckdb.connect(str(settings.analytical_db), read_only=read_only)
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
