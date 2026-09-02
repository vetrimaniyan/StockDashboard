"""Cover the historical materialiser, the path that silently emptied FR-17.

There was no test here at all, which is how this broke without anyone
noticing. ``alpha500 materialise`` crashed the moment FR-17 added the first
DATE-valued and staged TEXT-valued metrics: ``history._clean`` sent every
non-numeric column through ``float()``, and ``_cross_section_for_date`` read
them back into a float64 array. The nightly path (``engine._coerce``) handled
both correctly, so the dashboard looked fine while the metric history the
backtester reads went stale at the last successful run.

The failure was worse than a crash, because the crash comes *after*
``DELETE FROM metrics_daily``. Anyone who ran it and gave up was left with the
range removed and the Fibonacci screen matching nothing on any past date — a
backtest that reports 0.00% CAGR and no error, which reads as "the setup never
fired" rather than "the inputs are absent".

So the assertion that matters is not that materialise runs. It is that the
historical path and the nightly path produce the SAME row for the same
session. Anything else lets them drift apart again.
"""

from __future__ import annotations

from datetime import date

import pytest

from alpha500.metrics.engine import (
    _BOOL_COLUMNS,
    _DATE_COLUMNS,
    _TEXT_COLUMNS,
    METRIC_COLUMNS,
    compute_metrics_for_date,
)
from alpha500.metrics.history import materialise_history


def test_materialise_writes_every_session(conn, universe) -> None:
    dates = universe
    start, end = dates[-20], dates[-1]

    written = materialise_history(conn, start, end)
    assert written > 0

    sessions = conn.execute(
        "SELECT count(DISTINCT trade_date) FROM metrics_daily "
        "WHERE trade_date BETWEEN ? AND ?",
        [start, end],
    ).fetchone()
    assert sessions is not None and sessions[0] == 20


def test_fib_date_columns_survive_the_round_trip(conn, universe) -> None:
    """A DATE metric must come back as a date, not as NULL and not as NaN.

    ``float(datetime.date(...))`` raises, so before the fix this never reached
    an assertion — the materialiser died in pass 1.
    """
    dates = universe
    materialise_history(conn, dates[-5], dates[-1])

    typed = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'metrics_daily' AND column_name = 'fib_leg_confirmed_date'"
    ).fetchone()
    assert typed is not None and typed[0] == "DATE"

    rows = conn.execute(
        "SELECT fib_leg_low_date, fib_leg_high_date, fib_leg_confirmed_date "
        "FROM metrics_daily WHERE trade_date = ?",
        [dates[-1]],
    ).fetchall()
    assert rows
    for low_date, high_date, confirmed in rows:
        for value in (low_date, high_date, confirmed):
            assert value is None or isinstance(value, date)


def test_fib_text_columns_are_text_not_float(conn, universe) -> None:
    """FR-17.3/17.8 are string-valued and staged, unlike ``ineligible_reason``.

    Reading 'NONE' back into a float64 array is what took pass 2 down, and a
    string through the numeric formatter renders NaN — the FR-15.1 bug.
    """
    dates = universe
    materialise_history(conn, dates[-5], dates[-1])

    statuses = conn.execute(
        "SELECT DISTINCT fib_zone_status FROM metrics_daily WHERE trade_date = ?",
        [dates[-1]],
    ).fetchall()
    assert statuses
    values = {r[0] for r in statuses}
    assert values <= {"TRIGGERED", "ARMED", "NONE", None}
    assert values != {None}

    reasons = conn.execute(
        "SELECT DISTINCT fib_exclusion_reason FROM metrics_daily WHERE trade_date = ?",
        [dates[-1]],
    ).fetchall()
    assert any(isinstance(r[0], str) for r in reasons)


def test_historical_and_nightly_paths_agree(conn, universe) -> None:
    """The guard that keeps the two paths from drifting apart again.

    The nightly path computes one session and keeps the last row; the
    historical path stages every row and reads them back. They share
    ``compute_series_metrics`` and ``_finalise_cross_section``, so for the same
    session they must produce the same values — that is the whole claim
    AR-4 makes, and the only reason a backtest of a screen means anything.
    """
    dates = universe
    as_of = dates[-1]

    materialise_history(conn, as_of, as_of)
    historical = _rows_by_token(conn, as_of)

    conn.execute("DELETE FROM metrics_daily WHERE trade_date = ?", [as_of])
    compute_metrics_for_date(conn, as_of)
    nightly = _rows_by_token(conn, as_of)

    assert historical.keys() == nightly.keys()
    assert historical

    mismatches: list[str] = []
    for token, left in historical.items():
        right = nightly[token]
        for name in METRIC_COLUMNS:
            a, b = left[name], right[name]
            if a is None or b is None:
                if a is not b:
                    mismatches.append(f"{token}.{name}: {a!r} vs {b!r}")
                continue
            if name in _DATE_COLUMNS or name in _TEXT_COLUMNS or name in _BOOL_COLUMNS:
                if a != b:
                    mismatches.append(f"{token}.{name}: {a!r} vs {b!r}")
            elif abs(float(a) - float(b)) > 1e-9:
                mismatches.append(f"{token}.{name}: {a!r} vs {b!r}")

    assert not mismatches, "historical and nightly disagree:\n  " + "\n  ".join(
        mismatches[:20]
    )


def _rows_by_token(conn, as_of: date) -> dict[int, dict[str, object]]:
    columns = ", ".join(METRIC_COLUMNS)
    rows = conn.execute(
        f"SELECT instrument_token, {columns} FROM metrics_daily WHERE trade_date = ?",
        [as_of],
    ).fetchall()
    return {int(r[0]): dict(zip(METRIC_COLUMNS, r[1:])) for r in rows}
