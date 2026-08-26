"""Corporate-action adjustment tests.

FR-3.2 makes the reconciliation a release gate (NFR-5.4). These tests cover
the logic; ``alpha500 reconcile`` runs the same assertion over real data.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from alpha500.pipeline.adjust import compute_adj_factors

EX_DATE = date(2023, 3, 2)
SPLIT_1_FOR_2 = [(EX_DATE, "SPLIT", 1.0, 2.0)]


def _dates(*days: tuple[int, int, int]):
    return np.array([date(*d) for d in days], dtype=object)


def test_raw_source_is_halved_before_the_ex_date():
    """An unadjusted print needs the correction applied to prior sessions.

    Without it the ex-date shows a spurious -50% return (FR-3.1).
    """
    trade_dates = _dates((2023, 3, 1), (2023, 3, 2), (2023, 3, 3))
    # A raw source reflects nothing beyond its own session.
    adjusted_through = trade_dates
    factors = compute_adj_factors(trade_dates, adjusted_through, SPLIT_1_FOR_2)
    assert factors.tolist() == pytest.approx([0.5, 1.0, 1.0])


def test_pre_adjusted_source_is_left_alone():
    """A back-adjusted feed already carries the split; applying it again doubles it.

    This is the 360ONE case: Yahoo's history is split-adjusted, and adjusting
    on top produced a +98.97% return on the ex-date.
    """
    trade_dates = _dates((2023, 3, 1), (2023, 3, 2), (2023, 3, 3))
    # Fetched long after the split, so the source already reflects it.
    adjusted_through = np.array([date(2026, 8, 25)] * 3, dtype=object)
    factors = compute_adj_factors(trade_dates, adjusted_through, SPLIT_1_FOR_2)
    assert factors.tolist() == pytest.approx([1.0, 1.0, 1.0])


def test_split_after_the_fetch_still_applies_to_a_pre_adjusted_source():
    """A back-adjusted feed is only current as of its fetch date.

    A split occurring after the rows were stored is not yet in them, so it
    must still be applied until the next refetch.
    """
    trade_dates = _dates((2023, 3, 1), (2023, 3, 2))
    adjusted_through = np.array([date(2023, 1, 1)] * 2, dtype=object)
    factors = compute_adj_factors(trade_dates, adjusted_through, SPLIT_1_FOR_2)
    assert factors[0] == pytest.approx(0.5)
    assert factors[1] == pytest.approx(1.0)


def test_multiple_events_compound():
    """A 1:2 then a 1:5 leaves the earliest prices at one tenth."""
    trade_dates = _dates((2020, 1, 1), (2023, 3, 2), (2024, 6, 2))
    actions = [
        (date(2023, 3, 2), "SPLIT", 1.0, 2.0),
        (date(2024, 6, 1), "BONUS", 1.0, 5.0),
    ]
    factors = compute_adj_factors(trade_dates, trade_dates, actions)
    assert factors[0] == pytest.approx(0.1)
    assert factors[1] == pytest.approx(0.2)
    assert factors[2] == pytest.approx(1.0)


def test_dividends_do_not_adjust_prices():
    """FR-3.4: splits and bonuses adjust the series, cash dividends do not.

    The operator trades price, and price-return momentum is the convention.
    """
    trade_dates = _dates((2023, 3, 1), (2023, 3, 3))
    actions = [(EX_DATE, "DIVIDEND", None, None)]
    factors = compute_adj_factors(trade_dates, trade_dates, actions)
    assert factors.tolist() == pytest.approx([1.0, 1.0])


def test_degenerate_ratios_are_ignored():
    """A 1:1 or zero ratio must not scale anything."""
    trade_dates = _dates((2023, 3, 1), (2023, 3, 3))
    for bad in ([(EX_DATE, "SPLIT", 1.0, 1.0)], [(EX_DATE, "SPLIT", 0.0, 2.0)],
                [(EX_DATE, "SPLIT", None, 2.0)]):
        factors = compute_adj_factors(trade_dates, trade_dates, bad)
        assert factors.tolist() == pytest.approx([1.0, 1.0])


def test_adjusted_return_across_split_stays_within_reconciliation_threshold():
    """The FR-3.2 assertion itself: no adjusted return exceeds +/-35% on an ex-date."""
    raw_close = np.array([440.0, 441.0, 220.5, 222.0])  # unadjusted 1:2 split
    trade_dates = _dates((2023, 2, 28), (2023, 3, 1), (2023, 3, 2), (2023, 3, 3))
    factors = compute_adj_factors(trade_dates, trade_dates, SPLIT_1_FOR_2)

    adjusted = raw_close * factors
    returns = adjusted[1:] / adjusted[:-1] - 1.0
    assert np.abs(returns).max() < 0.35
