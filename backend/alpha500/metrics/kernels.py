"""Numerical primitives for the metric engine.

Deliberately explicit rather than clever: every function here backs a formula
in SRS section 5 and must be checkable against a hand-computed value
(NFR-5.1). All are pure and deterministic (AR-4) — no wall-clock, no RNG.

Convention: input arrays are ordered oldest-first. Output arrays are the same
length, with ``nan`` wherever the window is not yet full. A metric with
insufficient history is null, never zero and never partially computed
(FR-6.1).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

Floats = NDArray[np.float64]


def _empty_like(n: int) -> Floats:
    return np.full(n, np.nan, dtype=np.float64)


def shift_ratio(values: Floats, periods: int) -> Floats:
    """``values[t] / values[t-periods] - 1`` — the return formula of FR-6.2."""
    n = values.size
    out = _empty_like(n)
    if periods <= 0 or periods >= n:
        return out
    prior = values[:-periods]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[periods:] = np.where(prior > 0, values[periods:] / prior - 1.0, np.nan)
    return out


def lagged_ratio(values: Floats, near: int, far: int) -> Floats:
    """``values[t-near] / values[t-far] - 1``.

    Backs ``ret_12m_1m`` = C21/C252 - 1, which skips the most recent month to
    keep short-horizon reversal out of the medium-term momentum signal.
    """
    n = values.size
    out = _empty_like(n)
    if far <= near or far >= n:
        return out
    numer = values[far - near : n - near]
    denom = values[: n - far]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[far:] = np.where(denom > 0, numer / denom - 1.0, np.nan)
    return out


def sma(values: Floats, window: int) -> Floats:
    """Simple moving average. Null if any value in the window is null.

    Nulls must propagate rather than be treated as zero: a symbol with no
    delivery data at all would otherwise report a delivery average of 0.0,
    which reads as a real measurement and would make every such stock look
    like it sits above its own average (FR-6.1, FR-2.7).
    """
    n = values.size
    out = _empty_like(n)
    if window <= 0 or window > n:
        return out
    finite = np.isfinite(values)
    filled = np.where(finite, values, 0.0)
    cumsum = np.concatenate(([0.0], np.cumsum(filled)))
    counts = np.concatenate(([0.0], np.cumsum(finite.astype(np.float64))))
    window_sum = cumsum[window:] - cumsum[:-window]
    window_count = counts[window:] - counts[:-window]
    out[window - 1 :] = np.where(window_count == window, window_sum / window, np.nan)
    return out


def ema(values: Floats, span: int) -> Floats:
    """Standard EMA, alpha = 2/(span+1), seeded with the SMA of the first span."""
    return _recursive_smooth(values, alpha=2.0 / (span + 1.0), seed_window=span)


def wilder_smooth(values: Floats, period: int) -> Floats:
    """Wilder's smoothing: ``X_t = (X_{t-1}*(n-1) + v_t) / n``.

    Equivalent to an EMA with alpha = 1/n. FR-6.10 requires this rather than a
    simple mean, and requires seeding with the simple mean of the first
    ``period`` values — ATR drives stop distance and position size, so the
    seeding convention is not cosmetic.
    """
    return _recursive_smooth(values, alpha=1.0 / period, seed_window=period)


def _recursive_smooth(values: Floats, alpha: float, seed_window: int) -> Floats:
    n = values.size
    out = _empty_like(n)
    if seed_window <= 0 or seed_window > n:
        return out

    # Seed from the first full window of *finite* values, not from index 0.
    # Chained smoothers feed each other — the MACD signal line is an EMA of the
    # MACD line, which is itself null until its slow EMA warms up — so seeding
    # blindly at the start yields nan for the entire output.
    finite = np.flatnonzero(np.isfinite(values))
    if finite.size < seed_window:
        return out
    first = int(finite[0])
    seed_end = first + seed_window
    if seed_end > n:
        return out

    seed = np.nanmean(values[first:seed_end])
    if not np.isfinite(seed):
        return out
    out[seed_end - 1] = seed
    prev = seed
    for i in range(seed_end, n):
        v = values[i]
        if not np.isfinite(v):
            out[i] = prev
            continue
        prev = prev + alpha * (v - prev)
        out[i] = prev
    return out


def rolling_max(values: Floats, window: int) -> Floats:
    return _rolling_extreme(values, window, np.max)


def rolling_min(values: Floats, window: int) -> Floats:
    return _rolling_extreme(values, window, np.min)


def _rolling_extreme(values: Floats, window: int, fn) -> Floats:  # type: ignore[no-untyped-def]
    n = values.size
    out = _empty_like(n)
    if window <= 0 or window > n:
        return out
    view = np.lib.stride_tricks.sliding_window_view(values, window)
    out[window - 1 :] = fn(view, axis=1)
    return out


def rolling_median(values: Floats, window: int) -> Floats:
    n = values.size
    out = _empty_like(n)
    if window <= 0 or window > n:
        return out
    view = np.lib.stride_tricks.sliding_window_view(values, window)
    out[window - 1 :] = np.median(view, axis=1)
    return out


def rolling_std(values: Floats, window: int, ddof: int = 1) -> Floats:
    """Sample standard deviation (ddof=1), matching ``stdev_N`` in FR-5.7."""
    n = values.size
    out = _empty_like(n)
    if window <= ddof or window > n:
        return out
    view = np.lib.stride_tricks.sliding_window_view(values, window)
    out[window - 1 :] = np.std(view, axis=1, ddof=ddof)
    return out


def sessions_since_rolling_max(values: Floats, window: int) -> NDArray[np.float64]:
    """Sessions elapsed since the rolling-window maximum was set.

    0 means the maximum is today's bar. Backs ``days_since_52w_high``.
    """
    n = values.size
    out = _empty_like(n)
    if window <= 0 or window > n:
        return out
    view = np.lib.stride_tricks.sliding_window_view(values, window)
    # Reverse each window so argmax finds the most recent occurrence of a tie.
    idx_from_end = np.argmax(view[:, ::-1], axis=1)
    out[window - 1 :] = idx_from_end.astype(np.float64)
    return out


def rolling_log_regression(close: Floats, window: int) -> tuple[Floats, Floats]:
    """OLS of ``ln(close)`` on session index over a rolling window (FR-6.5).

    Returns ``(slope_per_session, r_squared)``.

    Computed in closed form from rolling sums rather than by fitting each
    window: within a window the predictor is always 0..L-1, so
    ``sum(x*y)`` can be recovered from the plain rolling sums of ``y`` and
    ``t*y``. Exact, and linear in the number of sessions.
    """
    n = close.size
    slope = _empty_like(n)
    r2 = _empty_like(n)
    if window < 3 or window > n:
        return slope, r2

    with np.errstate(divide="ignore", invalid="ignore"):
        y = np.log(np.where(close > 0, close, np.nan))
    if not np.any(np.isfinite(y)):
        return slope, r2

    t = np.arange(n, dtype=np.float64)
    L = float(window)

    def _roll_sum(arr: Floats) -> Floats:
        cs = np.concatenate(([0.0], np.cumsum(arr)))
        return cs[window:] - cs[:-window]

    finite = np.isfinite(y)
    y_safe = np.where(finite, y, 0.0)
    valid_counts = _roll_sum(finite.astype(np.float64))

    s_y = _roll_sum(y_safe)
    s_yy = _roll_sum(y_safe * y_safe)
    s_ty = _roll_sum(t * y_safe)

    # Window starting index for each output position.
    start = np.arange(n - window + 1, dtype=np.float64)
    s_xy = s_ty - start * s_y

    sum_x = L * (L - 1.0) / 2.0
    sum_xx = (L - 1.0) * L * (2.0 * L - 1.0) / 6.0
    sxx_c = sum_xx - sum_x * sum_x / L

    with np.errstate(divide="ignore", invalid="ignore"):
        sxy_c = s_xy - sum_x * s_y / L
        syy_c = s_yy - s_y * s_y / L
        b = sxy_c / sxx_c
        r = np.where(syy_c > 0, (b * b) * sxx_c / syy_c, np.nan)

    complete = valid_counts == L
    slope[window - 1 :] = np.where(complete, b, np.nan)
    r2[window - 1 :] = np.where(complete, np.clip(r, 0.0, 1.0), np.nan)
    return slope, r2


def true_range(high: Floats, low: Floats, close: Floats) -> Floats:
    """``max(H-L, |H-C_prev|, |L-C_prev|)``. First bar has no prior close."""
    n = high.size
    out = _empty_like(n)
    if n == 0:
        return out
    prev = close[:-1]
    out[0] = high[0] - low[0]
    out[1:] = np.maximum.reduce(
        [high[1:] - low[1:], np.abs(high[1:] - prev), np.abs(low[1:] - prev)]
    )
    return out


def rsi(close: Floats, period: int = 14) -> Floats:
    """RSI with Wilder smoothing."""
    n = close.size
    out = _empty_like(n)
    if n <= period:
        return out
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    gain[0] = np.nan
    loss[0] = np.nan
    avg_gain = wilder_smooth(gain[1:], period)
    avg_loss = wilder_smooth(loss[1:], period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, np.inf)
        values = 100.0 - (100.0 / (1.0 + rs))
    values = np.where(avg_loss == 0, 100.0, values)
    values = np.where(np.isnan(avg_gain), np.nan, values)
    out[1:] = values
    return out


def adx(high: Floats, low: Floats, close: Floats, period: int = 14) -> Floats:
    """ADX(14) with Wilder smoothing throughout."""
    n = high.size
    out = _empty_like(n)
    if n <= 2 * period:
        return out

    up = np.diff(high)
    down = -np.diff(low)
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(high, low, close)[1:]

    atr_ = wilder_smooth(tr, period)
    plus_sm = wilder_smooth(plus_dm, period)
    minus_sm = wilder_smooth(minus_dm, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * np.where(atr_ > 0, plus_sm / atr_, np.nan)
        minus_di = 100.0 * np.where(atr_ > 0, minus_sm / atr_, np.nan)
        denom = plus_di + minus_di
        dx = 100.0 * np.where(denom > 0, np.abs(plus_di - minus_di) / denom, np.nan)

    out[1:] = wilder_smooth(dx, period)
    return out


def macd(
    close: Floats, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Floats, Floats, Floats]:
    """MACD(12, 26, 9) on EMAs. Returns ``(macd, signal, histogram)``."""
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def winsorise(values: Floats, lower_pct: float = 1.0, upper_pct: float = 99.0) -> Floats:
    """Clip to the given percentiles (FR-6.8).

    Mandatory before z-scoring: a single extreme outlier otherwise compresses
    the entire cross-sectional distribution into a narrow band.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return values.copy()
    lo, hi = np.percentile(finite, [lower_pct, upper_pct])
    return np.clip(values, lo, hi)


def zscore(values: Floats) -> Floats:
    """Cross-sectional z-score, ignoring nulls."""
    out = np.full_like(values, np.nan)
    finite = np.isfinite(values)
    if finite.sum() < 2:
        return out
    subset = values[finite]
    mean = subset.mean()
    std = subset.std(ddof=1)
    if std == 0 or not np.isfinite(std):
        out[finite] = 0.0
        return out
    out[finite] = (subset - mean) / std
    return out


def percentile_rank(values: Floats) -> Floats:
    """Fraction of the population each value strictly exceeds, in ``[0, 1]``.

    Ties share the mid-rank so that identical inputs cannot be ordered
    arbitrarily — a determinism requirement (AR-4), not a statistical nicety.
    """
    out = np.full_like(values, np.nan)
    finite = np.isfinite(values)
    count = int(finite.sum())
    if count == 0:
        return out
    if count == 1:
        out[finite] = 1.0
        return out

    subset = values[finite]
    order = np.argsort(subset, kind="stable")
    ranks = np.empty(count, dtype=np.float64)
    sorted_vals = subset[order]

    i = 0
    while i < count:
        j = i
        while j + 1 < count and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        # Mid-rank of the tie group, expressed as a 0-based average position.
        ranks[order[i : j + 1]] = (i + j) / 2.0
        i = j + 1

    out[finite] = ranks / (count - 1)
    return out


def dense_rank_desc(values: Floats) -> NDArray[np.float64]:
    """Dense rank, highest value = 1 (FR-6.7). Nulls stay null."""
    out = np.full(values.shape, np.nan, dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any():
        return out
    subset = values[finite]
    uniq = np.unique(subset)[::-1]
    lookup = {v: i + 1 for i, v in enumerate(uniq)}
    out[finite] = np.array([lookup[v] for v in subset], dtype=np.float64)
    return out
