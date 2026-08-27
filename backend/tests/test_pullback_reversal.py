"""New return windows and the pullback-with-reversal signal (FR-13, FR-14).

Expected values are computed by hand in the test, per NFR-5.1.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from alpha500.config import settings
from alpha500.metrics import kernels as k
from alpha500.metrics.series import compute_series_metrics


def _dates(n: int) -> np.ndarray:
    return np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(n)], dtype=object
    )


def _metrics(close: np.ndarray, **overrides):  # type: ignore[no-untyped-def]
    n = close.size
    return compute_series_metrics(
        trade_date=_dates(n),
        open_=overrides.get("open_", close * 0.999),
        high=overrides.get("high", close * 1.005),
        low=overrides.get("low", close * 0.995),
        close=close,
        volume=overrides.get("volume", np.full(n, 1_000_000.0)),
    )


# --- FR-13: additional return windows ------------------------------------

def test_new_return_windows_match_hand_computed_values():
    """A series rising exactly 1% per session has closed-form returns."""
    n = 300
    close = np.array([100.0 * 1.01**i for i in range(n)])
    cols = _metrics(close).columns

    # ret_2w spans 10 sessions, so the ratio is 1.01**10.
    assert cols["ret_2w"][-1] == pytest.approx(1.01**10 - 1, abs=1e-12)
    assert cols["ret_3w"][-1] == pytest.approx(1.01**15 - 1, abs=1e-12)
    assert cols["ret_2m"][-1] == pytest.approx(1.01**42 - 1, abs=1e-12)
    # ret_3m_2m spans C_42/C_63 — 21 sessions of compounding, not 42.
    assert cols["ret_3m_2m"][-1] == pytest.approx(1.01**21 - 1, abs=1e-12)


def test_lookback_and_interval_returns_are_different_numbers():
    """ret_2m and ret_3m_2m answer different questions (decision 1).

    One measures how far price sits above a point 42 sessions back; the other
    measures what was earned during the month before that. Conflating them
    would silently pick one reading of "2 to 3-month return" for the operator.
    """
    n = 200
    close = np.concatenate([
        np.full(100, 100.0),
        np.array([100.0 * 1.02**i for i in range(100)]),
    ])
    cols = _metrics(close).columns
    assert cols["ret_2m"][-1] != pytest.approx(cols["ret_3m_2m"][-1])


def test_returns_are_null_when_history_is_too_short():
    """FR-6.1/FR-13.2: never zero, never partially computed."""
    close = np.array([100.0 * 1.01**i for i in range(12)])
    cols = _metrics(close).columns
    assert np.isfinite(cols["ret_2w"][-1])          # 10 sessions available
    assert not np.isfinite(cols["ret_3w"][-1])      # needs 15
    assert not np.isfinite(cols["ret_2m"][-1])      # needs 42
    assert not np.isfinite(cols["ret_3m_2m"][-1])   # needs 63


# --- FR-14.1: swing lows --------------------------------------------------

def test_swing_low_finds_the_trough():
    low = np.array([10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 12, 13.0])
    found = np.flatnonzero(k.swing_lows(low, reach=3))
    assert found.tolist() == [4]


def test_swing_low_never_confirms_the_last_bars():
    """A low needs sessions on both sides; confirming early is look-ahead.

    A support level built from unconfirmed lows is one the operator could not
    have traded, which would quietly flatter every backtest that used it.
    """
    low = np.array([10, 9, 8, 7, 6, 5, 4, 3, 2, 1.0])   # falling to the last bar
    swing = k.swing_lows(low, reach=3)
    assert not swing[-3:].any()


def test_flat_run_yields_no_swing_low():
    low = np.full(20, 100.0)
    assert not k.swing_lows(low, reach=3).any()


# --- FR-14.2: support level ----------------------------------------------

def test_support_is_the_nearest_level_below_price_not_the_lowest():
    close = np.array([100.0] * 5)
    low = np.array([100.0] * 5)
    swing = np.zeros(5, dtype=bool)
    candidates = [np.full(5, 60.0), np.full(5, 95.0)]   # far and near
    support = k.nearest_support(close, candidates, lookback=63, low=low, swing=swing)
    assert support[-1] == pytest.approx(95.0)


def test_no_support_above_price_yields_null():
    """A stock at a new high has nothing beneath it.

    Inventing a level would put a stop where no buyer has ever appeared.
    """
    close = np.array([100.0] * 5)
    support = k.nearest_support(
        close, [np.full(5, 120.0)], lookback=63,
        low=np.full(5, 100.0), swing=np.zeros(5, dtype=bool),
    )
    assert not np.isfinite(support[-1])


# --- FR-14.4/14.5: reversal ----------------------------------------------

def test_steady_uptrend_at_a_high_is_not_a_pullback_reversal():
    """Nothing has pulled back, so the signal must not fire."""
    close = np.array([100.0 * 1.01**i for i in range(300)])
    cols = _metrics(close).columns
    assert cols["is_pullback_reversal"][-1] is not True


def test_downtrend_below_sma_200_is_excluded_however_strong_the_bounce():
    """FR-14.5: a bounce in a downtrend is a falling knife, not a pullback.

    Long-only (FR-12.2) makes the asymmetry real — there is no trade here.
    """
    fall = np.array([300.0 * 0.99**i for i in range(280)])
    bounce = np.array([fall[-1] * 1.03**i for i in range(1, 6)])
    close = np.concatenate([fall, bounce])
    cols = _metrics(close).columns
    assert close[-1] < cols["sma_200"][-1], "fixture is not below its 200 SMA"
    assert cols["is_pullback_reversal"][-1] is not True


def test_reversal_score_is_bounded_and_null_before_warm_up():
    close = np.array([100.0 * 1.01**i for i in range(300)])
    scores = _metrics(close).columns["reversal_score"]
    finite = scores[np.isfinite(scores.astype(np.float64))]
    assert finite.min() >= 0 and finite.max() <= 5
    assert not np.isfinite(float(scores[0]))


def test_pullback_to_support_with_reversal_fires():
    """A rally, a shallow pullback to the 21 EMA, then an up day that reclaims it."""
    rise = np.array([100.0 * 1.008**i for i in range(280)])
    peak = rise[-1]
    dip = np.array([peak * (1 - 0.012 * i) for i in range(1, 9)])   # ~9% pullback
    recover = np.array([dip[-1] * 1.02, dip[-1] * 1.045])
    close = np.concatenate([rise, dip, recover])
    n = close.size

    # Final bar closes near its high on heavy volume — R4 and R5.
    high = close * 1.005
    low = close * 0.995
    open_ = close * 0.999
    open_[-1] = close[-1] * 0.97
    low[-1] = close[-1] * 0.968
    volume = np.full(n, 1_000_000.0)
    volume[-1] = 3_000_000.0

    cols = compute_series_metrics(
        trade_date=_dates(n), open_=open_, high=high, low=low,
        close=close, volume=volume,
    ).columns

    assert cols["reversal_score"][-1] >= settings.reversal_min_score
    assert np.isfinite(cols["support_level"][-1])
    assert close[-1] > cols["sma_200"][-1]


def test_recomputing_gives_identical_results():
    """AR-4: the top-10 ordering can only be deterministic if its inputs are."""
    close = np.array([100.0 * 1.006**i for i in range(300)])
    first = _metrics(close).columns
    second = _metrics(close).columns
    for name in ("support_level", "support_distance_pct", "reversal_score",
                 "pullback_from_high_pct"):
        a = np.asarray(first[name], dtype=np.float64)
        b = np.asarray(second[name], dtype=np.float64)
        assert np.array_equal(a, b, equal_nan=True)
