"""FR-18.1/18.2 — the tracked universe and its two-source ingestion.

The rules under test are the ones that would fail quietly: an index served only
by close must not end up with a high, the peak must not be called an all-time
high without a documented inception behind it, and one vendor failure must not
take the other twenty-three series with it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from alpha500.pipeline.index_series import (
    CLOSE,
    CLOSE_SOURCE,
    OHLC,
    index_coverage,
    sync_index_series,
)
from alpha500.pipeline.index_universe import TRACKED, TrackedIndex, tracked_names
from alpha500.providers.models import Candle, ProviderError

START = date(2026, 8, 3)
END = date(2026, 8, 28)


class _FakeYahoo:
    """Serves OHLC, and can be told to fail for one index."""

    name = "YAHOO"

    def __init__(self, fail_for: str | None = None) -> None:
        self.fail_for = fail_for
        self.asked: list[str] = []

    def get_index_candles(self, index_name: str, start: date, end: date):
        self.asked.append(index_name)
        if index_name == self.fail_for:
            raise ProviderError(f"yahoo: no index candles for {index_name}")
        out, day, px = [], start, 100.0
        while day <= end:
            if day.weekday() < 5:
                out.append(Candle(
                    trade_date=day, open=px, high=px * 1.02,
                    low=px * 0.98, close=px, volume=0,
                ))
                px *= 1.001
            day += timedelta(days=1)
        return out


def _seed_valuations(conn, name: str, first: date, last: date) -> None:
    """The close-only source: what the FR-18 valuation sync already stores."""
    stamp = datetime.now(timezone.utc)
    rows, day, px = [], first, 500.0
    while day <= last:
        if day.weekday() < 5:
            rows.append((name, day, px, 20.0, 3.0, 1.1, stamp))
            px *= 1.002
        day += timedelta(days=1)
    conn.executemany(
        "INSERT OR REPLACE INTO index_valuation_daily VALUES (?,?,?,?,?,?,?)", rows
    )


# --- the universe --------------------------------------------------------


def test_the_tracked_universe_is_the_size_fr_18_1_specifies():
    assert 21 <= len(TRACKED) <= 27
    assert len(set(tracked_names())) == len(TRACKED), "duplicate index name"


def test_no_strategy_or_factor_index_is_tracked():
    """FR-18.1: a factor is not a sector, and ranking them together invites a
    rotation conclusion the data does not support."""
    banned = ("alpha", "quality", "low volatility", "equal weight", "value 20",
              "momentum 30", "growth sect")
    for name in tracked_names():
        assert not any(b in name.lower() for b in banned), name


def test_every_tracked_index_has_a_constituent_list_mapped():
    """An entry that cannot be fetched is worse than an entry that is missing."""
    from alpha500.providers.nse_archive import INDEX_CONSTITUENT_SLUGS

    missing = [n for n in tracked_names() if n not in INDEX_CONSTITUENT_SLUGS]
    assert not missing, f"no constituent slug for {missing}"


def test_no_index_claims_an_inception_without_one_recorded():
    """The hand-maintained field starts empty on purpose (D-11). This test is
    here so that filling one in is a deliberate act that has to update it."""
    assert all(i.documented_inception is None for i in TRACKED)


# --- ingestion -----------------------------------------------------------


def test_an_index_yahoo_serves_is_stored_with_real_highs(conn):
    bank = TrackedIndex("Nifty Bank", "SECTORAL")
    results = sync_index_series(conn, _FakeYahoo(), START, END, indices=[bank])

    assert results[0].ok
    assert results[0].basis == OHLC
    row = conn.execute(
        "SELECT high, low, close FROM index_ohlcv_daily WHERE index_name = 'Nifty Bank' "
        "ORDER BY trade_date LIMIT 1"
    ).fetchone()
    assert row[0] > row[2] > row[1]


def test_an_index_without_a_ticker_falls_back_to_close_and_stores_no_high(conn):
    """The landmine this avoids: repeating close into high would make a
    52-week 'high' answerable and wrong. NULL forces the reader to consult
    ohlc_basis instead of quietly getting a number.
    """
    defence = TrackedIndex("Nifty India Defence", "THEMATIC")
    _seed_valuations(conn, defence.name, START, END)
    yahoo = _FakeYahoo()

    results = sync_index_series(conn, yahoo, START, END, indices=[defence])

    assert defence.name not in yahoo.asked, "should not ask a vendor with no ticker"
    assert results[0].basis == CLOSE
    assert results[0].source == CLOSE_SOURCE
    assert results[0].rows > 0
    highs, closes = conn.execute(
        "SELECT count(high), count(close) FROM index_ohlcv_daily WHERE index_name = ?",
        [defence.name],
    ).fetchone()
    assert highs == 0
    assert closes > 0


def test_one_vendor_failure_leaves_the_other_series_intact(conn):
    """23 of 24 series is worth more than none."""
    a = TrackedIndex("Nifty Bank", "SECTORAL")
    b = TrackedIndex("Nifty IT", "SECTORAL")
    results = sync_index_series(
        conn, _FakeYahoo(fail_for="Nifty Bank"), START, END, indices=[a, b]
    )

    by_name = {r.index_name: r for r in results}
    assert not by_name["Nifty Bank"].ok
    assert "no index candles" in by_name["Nifty Bank"].error
    assert by_name["Nifty IT"].ok and by_name["Nifty IT"].rows > 0


def test_the_indices_row_reports_what_is_stored_not_what_was_sent(conn):
    bank = TrackedIndex("Nifty Bank", "SECTORAL")
    sync_index_series(conn, _FakeYahoo(), START, END, indices=[bank])

    first, last, sessions, basis = conn.execute(
        "SELECT first_session, last_session, sessions, ohlc_basis FROM indices "
        "WHERE index_name = 'Nifty Bank'"
    ).fetchone()
    stored = conn.execute(
        "SELECT count(*) FROM index_ohlcv_daily WHERE index_name = 'Nifty Bank'"
    ).fetchone()[0]
    assert sessions == stored
    assert first == date(2026, 8, 3) and last <= END
    assert basis == OHLC


def test_widening_the_table_leaves_the_benchmark_series_alone(conn):
    """Every reader of index_ohlcv_daily filters on index_name. This pins that
    the sector rows do not reach the NIFTY500 series they share a table with."""
    conn.execute(
        "INSERT INTO index_ohlcv_daily VALUES "
        "('NIFTY500', DATE '2026-08-03', 1.0, 1.0, 1.0, 1.0, 0, 'SEED', now())"
    )
    sync_index_series(
        conn, _FakeYahoo(), START, END,
        indices=[TrackedIndex("Nifty Bank", "SECTORAL")],
    )
    assert conn.execute(
        "SELECT count(*) FROM index_ohlcv_daily WHERE index_name = 'NIFTY500'"
    ).fetchone()[0] == 1


# --- the naming rule -----------------------------------------------------


def test_a_series_short_of_inception_reports_a_period_high_not_an_ath(conn):
    """FR-15.2's rule, applied to indices. Nifty Bank launched in 2003 and the
    deepest series obtainable starts in 2007, so calling it an ATH would be the
    same error the period high exists to prevent."""
    bank = TrackedIndex("Nifty Bank", "SECTORAL",
                        documented_inception=date(2003, 9, 12))
    sync_index_series(conn, _FakeYahoo(), START, END, indices=[bank])

    row = index_coverage(conn, [bank])[0]
    assert row["reaches_inception"] is False
    assert row["peak_metric"] == "period"


def test_an_unknown_inception_resolves_to_period_not_to_all_time(conn):
    """None means 'not established', and the conservative reading of that is
    the whole reason the field is hand-maintained."""
    bank = TrackedIndex("Nifty Bank", "SECTORAL", documented_inception=None)
    sync_index_series(conn, _FakeYahoo(), START, END, indices=[bank])

    row = index_coverage(conn, [bank])[0]
    assert row["documented_inception"] is None
    assert row["peak_metric"] == "period"


def test_a_series_reaching_inception_earns_the_ath_name(conn):
    bank = TrackedIndex("Nifty Bank", "SECTORAL",
                        documented_inception=date(2026, 8, 20))
    sync_index_series(conn, _FakeYahoo(), START, END, indices=[bank])

    row = index_coverage(conn, [bank])[0]
    assert row["reaches_inception"] is True
    assert row["peak_metric"] == "ath"


def test_coverage_names_every_tracked_index_even_before_ingestion(conn):
    rows = index_coverage(conn)
    assert [r["index_name"] for r in rows] == list(tracked_names())
    assert all(r["sessions"] == 0 and r["peak_metric"] == "period" for r in rows)


# --- density: a row count is not a series ---------------------------------


def _mark_trading_days(conn, first: date, last: date) -> None:
    days, day = [], first
    while day <= last:
        if day.weekday() < 5:
            days.append((day,))
        day += timedelta(days=1)
    conn.executemany(
        "INSERT OR REPLACE INTO trading_calendar VALUES (?, TRUE, NULL)", days
    )


def test_a_daily_series_is_reported_as_daily(conn):
    bank = TrackedIndex("Nifty Bank", "SECTORAL")
    _mark_trading_days(conn, START, END)
    sync_index_series(conn, _FakeYahoo(), START, END, indices=[bank])

    row = index_coverage(conn, [bank])[0]
    assert row["daily"] is True
    assert row["density"] > 0.95


def test_a_sampled_series_is_not_reported_as_daily(conn):
    """The close-only fallback inherits index_valuation_daily's sampling, which
    is weekly at best. FR-18.3's 252-session window and FR-18.4's SMA200 both
    assume daily bars; over a sparse series they would answer rather than fail,
    and the answer would span years. So density is measured, not assumed.
    """
    defence = TrackedIndex("Nifty India Defence", "THEMATIC")
    _mark_trading_days(conn, START, END)
    # One reading a week, as the real valuation history holds.
    stamp = datetime.now(timezone.utc)
    rows, day = [], START
    while day <= END:
        rows.append((defence.name, day, 500.0, 20.0, 3.0, 1.1, stamp))
        day += timedelta(days=7)
    conn.executemany(
        "INSERT OR REPLACE INTO index_valuation_daily VALUES (?,?,?,?,?,?,?)", rows
    )

    sync_index_series(conn, _FakeYahoo(), START, END, indices=[defence])
    row = index_coverage(conn, [defence])[0]

    assert row["sessions"] > 0, "the series exists"
    assert row["daily"] is False, "but it is not daily, and must not read as one"
    assert row["density"] < 0.4


def test_density_is_none_before_anything_is_ingested(conn):
    row = index_coverage(conn, [TrackedIndex("Nifty Bank", "SECTORAL")])[0]
    assert row["density"] is None
    assert row["daily"] is False


def test_density_never_exceeds_one_when_the_calendar_is_shallow(conn):
    """How the broken denominator was caught: the calendar is seeded around the
    present, so for a series older than it the row count of a partial calendar
    is smaller than the series itself and density read 125%.
    """
    bank = TrackedIndex("Nifty Bank", "SECTORAL")
    # A calendar covering only the tail of the series, as the real one does.
    _mark_trading_days(conn, END - timedelta(days=5), END)
    sync_index_series(conn, _FakeYahoo(), START, END, indices=[bank])

    row = index_coverage(conn, [bank])[0]
    assert row["density"] is not None
    assert row["density"] <= 1.0, f"density {row['density']} exceeds 100%"
    assert row["daily"] is True


def test_density_uses_the_calendar_when_it_spans_the_series(conn):
    """Holidays make the calendar the more accurate denominator where it
    reaches, so a series with a holiday in it still reads as fully daily."""
    bank = TrackedIndex("Nifty Bank", "SECTORAL")
    _mark_trading_days(conn, START, END)
    conn.execute(
        "INSERT OR REPLACE INTO trading_calendar VALUES (DATE '2026-08-17', FALSE, 'holiday')"
    )
    sync_index_series(conn, _FakeYahoo(), START, END, indices=[bank])
    conn.execute(
        "DELETE FROM index_ohlcv_daily WHERE index_name = 'Nifty Bank' "
        "AND trade_date = DATE '2026-08-17'"
    )
    sync_index_series(conn, _FakeYahoo(fail_for="Nifty Bank"), START, END, indices=[bank])

    row = index_coverage(conn, [bank])[0]
    assert row["density"] == 1.0
