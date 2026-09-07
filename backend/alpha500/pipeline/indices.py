"""Index size tiers and index valuation history.

Two related things NSE publishes that the universe sync alone does not capture:

* which size tier each NIFTY 500 constituent sits in — the index is exactly
  NIFTY 50 + NEXT 50 + MIDCAP 150 + SMALLCAP 250, so every symbol has one;
* the daily P/E, P/B and dividend yield of each index, which is what makes
  "is the midcap index expensive against its own history" answerable.

Median P/E over 7 and 10 years is computed from the stored history rather than
fetched, so it costs nothing to ask for and cannot disagree with the series it
claims to summarise. It is a median of monthly medians, because that history is
not sampled evenly and a raw median would report the sampling rather than the
period.
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


def sync_index_tiers(
    conn: duckdb.DuckDBPyConnection, provider: _IndexSource
) -> tuple[int, int]:
    """Record which size tier each constituent belongs to.

    Returns (symbols tagged, symbols listed that the universe does not hold).

    The second number is the one worth watching. The four tier lists should sum
    to the NIFTY 500 exactly, so a leftover means a list has drifted from the
    universe — NSE currently publishes 251 rows in the 250-member smallcap
    file, so there is always at least one.
    """
    tiers = provider.get_index_tiers()
    if not tiers:
        return 0, 0

    tagged = 0
    for symbol, tier in tiers.items():
        # DuckDB returns the number of rows the statement changed. The previous
        # count tested the truthiness of the connection object this returns,
        # which is never false, so it reported every symbol NSE listed as
        # though it had been tagged — including ones no instrument matches.
        changed = conn.execute(
            "UPDATE instruments SET index_tier = ? WHERE upper(tradingsymbol) = ?",
            [tier, symbol],
        ).fetchone()
        tagged += int(changed[0]) if changed else 0
    return tagged, len(tiers) - tagged


def sync_index_valuations(
    conn: duckdb.DuckDBPyConnection,
    provider: _IndexSource,
    start: date,
    end: date,
    every: int = 5,
    progress: Callable[[str, int, int], None] | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Fetch index valuations across a date range, sampling every ``every``
    sessions.

    Returns (rows written, sessions with no file). A missing file is a holiday
    or an unpublished session, not a failure — the caller reports the count so
    a systematically empty range is still visible.

    ``force`` refetches sampled sessions that are already stored. Without it a
    session is skipped once it holds *any* row, which makes a bad fetch
    permanent: a file that parsed partially, or one whose ratios all came back
    NULL because the header had drifted, is never revisited and no later run
    repairs it. The write is INSERT OR REPLACE, so a forced pass overwrites in
    place. It costs one request per sampled session — hours over ten years —
    which is why it is opt-in rather than the default.

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
    todo = sampled if force else [s for s in sampled if s not in have]

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

    Each median is taken over monthly medians rather than over the raw
    readings, so an unevenly sampled window still summarises the period rather
    than the sampling. See the comment at the query for why that matters here.
    """
    newest = conn.execute(
        "SELECT max(trade_date) FROM index_valuation_daily"
    ).fetchone()
    if as_of is None and not (newest and newest[0]):
        return []

    # Each index is read at its own most recent date, not at the newest date in
    # the table. They are published in one file, but one lagging index — a late
    # correction, a session where NSE omitted it — used to blank that index's
    # entire row: no P/E, no medians, no comparison, and nothing saying why. An
    # explicit as_of still pins every index to the same date, which is what
    # makes a summary reproducible for a past session.
    anchors: dict[str, date] = {}
    if as_of is None:
        anchors = {
            str(n): d
            for n, d in conn.execute(
                "SELECT index_name, max(trade_date) FROM index_valuation_daily "
                "GROUP BY index_name"
            ).fetchall()
        }

    out: list[dict[str, Any]] = []
    for name in indices:
        latest = as_of if as_of is not None else anchors.get(name)
        if latest is None:
            # Tracked but never fetched. Named with empty figures, so the panel
            # shows it is missing rather than dropping it silently.
            out.append({
                "index_name": name, "as_of": None, "close": None, "pe": None,
                "pb": None, "div_yield": None, "median_pe_7y": None,
                "median_pe_10y": None, "sessions_7y": 0, "sessions_10y": 0,
                "months_7y": 0, "months_10y": 0, "pe_vs_7y_pct": None,
                "pe_vs_10y_pct": None,
            })
            continue

        row = conn.execute(
            "SELECT close, pe, pb, div_yield FROM index_valuation_daily "
            "WHERE index_name = ? AND trade_date = ?",
            [name, latest],
        ).fetchone()

        medians: dict[str, float | None] = {}
        coverage: dict[str, int] = {}
        for label, years in (("median_pe_7y", 7), ("median_pe_10y", 10)):
            since = latest - timedelta(days=365 * years)
            # Median of monthly medians, not of the raw observations.
            #
            # A plain median assumes every point carries equal weight, which
            # holds only if the window is sampled evenly. This one is not: the
            # history was accumulated by backfills of differing cadence, so
            # some stretches hold several readings a week and others barely one
            # a month. A raw median over that is not the median of the decade,
            # it is the median of wherever the sampling happened to be dense —
            # and because the dense stretch here is the oldest, it dragged the
            # 10-year figure toward valuations from years ago and made the
            # index look cheaper against its history than it is.
            #
            # Collapsing each month to one value first gives every month equal
            # say regardless of how many readings back it. That is a property
            # of the estimator rather than of the data, so it holds for gaps
            # that appear later too.
            stats = conn.execute(
                "WITH obs AS ("
                "  SELECT trade_date, pe FROM index_valuation_daily "
                "  WHERE index_name = ? AND pe IS NOT NULL "
                "  AND trade_date BETWEEN ? AND ?"
                "), monthly AS ("
                "  SELECT date_trunc('month', trade_date) AS month, median(pe) AS pe "
                "  FROM obs GROUP BY 1"
                ") SELECT "
                "  (SELECT median(pe) FROM monthly), "
                "  (SELECT count(*) FROM obs), "
                "  (SELECT count(DISTINCT date_trunc('quarter', trade_date)) FROM obs), "
                "  (SELECT count(*) FROM monthly)",
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
            middle, observations, quarters, months = stats or (None, 0, 0, 0)
            expected_quarters = years * 4
            sufficient = (
                middle is not None
                and quarters >= expected_quarters * 0.8
                and observations >= 40
            )
            medians[label] = float(middle) if sufficient else None
            coverage[label.replace("median_pe", "sessions")] = observations
            # The count that now carries the weight, since months are what the
            # median is taken over. Reported so a thin window is visible rather
            # than inferred from the session count.
            coverage[label.replace("median_pe", "months")] = months

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
