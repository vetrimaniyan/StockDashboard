"""FR-18.3/18.4 — range, drawdown and the three-state trend.

The two named acceptance tests from the requirement are here verbatim, plus the
rules most likely to fail quietly: the current bar's exclusion from the peak,
and the refusal to compute a 52-week window over a sampled series.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from alpha500.pipeline.index_metrics import (
    DOWNTREND,
    MIN_TREND_SESSIONS,
    TRANSITIONAL,
    UPTREND,
    compute_index_metrics,
)
from alpha500.pipeline.index_universe import TrackedIndex

BANK = TrackedIndex("Nifty Bank", "SECTORAL")


def _sessions(count: int, end: date = date(2026, 9, 4)) -> list[date]:
    """`count` weekday sessions ending at `end`."""
    out: list[date] = []
    day = end
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day -= timedelta(days=1)
    return list(reversed(out))


def _store(conn, name: str, bars, basis: str = "OHLC") -> None:
    """bars: list of (date, high, low, close)."""
    stamp = datetime.now(timezone.utc)
    conn.executemany(
        "INSERT OR REPLACE INTO index_ohlcv_daily "
        "(index_name, trade_date, open, high, low, close, volume, source, ingested_at) "
        "VALUES (?,?,NULL,?,?,?,NULL,'TEST',?)",
        [(name, d, h, lo, c, stamp) for d, h, lo, c in bars],
    )
    conn.execute(
        "INSERT OR REPLACE INTO indices "
        "(index_name, category, first_session, last_session, sessions, ohlc_basis, "
        " source, refreshed_at) VALUES (?,?,?,?,?,?,'TEST',?)",
        [name, "SECTORAL", bars[0][0], bars[-1][0], len(bars), basis, stamp],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO trading_calendar VALUES (?, TRUE, NULL)",
        [(d,) for d, _, _, _ in bars],
    )


# --- FR-18.3 -------------------------------------------------------------


def test_index_range_and_drawdown_worked_example(conn):
    """The requirement's own numbers, computed rather than asserted.

    low_52w 40,000, high_52w 52,000, period high 55,000, close 46,000.
    """
    days = _sessions(WINDOW := 300)
    bars = []
    for i, day in enumerate(days):
        # The 55,000 peak sits outside the 52-week window, so it is a period
        # high the 52-week high cannot see - the case the view's track has to
        # stretch for, or the marker falls off the end.
        if i == 5:
            bars.append((day, 55_000.0, 54_000.0, 54_500.0))
        elif i == WINDOW - 200:
            bars.append((day, 52_000.0, 51_000.0, 51_500.0))
        elif i == WINDOW - 100:
            bars.append((day, 41_000.0, 40_000.0, 40_500.0))
        elif i == WINDOW - 1:
            bars.append((day, 46_500.0, 45_500.0, 46_000.0))
        else:
            bars.append((day, 47_000.0, 44_000.0, 45_500.0))
    _store(conn, BANK.name, bars)

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.available
    assert m.low_52w == 40_000.0
    assert m.high_52w == 52_000.0
    assert m.period_high == 55_000.0
    assert m.close == 46_000.0
    assert math.isclose(m.range_position_52w, 0.500, abs_tol=1e-9)
    assert math.isclose(m.pct_from_52w_high * 100, -11.538461, abs_tol=1e-4)
    assert math.isclose(m.pct_from_period_high * 100, -16.363636, abs_tol=1e-4)


def test_the_current_bar_is_excluded_from_the_period_high(conn):
    """FR-15.2's rule. Were today included, an index making a new high would
    read as 0% below its peak and be indistinguishable from one still climbing
    toward it."""
    days = _sessions(260)
    bars = [(d, 90.0, 88.0, 89.0) for d in days[:-2]]
    bars.append((days[-2], 100.0, 98.0, 99.0))      # the prior peak
    bars.append((days[-1], 200.0, 190.0, 195.0))    # a new high, today
    _store(conn, BANK.name, bars)

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.period_high == 100.0, "today's bar must not set the peak it is measured against"
    assert m.pct_from_period_high > 0, "above its prior peak, not level with it"
    assert m.sessions_since_period_high == 1


def test_a_new_52_week_high_reads_as_the_top_of_its_range(conn):
    """The 52-week window does include today - an index at a new 52-week high
    should read 1.0, which is the useful answer, not 'unavailable'."""
    days = _sessions(260)
    bars = [(d, 100.0, 90.0, 95.0) for d in days[:-1]]
    bars.append((days[-1], 120.0, 110.0, 120.0))
    _store(conn, BANK.name, bars)

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.high_52w == 120.0
    assert math.isclose(m.range_position_52w, 1.0, abs_tol=1e-9)


def test_a_short_series_reports_no_52_week_range(conn):
    days = _sessions(MIN_TREND_SESSIONS + 5)
    _store(conn, BANK.name, [(d, 100.0, 98.0, 99.0) for d in days])

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.high_52w is None and m.range_position_52w is None
    assert m.trend_state is not None, "a trend state needs less history than a year"


# --- FR-18.4 -------------------------------------------------------------


def _trending(days, start: float, drift: float):
    return [(d, start * (1 + drift) ** i * 1.005,
             start * (1 + drift) ** i * 0.995,
             start * (1 + drift) ** i) for i, d in enumerate(days)]


def test_trend_state_returns_transitional_when_neither_definition_holds(conn):
    """The requirement's named case: flat at the 200 SMA, slope inside +/-0.1%.

    Collapsing this into 'uptrend' because price sits a fraction above the line
    manufactures conviction the data does not contain.
    """
    days = _sessions(400)
    # A tiny oscillation around a level, so the 200 SMA is flat and price
    # crosses it constantly.
    bars = [(d, 100.0 + 0.2 * math.sin(i / 3.0) + 0.1,
             100.0 + 0.2 * math.sin(i / 3.0) - 0.1,
             100.0 + 0.2 * math.sin(i / 3.0)) for i, d in enumerate(days)]
    _store(conn, BANK.name, bars)

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.trend_state == TRANSITIONAL
    slope = m.sma_200 / 100.0 - 1.0
    assert abs(slope) < 0.001, "fixture must be flat, or it proves nothing"


def test_a_sustained_advance_classifies_as_uptrend(conn):
    days = _sessions(400)
    _store(conn, BANK.name, _trending(days, 100.0, 0.002))

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.trend_state == UPTREND
    assert m.close > m.sma_200 and m.sma_50 > m.sma_200
    assert m.sessions_in_state >= 1


def test_a_sustained_decline_classifies_as_downtrend(conn):
    days = _sessions(400)
    _store(conn, BANK.name, _trending(days, 100.0, -0.002))

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.trend_state == DOWNTREND
    assert m.close < m.sma_200 and m.sma_50 < m.sma_200


def test_sessions_in_state_counts_only_the_current_run(conn):
    """Three sessions into an uptrend must be distinguishable from eleven
    months into one."""
    days = _sessions(500)
    falling = _trending(days[:400], 100.0, -0.002)
    floor = falling[-1][3]
    rising = _trending(days[400:], floor, 0.02)
    _store(conn, BANK.name, falling + rising)

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.trend_state == UPTREND
    assert m.sessions_in_state < 100, "the earlier downtrend must not be counted"


def test_a_series_too_short_for_a_200_sma_has_no_trend_state(conn):
    days = _sessions(MIN_TREND_SESSIONS - 10)
    _store(conn, BANK.name, [(d, 100.0, 98.0, 99.0) for d in days])

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.trend_state is None
    assert "needs" in m.reason


# --- the gate ------------------------------------------------------------


def test_a_sampled_series_is_reported_unavailable_rather_than_computed(conn):
    """The six close-only indices. Every formula above would answer over a 5%
    sample, and every answer would span years while looking like a year."""
    # One reading a week over six years: 300 rows, and the last 252 of them
    # occupy nearly five years rather than one.
    end = date(2026, 9, 4)
    weekly = [end - timedelta(days=7 * i) for i in range(300)][::-1]
    _store(conn, BANK.name, [(d, 100.0, 98.0, 99.0) for d in weekly], basis="CLOSE")

    m = compute_index_metrics(conn, [BANK])[0]

    assert m.available is False
    assert m.high_52w is None and m.trend_state is None
    assert "span" in m.reason and "months" in m.reason


def test_an_index_with_no_series_says_so(conn):
    m = compute_index_metrics(conn, [BANK])[0]

    assert m.available is False
    assert "index-series" in m.reason


def test_no_metric_is_ever_named_all_time(conn):
    """D-11: no series reaches inception, so the peak is a period high and the
    field names must not invite the other reading."""
    days = _sessions(300)
    _store(conn, BANK.name, [(d, 100.0, 98.0, 99.0) for d in days])

    keys = compute_index_metrics(conn, [BANK])[0].as_dict().keys()

    assert not any("ath" in k or "all_time" in k for k in keys)
    assert "period_high" in keys
