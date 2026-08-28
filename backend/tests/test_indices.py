"""Median sufficiency for index valuations.

The rule these tests defend is FR-6.1's: too little history yields *null*, never
a number computed from whatever happens to be present. For a median over a
10-year window that is subtler than a row count, because a history can be long
and still be missing most of the window.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb

from alpha500.pipeline.indices import valuation_summary

LATEST = date(2026, 8, 25)


def _seed(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    first: date,
    last: date,
    every_days: int = 7,
    pe: float = 26.0,
) -> None:
    stamp = datetime.now(timezone.utc)
    rows = []
    day = first
    while day <= last:
        rows.append((name, day, 20000.0, pe, 3.5, 1.2, stamp))
        day += timedelta(days=every_days)
    conn.executemany(
        "INSERT OR REPLACE INTO index_valuation_daily VALUES (?,?,?,?,?,?,?)", rows
    )


def _row(conn: duckdb.DuckDBPyConnection, name: str) -> dict:
    return valuation_summary(conn, [name], as_of=LATEST)[0]


def test_history_clustered_at_the_start_of_the_window_yields_no_median(conn):
    """The flaw that shipped: 2016-2020 data reporting a "10-year median".

    Every observation is genuinely more than ten years old at its oldest, so a
    check on the *span* of the history passes. Only a check on coverage
    *across* the window rejects it.
    """
    _seed(conn, "Nifty 50", date(2016, 8, 30), date(2020, 12, 31))
    # A current reading, so the summary has something to compare against.
    _seed(conn, "Nifty 50", LATEST, LATEST, pe=20.57)

    row = _row(conn, "Nifty 50")
    assert row["pe"] == 20.57
    assert row["median_pe_10y"] is None
    assert row["pe_vs_10y_pct"] is None


def test_seven_year_median_is_never_absent_while_ten_year_is_present(conn):
    """7y is a subset of 10y, so this pairing is arithmetically impossible.

    It is also exactly how the flaw surfaced in the running dashboard, so the
    history here is shaped to force it: everything predates the 7-year window,
    leaving that window too thin to summarise while the 10-year one looks long
    enough to a check that only measures span.
    """
    _seed(conn, "Nifty 50", date(2016, 8, 30), date(2019, 12, 31))
    _seed(conn, "Nifty 50", LATEST, LATEST)

    row = _row(conn, "Nifty 50")
    assert row["median_pe_7y"] is None
    assert row["median_pe_10y"] is None


def test_full_coverage_yields_both_medians(conn):
    _seed(conn, "Nifty 50", LATEST - timedelta(days=365 * 11), LATEST, pe=25.0)
    _seed(conn, "Nifty 50", LATEST, LATEST, pe=20.0)

    row = _row(conn, "Nifty 50")
    assert row["median_pe_7y"] == 25.0
    assert row["median_pe_10y"] == 25.0
    # Positive means richer than its own history; 20 against 25 is cheaper.
    assert row["pe_vs_10y_pct"] < 0


def test_an_index_younger_than_the_window_reports_no_median(conn):
    """Microcap 250 launched in 2021 — its 10-year median cannot exist."""
    _seed(conn, "Nifty Microcap 250", date(2021, 5, 3), LATEST, pe=28.0)
    _seed(conn, "Nifty Microcap 250", LATEST, LATEST, pe=28.0)

    row = _row(conn, "Nifty Microcap 250")
    assert row["pe"] == 28.0
    assert row["median_pe_7y"] is None
    assert row["median_pe_10y"] is None


def test_sparse_sampling_across_a_covered_window_still_yields_a_median(conn):
    """Sufficiency must measure the window, not the sampling cadence.

    Monthly sampling over eleven years is ~130 observations — far fewer than
    daily, and no less able to support a median.
    """
    _seed(conn, "Nifty 50", LATEST - timedelta(days=365 * 11), LATEST, every_days=30)

    assert _row(conn, "Nifty 50")["median_pe_10y"] is not None
