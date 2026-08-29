"""Hand-computed tests for every numerical primitive (NFR-5.1).

Each expected value below is derived by hand in the docstring or comment, not
read back from the implementation. A test that merely records current output
would pass through a metric bug unchanged (risk R-5).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from alpha500.metrics import kernels as k


def arr(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float64)


# --- returns -------------------------------------------------------------


def test_shift_ratio_one_period():
    """100 -> 110 is +10%; 110 -> 121 is +10%. First bar has no prior."""
    out = k.shift_ratio(arr(100, 110, 121), 1)
    assert math.isnan(out[0])
    assert out[1] == pytest.approx(0.10)
    assert out[2] == pytest.approx(0.10)


def test_shift_ratio_insufficient_history_is_null():
    """FR-6.1: never zero, never partially computed."""
    out = k.shift_ratio(arr(100, 110), 5)
    assert np.isnan(out).all()


def test_lagged_ratio_matches_ret_12m_1m_definition():
    """ret_12m_1m = C_21 / C_252 - 1, i.e. skip the most recent month.

    With near=1, far=3 on [10, 20, 30, 40]: at t=3 the value is
    C[3-1]/C[3-3] - 1 = 30/10 - 1 = 2.0.
    """
    out = k.lagged_ratio(arr(10, 20, 30, 40), near=1, far=3)
    assert np.isnan(out[:3]).all()
    assert out[3] == pytest.approx(2.0)


# --- moving averages -----------------------------------------------------


def test_sma_window_three():
    """mean(1,2,3)=2, mean(2,3,4)=3, mean(3,4,5)=4."""
    out = k.sma(arr(1, 2, 3, 4, 5), 3)
    assert np.isnan(out[:2]).all()
    assert out[2:].tolist() == pytest.approx([2.0, 3.0, 4.0])


def test_sma_propagates_nulls_instead_of_treating_them_as_zero():
    """A partially-null window is null, not a smaller average.

    Regression: an all-null delivery series once averaged to 0.0, which reads
    as a real measurement rather than missing data.
    """
    out = k.sma(arr(1, np.nan, 3, 4, 5), 3)
    assert math.isnan(out[2])
    assert math.isnan(out[3])
    assert out[4] == pytest.approx(4.0)


def test_sma_of_all_nulls_is_all_null():
    out = k.sma(arr(np.nan, np.nan, np.nan, np.nan), 2)
    assert np.isnan(out).all()


def test_ema_span_three_seeded_with_sma():
    """span=3 -> alpha=0.5, seeded with mean(1,2,3)=2.

    idx3 = 2 + 0.5*(4-2) = 3.0
    idx4 = 3 + 0.5*(5-3) = 4.0
    """
    out = k.ema(arr(1, 2, 3, 4, 5), 3)
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)
    assert out[4] == pytest.approx(4.0)


def test_wilder_smooth_seeds_with_simple_mean():
    """FR-6.10: alpha = 1/n, seeded with the simple mean of the first n.

    period=3 -> seed = mean(1,2,3) = 2
    idx3 = 2 + (4-2)/3       = 2.666666...
    idx4 = 2.6667 + (5-2.6667)/3 = 3.444444...
    """
    out = k.wilder_smooth(arr(1, 2, 3, 4, 5), 3)
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(8.0 / 3.0)
    assert out[4] == pytest.approx(31.0 / 9.0)


def test_wilder_differs_from_simple_mean():
    """The distinction is not cosmetic: ATR drives stop distance (FR-6.10)."""
    values = arr(*[float(i) for i in range(1, 21)])
    assert k.wilder_smooth(values, 14)[-1] != pytest.approx(k.sma(values, 14)[-1])


# --- rolling windows -----------------------------------------------------


def test_rolling_extremes_and_median():
    values = arr(5, 1, 4, 2, 3)
    assert k.rolling_max(values, 3)[2:].tolist() == pytest.approx([5, 4, 4])
    assert k.rolling_min(values, 3)[2:].tolist() == pytest.approx([1, 1, 2])
    assert k.rolling_median(values, 3)[2:].tolist() == pytest.approx([4, 2, 3])


def test_rolling_std_is_sample_not_population():
    """stdev_N is the sample standard deviation (ddof=1).

    For (1,2,3): mean 2, deviations -1,0,1, sum sq 2, /(3-1) = 1, sqrt = 1.
    Population sd would be sqrt(2/3) = 0.8165.
    """
    out = k.rolling_std(arr(1, 2, 3), 3)
    assert out[2] == pytest.approx(1.0)


def test_prior_expanding_max_excludes_the_current_bar():
    """Highs 10,12,11,15,13. Each bar sees only what came before it.

    idx0: nothing before      -> NaN
    idx1: max(10)             -> 10
    idx2: max(10,12)          -> 12
    idx3: max(10,12,11)       -> 12
    idx4: max(10,12,11,15)    -> 15

    idx4 is the case that matters: 15 was set on the previous bar, so a close
    of 13 must read as below the high, not at it.
    """
    out = k.prior_expanding_max(arr(10, 12, 11, 15, 13))
    assert math.isnan(out[0])
    assert out[1:].tolist() == pytest.approx([10, 12, 12, 15])


def test_prior_expanding_max_skips_nan_rather_than_propagating():
    """One missing session must not void every value after it.

    Highs 10,NaN,11,9: idx2 sees (10,NaN) -> 10, idx3 sees (10,NaN,11) -> 11.
    np.maximum would return NaN from idx2 onward, permanently.
    """
    out = k.prior_expanding_max(arr(10, float("nan"), 11, 9))
    assert math.isnan(out[0])
    assert out[1] == pytest.approx(10.0)
    assert out[2] == pytest.approx(10.0)
    assert out[3] == pytest.approx(11.0)


def test_prior_expanding_max_needs_a_prior_bar():
    """FR-6.1: a single bar has no history, so no high — never the bar itself."""
    assert np.isnan(k.prior_expanding_max(arr(10))).all()


def test_sessions_since_rolling_max():
    """0 means the window maximum is today's bar."""
    # Highs 1,5,2,3 with window 3: at idx2 window is (1,5,2), max at 1 back.
    out = k.sessions_since_rolling_max(arr(1, 5, 2, 3), 3)
    assert out[2] == pytest.approx(1.0)
    assert out[3] == pytest.approx(2.0)


def test_sessions_since_rolling_max_prefers_most_recent_tie():
    """AR-4: identical values must not be ordered arbitrarily."""
    out = k.sessions_since_rolling_max(arr(4, 4, 4), 3)
    assert out[2] == pytest.approx(0.0)


# --- exponential regression (FR-6.5) -------------------------------------


def test_log_regression_on_perfect_exponential():
    """A clean exponential fits exactly: R^2 = 1 and slope = ln(growth).

    close_t = 100 * 1.01^t  =>  ln(close) is linear with slope ln(1.01).
    """
    close = 100.0 * np.power(1.01, np.arange(30, dtype=np.float64))
    slope, r2 = k.rolling_log_regression(close, 30)
    assert slope[-1] == pytest.approx(math.log(1.01), rel=1e-9)
    assert r2[-1] == pytest.approx(1.0, abs=1e-9)


def test_log_regression_matches_numpy_polyfit():
    """Closed form must agree with an explicit fit on noisy data."""
    rng = np.random.default_rng(42)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 120)))
    window = 90
    slope, r2 = k.rolling_log_regression(close, window)

    y = np.log(close[-window:])
    x = np.arange(window, dtype=np.float64)
    expected_slope, intercept = np.polyfit(x, y, 1)
    residuals = y - (expected_slope * x + intercept)
    expected_r2 = 1.0 - residuals.var() / y.var()

    assert slope[-1] == pytest.approx(expected_slope, rel=1e-9)
    assert r2[-1] == pytest.approx(expected_r2, rel=1e-9)


def test_momentum_score_ordering_from_the_spec():
    """FR-6.5 states this ordering explicitly, and it is the point of R^2.

    60% annualised slope with R^2 0.35 scores 0.21;
    30% annualised slope with R^2 0.90 scores 0.27 — and ranks higher.
    """
    choppy = 0.60 * 0.35
    clean = 0.30 * 0.90
    assert choppy == pytest.approx(0.21)
    assert clean == pytest.approx(0.27)
    assert clean > choppy


# --- volatility ----------------------------------------------------------


def test_true_range_picks_the_largest_of_three():
    """TR = max(H-L, |H-C_prev|, |L-C_prev|).

    Bar 2: H=12, L=11, C_prev=5. H-L=1, |H-Cprev|=7, |L-Cprev|=6 -> 7.
    """
    high = arr(10, 12)
    low = arr(8, 11)
    close = arr(5, 11.5)
    out = k.true_range(high, low, close)
    assert out[0] == pytest.approx(2.0)  # first bar: H-L only
    assert out[1] == pytest.approx(7.0)


# --- oscillators (5.11) --------------------------------------------------

_WILDER_CLOSES = arr(
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
    45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
    46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45,
)


def test_rsi_first_value_hand_computed():
    """First RSI(14) on the reference series, derived by hand.

    The 14 changes from close[0] to close[14] are:
      -0.25 +0.06 -0.54 +0.72 +0.50 +0.27 +0.32
      +0.42 +0.24 -0.19 +0.14 -0.42 +0.67  0.00

    gains  = 0.06+0.72+0.50+0.27+0.32+0.42+0.24+0.14+0.67 = 3.34
    losses = 0.25+0.54+0.19+0.42                          = 1.40

    avg_gain = 3.34 / 14 = 0.2385714...
    avg_loss = 1.40 / 14 = 0.1
    RS       = 2.3857142...
    RSI      = 100 - 100/(1+RS) = 70.4641...

    (Secondary sources often quote 70.53 for "the" first RSI; that figure
    belongs to a differently-truncated series, not this one.)
    """
    out = k.rsi(_WILDER_CLOSES, 14)
    assert out[14] == pytest.approx(70.4641, abs=1e-4)


def test_rsi_all_gains_is_one_hundred():
    """No losses means avg_loss = 0, and RSI pins at 100 rather than dividing by zero."""
    out = k.rsi(arr(*[100.0 + i for i in range(30)]), 14)
    assert out[-1] == pytest.approx(100.0)


def test_macd_is_fast_ema_minus_slow_ema():
    close = arr(*[100.0 + math.sin(i / 3.0) * 5 for i in range(80)])
    line, signal, hist = k.macd(close)
    assert line[-1] == pytest.approx(k.ema(close, 12)[-1] - k.ema(close, 26)[-1])
    assert hist[-1] == pytest.approx(line[-1] - signal[-1])


def test_adx_stays_within_bounds_and_rises_in_a_trend():
    n = 60
    close = np.array([100.0 + i for i in range(n)], dtype=np.float64)
    high = close + 1.0
    low = close - 1.0
    out = k.adx(high, low, close, 14)
    finite = out[np.isfinite(out)]
    assert finite.size > 0
    assert (finite >= 0).all() and (finite <= 100).all()
    assert finite[-1] > 50  # a pure uptrend must register as strongly trending


# --- cross-sectional helpers (5.5) ---------------------------------------


def test_winsorise_clips_the_outlier():
    """FR-6.8: mandatory before z-scoring.

    One extreme value otherwise compresses the whole distribution.
    """
    values = arr(*([1.0] * 98 + [2.0, 1000.0]))
    out = k.winsorise(values)
    assert out.max() < 1000.0


def test_zscore_is_centred_and_unit_scaled():
    out = k.zscore(arr(1, 2, 3, 4, 5))
    assert out.mean() == pytest.approx(0.0, abs=1e-12)
    assert out.std(ddof=1) == pytest.approx(1.0)


def test_zscore_ignores_nulls():
    out = k.zscore(arr(1, 2, np.nan, 4, 5))
    assert math.isnan(out[2])
    assert np.isfinite(out[[0, 1, 3, 4]]).all()


def test_percentile_rank_bounds_and_ties():
    """Ties share a mid-rank so identical inputs cannot be ordered arbitrarily."""
    out = k.percentile_rank(arr(1, 2, 3, 4, 5))
    assert out[0] == pytest.approx(0.0)
    assert out[-1] == pytest.approx(1.0)

    tied = k.percentile_rank(arr(5, 5, 5, 5))
    assert np.allclose(tied, tied[0])


def test_dense_rank_desc_puts_strongest_first():
    """FR-6.7: 1 = strongest. Dense, so a tie does not skip the next rank."""
    out = k.dense_rank_desc(arr(0.5, 0.9, 0.9, 0.1))
    assert out.tolist() == pytest.approx([2.0, 1.0, 1.0, 3.0])


def test_dense_rank_desc_keeps_nulls_null():
    out = k.dense_rank_desc(arr(0.5, np.nan, 0.9))
    assert math.isnan(out[1])
    assert out[2] == pytest.approx(1.0)
