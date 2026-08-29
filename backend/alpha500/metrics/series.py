"""Per-symbol (time-series) metrics.

Everything computable from one symbol's own history lives here. Anything
needing the rest of the universe — RS rating, momentum rank, composite
z-score — is cross-sectional and lives in :mod:`alpha500.metrics.cross_section`.

All inputs are adjusted prices (FR-3.3, section 5 preamble).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from alpha500.config import settings
from alpha500.metrics import kernels as k
from alpha500.metrics import periods as p

Floats = NDArray[np.float64]


@dataclass(slots=True)
class SeriesMetrics:
    """Column-oriented metric output for one symbol, aligned to ``trade_date``."""

    trade_date: NDArray[Any]
    close: Floats
    columns: dict[str, NDArray[Any]] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.trade_date.size)

    def tail(self, n: int = 1) -> dict[str, Any]:
        """The last ``n`` rows as plain Python values, for the latest-date write."""
        return {name: values[-n:] for name, values in self.columns.items()}


def compute_series_metrics(
    trade_date: NDArray[Any],
    open_: Floats,
    high: Floats,
    low: Floats,
    close: Floats,
    volume: Floats,
    delivery_pct: Floats | None = None,
) -> SeriesMetrics:
    n = close.size
    cols: dict[str, NDArray[Any]] = {}

    # --- returns (5.2) ---------------------------------------------------
    cols["ret_1d"] = k.shift_ratio(close, p.DAY)
    cols["ret_1w"] = k.shift_ratio(close, p.WEEK)
    cols["ret_2w"] = k.shift_ratio(close, p.TWO_WEEKS)
    cols["ret_3w"] = k.shift_ratio(close, p.THREE_WEEKS)
    cols["ret_1m"] = k.shift_ratio(close, p.MONTH)
    cols["ret_2m"] = k.shift_ratio(close, p.TWO_MONTHS)
    cols["ret_3m"] = k.shift_ratio(close, p.QUARTER)
    cols["ret_6m"] = k.shift_ratio(close, p.HALF_YEAR)
    cols["ret_9m"] = k.shift_ratio(close, p.NINE_MONTHS)
    cols["ret_12m"] = k.shift_ratio(close, p.YEAR)
    # FR-6.2: skips the most recent month; this is the return the composite uses.
    cols["ret_12m_1m"] = k.lagged_ratio(close, near=p.MONTH, far=p.YEAR)
    # FR-13.1: the return earned *across* the interval three-to-two months ago,
    # which is a different question from ret_2m's lookback to a single point.
    cols["ret_3m_2m"] = k.lagged_ratio(close, near=p.TWO_MONTHS, far=p.QUARTER)

    # --- moving averages (5.9) ------------------------------------------
    sma_20 = k.sma(close, 20)
    sma_50 = k.sma(close, 50)
    sma_100 = k.sma(close, 100)
    sma_150 = k.sma(close, 150)
    sma_200 = k.sma(close, 200)
    cols["sma_20"] = sma_20
    cols["sma_50"] = sma_50
    cols["sma_100"] = sma_100
    cols["sma_150"] = sma_150
    cols["sma_200"] = sma_200
    cols["ema_21"] = k.ema(close, 21)
    cols["ema_50"] = k.ema(close, 50)

    slope_1m = np.full(n, np.nan)
    if n > p.MONTH:
        prior = sma_200[:-p.MONTH]
        with np.errstate(divide="ignore", invalid="ignore"):
            slope_1m[p.MONTH:] = np.where(prior > 0, sma_200[p.MONTH:] / prior - 1.0, np.nan)
    cols["sma_200_slope_1m"] = slope_1m

    cols["ma_alignment"] = _bool(
        (close > sma_50) & (sma_50 > sma_100) & (sma_100 > sma_200),
        sma_50, sma_100, sma_200,
    )

    # --- 52-week (5.6) ---------------------------------------------------
    # FR-6.9: from intraday High/Low, not closes. Using closes understates the
    # true range and manufactures false breakout signals.
    high_52w = k.rolling_max(high, p.WEEKS_52)
    low_52w = k.rolling_min(low, p.WEEKS_52)
    cols["high_52w"] = high_52w
    cols["low_52w"] = low_52w
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["pct_from_52w_high"] = np.where(high_52w > 0, close / high_52w - 1.0, np.nan)
        cols["pct_above_52w_low"] = np.where(low_52w > 0, close / low_52w - 1.0, np.nan)
        span = high_52w - low_52w
        cols["range_position_52w"] = np.where(span > 0, (close - low_52w) / span, np.nan)
    cols["days_since_52w_high"] = k.sessions_since_rolling_max(high, p.WEEKS_52)

    # --- period high -----------------------------------------------------
    # The highest high in everything stored for this symbol, excluding today.
    # Deliberately NOT called an all-time high: depth is whatever was
    # backfilled (history_days says how much), so this is a true all-time
    # high only for symbols that listed inside the window. Naming it "period"
    # keeps the UI from claiming more than the data supports.
    high_period = k.prior_expanding_max(high)
    cols["high_period"] = high_period
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["pct_from_period_high"] = np.where(
            high_period > 0, close / high_period - 1.0, np.nan
        )

    # --- momentum score (5.4) -------------------------------------------
    lookback = settings.momentum_lookback
    slope, r2 = k.rolling_log_regression(close, lookback)
    with np.errstate(over="ignore", invalid="ignore"):
        annualised = np.expm1(slope * p.TRADING_DAYS_PER_YEAR)
    cols["exp_reg_slope_90"] = annualised
    cols["exp_reg_r2_90"] = r2

    # FR-6.6: a one-off gap means the advance is not a tradeable trend.
    ret_1d = cols["ret_1d"]
    max_abs_move = k.rolling_max(np.abs(np.nan_to_num(ret_1d, nan=0.0)), lookback)
    gap_disqualified = max_abs_move > settings.gap_disqualifier_pct
    cols["gap_disqualified"] = _bool(gap_disqualified, max_abs_move)

    score = annualised * r2
    cols["momentum_score"] = np.where(gap_disqualified, np.nan, score)

    # --- volatility (5.7) ------------------------------------------------
    tr = k.true_range(high, low, close)
    atr_14 = k.wilder_smooth(tr, 14)
    cols["atr_14"] = atr_14
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["atr_pct_14"] = np.where(close > 0, atr_14 / close, np.nan)

    with np.errstate(divide="ignore", invalid="ignore"):
        log_ret = np.full(n, np.nan)
        if n > 1:
            ratio = np.where(close[:-1] > 0, close[1:] / close[:-1], np.nan)
            log_ret[1:] = np.log(ratio)
        daily_range = np.where(low > 0, high / low - 1.0, np.nan)
    cols["stdev_21"] = k.rolling_std(log_ret, 21)
    cols["stdev_63"] = k.rolling_std(log_ret, 63)
    cols["adr_pct_20"] = k.sma(daily_range, 20)

    # --- volume (5.8) ----------------------------------------------------
    vol_sma_20 = k.sma(volume, 20)
    vol_sma_50 = k.sma(volume, 50)
    cols["vol_sma_20"] = vol_sma_20
    cols["vol_sma_50"] = vol_sma_50
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["rel_volume"] = np.where(vol_sma_50 > 0, volume / vol_sma_50, np.nan)
    cols["turnover_20d_median"] = k.rolling_median(close * volume, 20)
    cols["delivery_pct_sma_20"] = (
        k.sma(delivery_pct, 20) if delivery_pct is not None else np.full(n, np.nan)
    )

    # --- oscillators (5.11) ----------------------------------------------
    cols["rsi_14"] = k.rsi(close, 14)
    cols["adx_14"] = k.adx(high, low, close, 14)
    macd_line, macd_signal, macd_hist = k.macd(close)
    cols["macd"] = macd_line
    cols["macd_signal"] = macd_signal
    cols["macd_hist"] = macd_hist

    # --- patterns (5.10) -------------------------------------------------
    rel_volume = cols["rel_volume"]
    vol_confirmed = rel_volume >= settings.rel_volume_threshold

    prior_high_20 = _prior_rolling_max(high, 20)
    prior_high_50 = _prior_rolling_max(high, 50)
    cols["is_n_day_breakout_20"] = _bool(
        (close > prior_high_20) & vol_confirmed, prior_high_20, rel_volume
    )
    cols["is_n_day_breakout_50"] = _bool(
        (close > prior_high_50) & vol_confirmed, prior_high_50, rel_volume
    )

    prior_52w_high = np.full(n, np.nan)
    prior_52w_high[1:] = high_52w[:-1]
    cols["is_52w_high_breakout"] = _bool(
        (close > prior_52w_high) & vol_confirmed, prior_52w_high, rel_volume
    )

    in_base, depth, length, base_valid = _detect_base(high, low, atr_14, close)
    cols["is_in_base"] = _bool(in_base, np.where(base_valid, 1.0, np.nan))
    cols["base_depth_pct"] = depth
    cols["base_length_days"] = length

    # Criteria 1-7 of FR-6.12. Criterion 8 needs rs_rating and is applied
    # in the cross-sectional pass.
    cols["trend_template_partial"] = _trend_template_partial(
        close, sma_50, sma_150, sma_200, slope_1m, low_52w, high_52w
    )

    cols["history_days"] = np.arange(1, n + 1, dtype=np.float64)
    # Carried so the cross-sectional pass has the adjusted close to hand.
    # --- support and reversal (FR-14) ------------------------------------
    _support_and_reversal(
        cols, open_=open_, high=high, low=low, close=close,
        ema_21=cols["ema_21"], sma_50=sma_50, sma_200=sma_200,
        rsi_14=cols["rsi_14"], macd_hist=macd_hist, rel_volume=rel_volume,
    )

    cols["close_adj"] = close

    return SeriesMetrics(trade_date=trade_date, close=close, columns=cols)


def _support_and_reversal(
    cols: dict[str, NDArray[Any]],
    *,
    open_: Floats,
    high: Floats,
    low: Floats,
    close: Floats,
    ema_21: Floats,
    sma_50: Floats,
    sma_200: Floats,
    rsi_14: Floats,
    macd_hist: Floats,
    rel_volume: Floats,
) -> None:
    """Pullback to support with reversal confirmation (FR-14).

    Distinct from FR-6.15's ``is_pullback``, which is a *continuation* filter:
    it demands a perfect 8/8 trend template and a neutral RSI, and asks for no
    evidence the pullback has actually stopped. This asks the opposite question
    — price is at a level buyers previously defended, and something has turned.
    A stock can satisfy either without the other.
    """
    n = close.size

    swing = k.swing_lows(low, reach=3)
    support = k.nearest_support(
        close, [sma_50, ema_21], lookback=p.QUARTER, low=low, swing=swing
    )
    cols["support_level"] = support

    with np.errstate(divide="ignore", invalid="ignore"):
        distance = np.where(support > 0, close / support - 1.0, np.nan)
    cols["support_distance_pct"] = distance
    distance_known = np.isfinite(distance)
    at_support_flag = np.zeros(n, dtype=bool)
    np.less_equal(
        distance, settings.support_tolerance_pct,
        out=at_support_flag, where=distance_known,
    )
    cols["is_at_support"] = _tristate(distance_known, at_support_flag)

    # Pullback measured off the recent high, so a stock that never rose is not
    # counted as having pulled back from anything.
    recent_high = k.rolling_max(high, p.MONTH)
    with np.errstate(divide="ignore", invalid="ignore"):
        pullback = np.where(recent_high > 0, close / recent_high - 1.0, np.nan)
    cols["pullback_from_high_pct"] = pullback
    depth_ok = np.isfinite(pullback) & (
        (-pullback >= settings.pullback_min_pct) & (-pullback <= settings.pullback_max_pct)
    )

    # --- the five reversal checks (FR-14.4) ------------------------------
    def prev(values: Floats, lag: int = 1) -> Floats:
        out = np.full(n, np.nan)
        if n > lag:
            out[lag:] = values[:-lag]
        return out

    rsi_prev = prev(rsi_14)
    was_oversold = np.zeros(n, dtype=bool)
    for i in range(n):
        window = rsi_14[max(0, i - p.WEEK + 1) : i + 1]
        finite = window[np.isfinite(window)]
        was_oversold[i] = bool(finite.size and finite.min() <= 45.0)
    r1 = np.isfinite(rsi_14) & np.isfinite(rsi_prev) & (rsi_14 > rsi_prev) & was_oversold

    hist_1, hist_2 = prev(macd_hist), prev(macd_hist, 2)
    r2 = (
        np.isfinite(macd_hist) & np.isfinite(hist_1) & np.isfinite(hist_2)
        & (macd_hist > hist_1) & (hist_1 > hist_2)
    )

    ema_prev, close_prev = prev(ema_21), prev(close)
    r3 = (
        np.isfinite(close) & np.isfinite(ema_21) & np.isfinite(close_prev) & np.isfinite(ema_prev)
        & (close > ema_21) & (close_prev <= ema_prev)
    )

    span = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        close_position = np.where(span > 0, (close - low) / span, np.nan)
    r4 = np.isfinite(close_position) & (close > open_) & (close_position >= 0.66)

    r5 = (
        np.isfinite(rel_volume) & np.isfinite(close_prev)
        & (close > close_prev) & (rel_volume >= settings.reversal_volume_ratio)
    )

    score = (
        r1.astype(np.int64) + r2.astype(np.int64) + r3.astype(np.int64)
        + r4.astype(np.int64) + r5.astype(np.int64)
    )
    # The score needs a full RSI and MACD history to mean anything; before that
    # it is "not yet computable", not "no reversal" (FR-6.1).
    computable = np.isfinite(rsi_14) & np.isfinite(macd_hist) & np.isfinite(ema_21)
    cols["reversal_score"] = np.where(computable, score, np.nan)
    reversal_flag = score >= settings.reversal_min_score
    cols["is_reversal"] = _tristate(computable, reversal_flag)

    # FR-14.5: an uptrend must still be intact, or this is a falling knife
    # rather than a pullback. Long-only (FR-12.2) makes that asymmetry real.
    uptrend = np.isfinite(sma_200) & (close > sma_200)
    combined = at_support_flag & depth_ok & reversal_flag & uptrend
    cols["is_pullback_reversal"] = _tristate(computable & distance_known, combined)


def _bool(mask: NDArray[np.bool_], *inputs: Floats) -> NDArray[Any]:
    """Boolean column, null wherever its inputs were not yet computable.

    A metric that cannot be computed is null, never False (FR-6.1). Any
    comparison against nan yields False, so without this a symbol with 30
    sessions of history would report "not a breakout" in exactly the same way
    as one that genuinely failed the test — and a screen filtering on
    ``= False`` would silently scoop up every warm-up row.
    """
    out = np.empty(mask.shape, dtype=object)
    valid = np.ones(mask.shape, dtype=bool)
    for values in inputs:
        valid &= np.isfinite(values)
    out[valid] = mask[valid]
    out[~valid] = None
    return out


def _prior_rolling_max(high: Floats, window: int) -> Floats:
    """Rolling max of High over the N sessions *before* today.

    Today's own bar is excluded: a breakout is price clearing prior resistance,
    and including today would make every new high trivially true of itself.
    """
    n = high.size
    out = np.full(n, np.nan)
    rolled = k.rolling_max(high, window)
    out[1:] = rolled[:-1]
    return out


def _trend_template_partial(
    close: Floats,
    sma_50: Floats,
    sma_150: Floats,
    sma_200: Floats,
    sma_200_slope: Floats,
    low_52w: Floats,
    high_52w: Floats,
) -> Floats:
    """Score criteria 1-7 of the 8-criterion trend template (FR-6.12)."""
    with np.errstate(invalid="ignore"):
        checks = [
            (close > sma_150) & (close > sma_200),
            sma_150 > sma_200,
            sma_200_slope > 0,
            (sma_50 > sma_150) & (sma_50 > sma_200),
            close > sma_50,
            close >= 1.30 * low_52w,
            close >= 0.75 * high_52w,
        ]
    total = np.zeros(close.size, dtype=np.float64)
    for check in checks:
        total += np.where(check, 1.0, 0.0)

    # Null out rows where the longest input is not yet available, so an early
    # bar cannot score 3/8 purely because its long MAs are missing.
    total[~np.isfinite(sma_200)] = np.nan
    return total


def _detect_base(
    high: Floats, low: Floats, atr_14: Floats, close: Floats
) -> tuple[NDArray[np.bool_], Floats, Floats, NDArray[np.bool_]]:
    """Volatility-contraction base detection (FR-6.14, with D-8 amendment).

    Three conditions: a shallow trailing range, ATR contracted against the
    advance that preceded it, and that advance being at least 25%.

    FR-6.14 specifies the contraction test as ``ATR_14 today < 0.75 x ATR_14 at
    the start of the window``. Taken literally the reference slides forward
    with the window, so once a base is a full window old the test compares the
    quiet period against itself, the ratio drifts to 1, and the condition
    extinguishes itself. Measured across 142 RS>=70 symbols, the literal form
    never held for more than 7 consecutive sessions — which makes the
    ``base_length_days >= 10`` requirement of the Volatility Contraction preset
    (FR-7.5) unsatisfiable, and the screen returned nothing.

    The reference here is the peak ATR of the preceding quarter instead. A
    quarter is long enough that a consolidation cannot immediately drag its own
    reference down, so a base can run for weeks; it still decays once the quiet
    period fills the whole lookback, which is the right behaviour — a range
    that has lasted a full quarter is no longer a contraction against anything.
    Every constant the SRS specifies (0.75, 15%, 25%, 63 sessions) is kept.
    """
    n = close.size
    window = settings.base_window
    depth = np.full(n, np.nan)
    length = np.full(n, np.nan)
    in_base = np.zeros(n, dtype=bool)
    valid = np.zeros(n, dtype=bool)
    if window <= 0 or n < window:
        return in_base, depth, length, valid

    win_high = k.rolling_max(high, window)
    win_low = k.rolling_min(low, window)
    with np.errstate(divide="ignore", invalid="ignore"):
        depth = np.where(win_high > 0, (win_high - win_low) / win_high, np.nan)

    tight = np.nan_to_num(depth <= 0.15, nan=False).astype(bool)

    lead = window - 1
    first_computable = lead + p.QUARTER

    # Reference volatility: the peak ATR of the preceding quarter, excluding
    # today. A quarter is long enough that a short consolidation cannot
    # immediately drag its own reference down, unlike the one-window reference
    # the SRS specifies, which a base extinguishes within about seven sessions.
    #
    # Anchoring the reference at the start of a tight-range episode was tried
    # and rejected: a steady advance is only ~8% deep over 15 sessions, so it
    # already counts as "tight", episodes begin during the rally, and the test
    # degrades into "ATR is lower than it was a year ago".
    prior_atr = np.full(n, np.nan)
    prior_atr[1:] = atr_14[:-1]
    atr_reference = k.rolling_max(prior_atr, p.QUARTER)
    with np.errstate(invalid="ignore"):
        contracting = atr_14 < 0.75 * atr_reference

    # Prior advance of >= 25% within the 63 sessions preceding the window.
    #
    # Measured directionally, as the gain from the quarter's trough up to the
    # price entering the consolidation. The obvious formulation — the window's
    # max over its min — is symmetric and cannot tell a rally from a crash: a
    # stock that fell 25% and went quiet near its low scores identically to one
    # that rose 25% and paused near its high. That admitted dead stocks as
    # "bases" and was what the Volatility Contraction screen actually surfaced.
    run_low = k.rolling_min(close, p.QUARTER)
    advance = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(run_low > 0, close / run_low - 1.0, np.nan)
    if n > lead:
        advance[lead:] = ratio[: n - lead]
    prior_advance = np.nan_to_num(advance >= 0.25, nan=False).astype(bool)

    if n > first_computable:
        valid[first_computable:] = True
    valid &= np.isfinite(depth) & np.isfinite(atr_reference) & np.isfinite(advance)

    in_base = tight & contracting & prior_advance & valid

    # base_length_days: consecutive sessions the full condition has held.
    run = 0
    for i in range(n):
        if not valid[i]:
            run = 0
            continue
        run = run + 1 if in_base[i] else 0
        length[i] = float(run)

    return in_base, depth, length, valid


def _tristate(valid: NDArray[np.bool_], value: NDArray[np.bool_]) -> NDArray[Any]:
    """True / False / None, as an object array.

    FR-6.1 draws a hard line between "the condition does not hold" and "there
    is not enough history to say". A plain bool array cannot express the
    second, and defaulting it to False would quietly assert the first.
    """
    out = np.empty(value.size, dtype=object)
    for i in range(value.size):
        out[i] = bool(value[i]) if valid[i] else None
    return out
