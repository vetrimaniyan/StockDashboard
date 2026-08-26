"""Shared fixtures.

Builds a self-contained analytical store with deterministic synthetic price
history, so the metric engine and validation gate can be exercised with no
network and no credentials (NFR-5.3).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

SCHEMA = Path(__file__).resolve().parents[1] / "alpha500" / "db" / "schema.sql"

START = date(2021, 1, 4)
SESSIONS = 400


def trading_days(count: int, start: date = START) -> list[date]:
    """Weekday sessions. Deterministic, so fixtures never shift under a rerun."""
    out: list[date] = []
    day = start
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def synth_series(
    dates: list[date],
    start_price: float,
    drift: float,
    wobble: float = 0.0,
    gap_at: int | None = None,
    gap_size: float = 0.60,
) -> list[tuple[date, float, float, float, float, int]]:
    """A reproducible OHLCV series with a chosen drift and optional shock."""
    rows = []
    price = start_price
    for i, day in enumerate(dates):
        if gap_at is not None and i == gap_at:
            price *= 1.0 + gap_size
        else:
            price *= 1.0 + drift + wobble * math.sin(i / 7.0)
        close = round(price, 2)
        high = round(close * 1.012, 2)
        low = round(close * 0.988, 2)
        open_ = round((high + low) / 2, 2)
        volume = 500_000 + (i % 11) * 25_000
        rows.append((day, open_, high, low, close, volume))
    return rows


@pytest.fixture
def conn(tmp_path: Path):
    connection = duckdb.connect(str(tmp_path / "test.duckdb"))
    connection.execute(SCHEMA.read_text(encoding="utf-8"))
    yield connection
    connection.close()


def insert_symbol(
    connection: duckdb.DuckDBPyConnection,
    token: int,
    symbol: str,
    rows: list[tuple[date, float, float, float, float, int]],
    index_name: str = "NIFTY500",
    series: str = "EQ",
    industry: str = "Test Industry",
) -> None:
    connection.execute(
        "INSERT INTO instruments (instrument_token, tradingsymbol, name, series, "
        "exchange, industry, is_active) VALUES (?,?,?,?,?,?,TRUE)",
        [token, symbol, f"{symbol} Ltd", series, "NSE", industry],
    )
    connection.execute(
        "INSERT INTO index_membership VALUES (?,?,?,NULL)",
        [index_name, token, rows[0][0]],
    )
    import pyarrow as pa

    now = datetime.now(timezone.utc)
    arrow_table = pa.table(
        {
            "instrument_token": pa.array([token] * len(rows), pa.int64()),
            "trade_date": pa.array([r[0] for r in rows], pa.date32()),
            "open": pa.array([r[1] for r in rows], pa.float64()),
            "high": pa.array([r[2] for r in rows], pa.float64()),
            "low": pa.array([r[3] for r in rows], pa.float64()),
            "close": pa.array([r[4] for r in rows], pa.float64()),
            "volume": pa.array([r[5] for r in rows], pa.int64()),
            "ingested_at": pa.array([now] * len(rows), pa.timestamp("us", tz="UTC")),
        }
    )
    connection.register("_fixture_rows", arrow_table)
    connection.execute(
        "INSERT INTO ohlcv_daily (instrument_token, trade_date, open, high, low, "
        "close, volume, adj_factor, source, ingested_at) "
        "SELECT instrument_token, trade_date, open, high, low, close, volume, "
        "1.0, 'CSV_FIXTURE', ingested_at FROM _fixture_rows"
    )
    connection.unregister("_fixture_rows")


def insert_index(
    connection: duckdb.DuckDBPyConnection,
    rows: list[tuple[date, float, float, float, float, int]],
    index_name: str = "NIFTY500",
) -> None:
    now = datetime.now(timezone.utc)
    connection.executemany(
        "INSERT INTO index_ohlcv_daily VALUES (?,?,?,?,?,?,?,'CSV_FIXTURE',?)",
        [(index_name, d, o, h, low, c, v, now) for d, o, h, low, c, v in rows],
    )


def mark_trading_days(connection: duckdb.DuckDBPyConnection, dates: list[date]) -> None:
    connection.executemany(
        "INSERT INTO trading_calendar VALUES (?,TRUE,NULL) ON CONFLICT DO NOTHING",
        [(d,) for d in dates],
    )


@pytest.fixture
def universe(conn):  # type: ignore[no-untyped-def]
    """Six symbols with distinct trend characters, plus the index."""
    dates = trading_days(SESSIONS)
    mark_trading_days(conn, dates)

    # A clean, steady advance — should rank best on momentum score.
    insert_symbol(conn, 1001, "CLEANUP", synth_series(dates, 100, 0.0018))
    # Same total drift, but choppy: lower R^2, so it must rank below CLEANUP.
    insert_symbol(conn, 1002, "CHOPPY", synth_series(dates, 100, 0.0018, wobble=0.012))
    # A downtrend. Starts high enough that its declining price still clears
    # the liquidity floor, so the test measures trend, not eligibility.
    insert_symbol(conn, 1003, "FALLER", synth_series(dates, 300, -0.0012))
    # Flat.
    insert_symbol(conn, 1004, "FLAT", synth_series(dates, 100, 0.0))
    # A strong advance ruined by a single 60% gap 30 sessions back.
    insert_symbol(
        conn, 1005, "GAPPER",
        synth_series(dates, 100, 0.0015, gap_at=SESSIONS - 30, gap_size=0.60),
    )
    # Thinly traded: below the liquidity floor, so ineligible.
    thin = [(d, o, h, low, c, 50) for d, o, h, low, c, _v in synth_series(dates, 12, 0.001)]
    insert_symbol(conn, 1006, "THIN", thin)

    insert_index(conn, synth_series(dates, 20000, 0.0006))
    return dates
