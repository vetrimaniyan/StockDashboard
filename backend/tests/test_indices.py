"""Median sufficiency for index valuations.

The rule these tests defend is FR-6.1's: too little history yields *null*, never
a number computed from whatever happens to be present. For a median over a
10-year window that is subtler than a row count, because a history can be long
and still be missing most of the window.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb

from alpha500.pipeline.indices import (
    sync_index_tiers,
    sync_index_valuations,
    valuation_summary,
)

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


# --- uneven sampling must not tilt the median ----------------------------


def test_a_densely_sampled_stretch_does_not_drag_the_median(conn):
    """The flaw the two-stage median exists to remove.

    Eight of these ten years sat at 20, and two at 40 — but the two are sampled
    every other day while the eight are sampled monthly, which is the shape the
    real history has, because it was accumulated by backfills of differing
    cadence. Counting readings, the 40s win four to one and a plain median
    returns 40. Counting months, the 20s hold 80% of the decade, which is what
    the decade actually did.
    """
    old_end = LATEST - timedelta(days=365 * 8)
    _seed(conn, "Nifty 50", LATEST - timedelta(days=365 * 10), old_end,
          every_days=2, pe=40.0)
    _seed(conn, "Nifty 50", old_end + timedelta(days=1), LATEST,
          every_days=30, pe=20.0)

    raw = conn.execute(
        "SELECT median(pe) FROM index_valuation_daily WHERE index_name = 'Nifty 50'"
    ).fetchone()[0]
    assert raw == 40.0, "fixture must reproduce the over-sampling, or it proves nothing"

    row = _row(conn, "Nifty 50")
    assert row["median_pe_10y"] == 20.0
    # Readings favour the dense stretch; months do not. Both are reported so
    # the difference is visible rather than buried in the estimator.
    assert row["sessions_10y"] > 2 * row["months_10y"]
    assert row["months_10y"] >= 100


def test_months_are_reported_alongside_the_session_count(conn):
    _seed(conn, "Nifty 50", LATEST - timedelta(days=365 * 11), LATEST, every_days=7)

    row = _row(conn, "Nifty 50")
    assert row["months_10y"] > row["months_7y"] > 0
    # Weekly sampling puts several readings in each month.
    assert row["sessions_10y"] > row["months_10y"]


def test_an_evenly_sampled_window_is_unchanged_by_the_two_stage_median(conn):
    """A uniform series must give the same answer either way, or the change
    would be trading one bias for another."""
    _seed(conn, "Nifty 50", LATEST - timedelta(days=365 * 11), LATEST, pe=25.0)

    assert _row(conn, "Nifty 50")["median_pe_10y"] == 25.0


# --- refetching a session already stored ---------------------------------


class _CountingSource:
    """Serves one row per session and records which sessions were asked for."""

    def __init__(self, pe: float) -> None:
        self.pe = pe
        self.asked: list[date] = []

    def get_index_tiers(self) -> dict[str, str]:
        return {}

    def get_index_valuations(self, on: date) -> list[dict]:
        self.asked.append(on)
        return [
            {
                "index_name": "Nifty 50",
                "close": 24000.0,
                "pe": self.pe,
                "pb": 3.0,
                "div_yield": 1.1,
            }
        ]


def _seed_calendar(conn, days: list[date]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO trading_calendar VALUES (?, TRUE, NULL)",
        [(d,) for d in days],
    )


def _pe_on(conn, day: date) -> float | None:
    return conn.execute(
        "SELECT pe FROM index_valuation_daily WHERE index_name = 'Nifty 50' "
        "AND trade_date = ?",
        [day],
    ).fetchone()[0]


def test_a_stored_session_is_not_refetched_by_default(conn):
    days = [date(2026, 8, 24), date(2026, 8, 25)]
    _seed_calendar(conn, days)

    first = _CountingSource(pe=20.0)
    sync_index_valuations(conn, first, days[0], days[-1], every=1)
    assert first.asked == days

    second = _CountingSource(pe=99.0)
    sync_index_valuations(conn, second, days[0], days[-1], every=1)
    assert second.asked == []


def test_force_refetches_and_overwrites_a_session_already_stored(conn):
    """Without this a bad fetch is permanent.

    A session stored with null or partial ratios is skipped by every later run
    precisely because it holds a row, so nothing short of a forced pass can
    repair it.
    """
    days = [date(2026, 8, 24), date(2026, 8, 25)]
    _seed_calendar(conn, days)

    sync_index_valuations(conn, _CountingSource(pe=20.0), days[0], days[-1], every=1)
    assert _pe_on(conn, days[1]) == 20.0

    repaired = _CountingSource(pe=22.5)
    written, _ = sync_index_valuations(
        conn, repaired, days[0], days[-1], every=1, force=True
    )

    assert repaired.asked == days
    assert written == 2
    # INSERT OR REPLACE, so the repair lands in place rather than duplicating.
    assert _pe_on(conn, days[1]) == 22.5
    assert conn.execute(
        "SELECT count(*) FROM index_valuation_daily WHERE index_name = 'Nifty 50'"
    ).fetchone()[0] == 2


# --- one index lagging must not blank its row ----------------------------


def test_an_index_a_session_behind_is_read_at_its_own_latest(conn):
    """The whole-row blanking this used to cause.

    Every index is published in one file, but one can lag — a late correction,
    or a session where NSE omits it. Anchoring on the newest date in the table
    then found no row for it and reported nulls across the board, with nothing
    to say the figures existed one session earlier.
    """
    behind = LATEST - timedelta(days=1)
    _seed(conn, "Nifty 50", LATEST - timedelta(days=365 * 11), LATEST, pe=25.0)
    _seed(conn, "Nifty 50", LATEST, LATEST, pe=25.0)
    # Smallcap stops one session short of the newest date in the table.
    _seed(conn, "Nifty Smallcap 250", LATEST - timedelta(days=365 * 11), behind, pe=30.0)
    _seed(conn, "Nifty Smallcap 250", behind, behind, pe=30.0)

    rows = {r["index_name"]: r
            for r in valuation_summary(conn, ["Nifty 50", "Nifty Smallcap 250"])}

    assert rows["Nifty 50"]["as_of"] == LATEST
    lagging = rows["Nifty Smallcap 250"]
    assert lagging["as_of"] == behind
    assert lagging["pe"] == 30.0
    assert lagging["median_pe_10y"] is not None


def test_an_explicit_as_of_still_pins_every_index_to_one_date(conn):
    """Reproducing a past session has to mean one date, not each index's own."""
    behind = LATEST - timedelta(days=1)
    _seed(conn, "Nifty 50", LATEST - timedelta(days=365 * 11), LATEST, pe=25.0)
    _seed(conn, "Nifty 50", LATEST, LATEST, pe=25.0)
    _seed(conn, "Nifty Smallcap 250", LATEST - timedelta(days=365 * 11), behind, pe=30.0)
    _seed(conn, "Nifty Smallcap 250", behind, behind, pe=30.0)

    rows = valuation_summary(
        conn, ["Nifty 50", "Nifty Smallcap 250"], as_of=LATEST
    )
    assert [r["as_of"] for r in rows] == [LATEST, LATEST]
    assert rows[1]["pe"] is None


def test_a_tracked_index_with_no_history_is_named_rather_than_dropped(conn):
    _seed(conn, "Nifty 50", LATEST - timedelta(days=365 * 11), LATEST, pe=25.0)
    _seed(conn, "Nifty 50", LATEST, LATEST, pe=25.0)

    rows = valuation_summary(conn, ["Nifty 50", "Nifty Microcap 250"])

    assert [r["index_name"] for r in rows] == ["Nifty 50", "Nifty Microcap 250"]
    missing = rows[1]
    assert missing["as_of"] is None
    assert missing["pe"] is None
    assert missing["months_10y"] == 0


# --- tier tagging reports what matched -----------------------------------


class _TierSource:
    def __init__(self, tiers: dict[str, str]) -> None:
        self._tiers = tiers

    def get_index_tiers(self) -> dict[str, str]:
        return self._tiers

    def get_index_valuations(self, on: date) -> list[dict]:
        return []


def test_tier_tagging_counts_rows_matched_not_symbols_listed(conn):
    """The count was fabricated: it tested the truthiness of the connection
    object, which is never false, so every listed symbol read as tagged.

    NSE currently publishes 251 rows in the 250-member smallcap file, so the
    lists genuinely do exceed the universe and the leftover is worth seeing.
    """
    conn.execute(
        "INSERT INTO instruments (instrument_token, tradingsymbol, name, series, "
        "exchange, industry, is_active) VALUES "
        "(1,'RELIANCE','Reliance','EQ','NSE','Energy',TRUE), "
        "(2,'INFY','Infosys','EQ','NSE','IT',TRUE)"
    )
    source = _TierSource(
        {"RELIANCE": "NIFTY50", "INFY": "NIFTY50", "NOTINUNIVERSE": "NIFTYSMALLCAP250"}
    )

    tagged, unmatched = sync_index_tiers(conn, source)

    assert (tagged, unmatched) == (2, 1)
    assert conn.execute(
        "SELECT count(*) FROM instruments WHERE index_tier = 'NIFTY50'"
    ).fetchone()[0] == 2


def test_tier_tagging_on_an_empty_list_reports_nothing_tagged(conn):
    assert sync_index_tiers(conn, _TierSource({})) == (0, 0)
