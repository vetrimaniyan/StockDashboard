"""Index size tiers and index valuation history.

Two related things NSE publishes that the universe sync alone does not capture:

* which size tier each NIFTY 500 constituent sits in — the index is exactly
  NIFTY 50 + NEXT 50 + MIDCAP 150 + SMALLCAP 250, so every symbol has one;
* the daily P/E, P/B and dividend yield of each index, which is what makes
  "is the midcap index expensive against its own history" answerable.

Median P/E over 7 and 10 years is computed from the stored history rather than
fetched, so it costs nothing to ask for and cannot disagree with the series it
claims to summarise.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Protocol, Sequence

import duckdb

TIER_LABELS: dict[str, str] = {
    "NIFTY50": "Nifty 50",
    "NIFTYNEXT50": "Next 50",
    "NIFTYMIDCAP150": "Midcap 150",
    "NIFTYSMALLCAP250": "Smallcap 250",
}

# The five indices the operator tracks. Microcap 250 sits outside the NIFTY 500
# (ranks 501-750), so it has no constituents here — only a valuation.
TRACKED_INDICES: tuple[str, ...] = (
    "Nifty 50",
    "Nifty Next 50",
    "Nifty Midcap 150",
    "Nifty Smallcap 250",
    "Nifty Microcap 250",
)


class _IndexSource(Protocol):
    def get_index_tiers(self) -> dict[str, str]: ...
    def get_index_valuations(self, on: date) -> list[dict[str, Any]]: ...


def sync_index_tiers(conn: duckdb.DuckDBPyConnection, provider: _IndexSource) -> int:
    """Record which size tier each constituent belongs to. Returns rows set."""
    tiers = provider.get_index_tiers()
    if not tiers:
        return 0

    updated = 0
    for symbol, tier in tiers.items():
        result = conn.execute(
            "UPDATE instruments SET index_tier = ? WHERE upper(tradingsymbol) = ?",
            [tier, symbol],
        )
        updated += 1 if result else 0
    return len(tiers)


def sync_index_valuations(
    conn: duckdb.DuckDBPyConnection,
    provider: _IndexSource,
    start: date,
    end: date,
    every: int = 5,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[int, int]:
    """Fetch index valuations across a date range, sampling every ``every``
    sessions.

    Returns (rows written, sessions with no file). A missing file is a holiday
    or an unpublished session, not a failure — the caller reports the count so
    a systematically empty range is still visible.

    Sampling is deliberate. NSE serves one file per session and each round trip
    costs seconds, so ten years daily is ~2 600 requests and several hours. The
    figure being derived is a *median* over thousands of observations, which
    weekly sampling estimates to well within its own noise. The latest session
    is always fetched regardless, so the *current* P/E is exact even though the
    history behind the median is sampled.
    """
    say = progress or (lambda _s, _i, _n: None)

    # Only ask for sessions the calendar calls trading days; the file does not
    # exist otherwise and every request would be a wasted round trip.
    sessions = [
        row[0]
        for row in conn.execute(
            "SELECT trade_date FROM trading_calendar "
            "WHERE is_trading_day AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [start, end],
        ).fetchall()
    ]
    have = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT trade_date FROM index_valuation_daily "
            "WHERE trade_date BETWEEN ? AND ?",
            [start, end],
        ).fetchall()
    }
    sampled = sessions[::max(every, 1)]
    # The most recent session carries the current P/E and is never sampled out.
    if sessions and sessions[-1] not in sampled:
        sampled.append(sessions[-1])
    todo = [s for s in sampled if s not in have]

    written = 0
    empty = 0
    stamp = datetime.now(timezone.utc)
    for position, session in enumerate(todo, start=1):
        say(session.isoformat(), position, len(todo))
        rows = provider.get_index_valuations(session)
        if not rows:
            empty += 1
            continue
        conn.executemany(
            "INSERT OR REPLACE INTO index_valuation_daily "
            "(index_name, trade_date, close, pe, pb, div_yield, ingested_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (
                    r["index_name"], session, r["close"], r["pe"], r["pb"],
                    r["div_yield"], stamp,
                )
                for r in rows
            ],
        )
        written += len(rows)
    return written, empty


def valuation_summary(
    conn: duckdb.DuckDBPyConnection,
    indices: Sequence[str] = TRACKED_INDICES,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Current P/E against its own 7- and 10-year medians.

    The medians come from stored history, so a short history yields a null
    median rather than one computed from whatever happens to be there — the
    same rule section 5 applies to every other metric.
    """
    newest = conn.execute(
        "SELECT max(trade_date) FROM index_valuation_daily"
    ).fetchone()
    latest = as_of or (newest[0] if newest else None)
    if latest is None:
        return []

    out: list[dict[str, Any]] = []
    for name in indices:
        row = conn.execute(
            "SELECT close, pe, pb, div_yield FROM index_valuation_daily "
            "WHERE index_name = ? AND trade_date = ?",
            [name, latest],
        ).fetchone()

        medians: dict[str, float | None] = {}
        coverage: dict[str, int] = {}
        for label, years in (("median_pe_7y", 7), ("median_pe_10y", 10)):
            since = latest - timedelta(days=365 * years)
            stats = conn.execute(
                "SELECT median(pe), count(pe), "
                "count(DISTINCT date_trunc('quarter', trade_date)) "
                "FROM index_valuation_daily "
                "WHERE index_name = ? AND pe IS NOT NULL "
                "AND trade_date BETWEEN ? AND ?",
                [name, since, latest],
            ).fetchone()

            # Sufficiency has to test *coverage across* the window, not its
            # extent. Checking only that the oldest point is old enough passes
            # a dataset clustered at the start: a part-loaded history once
            # reported a "10-year median" computed from its first four years,
            # and reported no 7-year median at all — a subset of the same
            # window — which is how the flaw surfaced.
            #
            # Counting observations is equally wrong, since it measures the
            # sampling cadence rather than the window. Counting populated
            # quarters measures neither, and a gap anywhere shows up.
            middle, observations, quarters = stats or (None, 0, 0)
            expected_quarters = years * 4
            sufficient = (
                middle is not None
                and quarters >= expected_quarters * 0.8
                and observations >= 40
            )
            medians[label] = float(middle) if sufficient else None
            coverage[label.replace("median_pe", "sessions")] = observations

        current = float(row[1]) if row and row[1] is not None else None
        out.append(
            {
                "index_name": name,
                "as_of": latest,
                "close": float(row[0]) if row and row[0] is not None else None,
                "pe": current,
                "pb": float(row[2]) if row and row[2] is not None else None,
                "div_yield": float(row[3]) if row and row[3] is not None else None,
                **medians,
                **coverage,
                # Positive means richer than its own history.
                "pe_vs_7y_pct": (
                    (current / medians["median_pe_7y"] - 1.0) * 100.0
                    if current and medians["median_pe_7y"]
                    else None
                ),
                "pe_vs_10y_pct": (
                    (current / medians["median_pe_10y"] - 1.0) * 100.0
                    if current and medians["median_pe_10y"]
                    else None
                ),
            }
        )
    return out
