"""Staleness reporting (FR-8.9).

Staleness has to be loud, but it also has to be *right*. A warning that fires
every trading morning by construction is one the operator stops reading, which
costs more than it saves.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from alpha500.api.main import IST, _expected_session
from tests.conftest import mark_trading_days

# Wed 26 Aug 2026 is a trading holiday (Id-E-Milad); the 29th/30th are a weekend.
SESSIONS = [date(2026, 8, 24), date(2026, 8, 25), date(2026, 8, 27), date(2026, 8, 28)]


@pytest.fixture
def calendar(conn):  # type: ignore[no-untyped-def]
    mark_trading_days(conn, SESSIONS)
    conn.executemany(
        "INSERT INTO trading_calendar VALUES (?,FALSE,?) ON CONFLICT DO NOTHING",
        [
            (date(2026, 8, 26), "Id-E-Milad"),
            (date(2026, 8, 29), "weekend"),
            (date(2026, 8, 30), "weekend"),
        ],
    )
    return conn


def at(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_before_the_publish_cutoff_todays_session_is_not_yet_expected(calendar):
    """At 06:30 on a trading day, today's EOD data cannot exist upstream.

    NSE finalises the bhavcopy after post-close processing, which is why the
    pipeline runs at 18:45 IST (FR-5.1).
    """
    assert _expected_session(calendar, at(2026, 8, 27, 6, 30)) == date(2026, 8, 25)


def test_after_the_publish_cutoff_todays_session_is_expected(calendar):
    assert _expected_session(calendar, at(2026, 8, 27, 19, 30)) == date(2026, 8, 27)


def test_a_holiday_is_skipped_rather_than_treated_as_missing(calendar):
    """FR-4.3: the calendar is authoritative, never the presence of data.

    26 Aug 2026 is Id-E-Milad. Inferring sessions from stored rows would make
    the holiday indistinguishable from a failed ingest.
    """
    # Late on the holiday itself, the last real session is still the 25th.
    assert _expected_session(calendar, at(2026, 8, 26, 23, 0)) == date(2026, 8, 25)


def test_weekend_falls_back_to_fridays_session(calendar):
    assert _expected_session(calendar, at(2026, 8, 29, 12, 0)) == date(2026, 8, 28)


def test_exactly_at_the_cutoff_counts_as_published(calendar):
    assert _expected_session(calendar, at(2026, 8, 27, 18, 45)) == date(2026, 8, 27)
