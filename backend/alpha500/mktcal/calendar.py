"""NSE trading calendar.

FR-4.3: a holiday calendar MUST be maintained. Inferring "the market was open"
from the presence of data is circular — a failed ingestion would then look
identical to a holiday, and the V8 gap check would never fire.

Seeded from NSE's published holiday master where reachable, and persisted, so
the calendar keeps working with the network down (NFR-2.3).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

import duckdb

from alpha500.providers.nse_http import NSE_HOME, NseSession

HOLIDAY_API = f"{NSE_HOME}/api/holiday-master?type=trading"


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def seed_from_nse(conn: duckdb.DuckDBPyConnection, session: NseSession | None = None) -> int:
    """Fetch and store the published trading-holiday list. Returns rows written."""
    session = session or NseSession()
    resp = session.get(HOLIDAY_API)
    payload = resp.json()

    holidays: list[tuple[date, str]] = []
    for _segment, entries in payload.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            raw = entry.get("tradingDate") or entry.get("trading_date")
            if not raw:
                continue
            for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
                try:
                    holidays.append(
                        (datetime.strptime(raw, fmt).date(), entry.get("description", ""))
                    )
                    break
                except ValueError:
                    continue

    if not holidays:
        return 0
    return mark_holidays(conn, holidays)


def mark_holidays(
    conn: duckdb.DuckDBPyConnection, holidays: Iterable[tuple[date, str]]
) -> int:
    rows = [(day, False, description) for day, description in holidays]
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO trading_calendar VALUES (?,?,?) "
        "ON CONFLICT (trade_date) DO UPDATE SET "
        "is_trading_day = excluded.is_trading_day, description = excluded.description",
        rows,
    )
    return len(rows)


def populate_weekdays(
    conn: duckdb.DuckDBPyConnection, start: date, end: date
) -> int:
    """Mark every weekday in range as a trading day unless already recorded.

    Holidays previously written by :func:`seed_from_nse` are left alone.
    """
    rows: list[tuple[date, bool, str | None]] = []
    day = start
    while day <= end:
        rows.append((day, not is_weekend(day), "weekend" if is_weekend(day) else None))
        day += timedelta(days=1)
    conn.executemany(
        "INSERT INTO trading_calendar VALUES (?,?,?) ON CONFLICT (trade_date) DO NOTHING",
        rows,
    )
    return len(rows)


def is_trading_day(conn: duckdb.DuckDBPyConnection, day: date) -> bool:
    row = conn.execute(
        "SELECT is_trading_day FROM trading_calendar WHERE trade_date = ?", [day]
    ).fetchone()
    if row is None:
        # Unknown date: fall back to the weekday rule rather than guessing from data.
        return not is_weekend(day)
    return bool(row[0])


def trading_days_between(
    conn: duckdb.DuckDBPyConnection, start: date, end: date
) -> list[date]:
    rows = conn.execute(
        """
        SELECT trade_date FROM trading_calendar
         WHERE trade_date BETWEEN ? AND ? AND is_trading_day
         ORDER BY trade_date
        """,
        [start, end],
    ).fetchall()
    if rows:
        return [r[0] for r in rows]
    out: list[date] = []
    day = start
    while day <= end:
        if not is_weekend(day):
            out.append(day)
        day += timedelta(days=1)
    return out


def previous_trading_day(conn: duckdb.DuckDBPyConnection, day: date) -> date:
    probe = day - timedelta(days=1)
    for _ in range(30):
        if is_trading_day(conn, probe):
            return probe
        probe -= timedelta(days=1)
    return probe
