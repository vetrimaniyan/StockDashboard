"""FR-17 — Fibonacci retracement zone metrics.

Locates the most recent completed impulse leg (swing low A to swing high B),
projects the standard retracement levels onto it, and describes where price
sits within them and whether volume and today's bar support a turn.

**What this is not.** Any advance that gives back a meaningful part of itself
passes through the 50% and 61.8% levels on the way down. Arriving in the zone
is arithmetic, not prediction — it says where price is, never where it is
going. Nothing here is called "support" for that reason (FR-17.9): a level is
"support" when buyers have actually appeared there, which is what FR-14's
``nearest_support`` measures from real swing lows. These are geometry. Same
spirit as FR-15.2 refusing to call the period high an all-time high.

**Point-in-time.** A swing is usable only from the session its confirming
window completes, never from the session the extreme printed (see
``k.swing_confirmation_index``). Everything here is computed from confirmed
swings only. Getting this wrong is silent: the screen still returns rows and a
backtest still produces a CAGR, one that could not have been earned.

Deeper is not stronger. A higher retracement ratio means more of the advance
has been given back — cheaper, not better — which is why the ratio carries no
weight in the FR-17.6 ranking.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from alpha500.config import settings
from alpha500.metrics import kernels as k

Floats = NDArray[np.float64]

RATIOS: Final[tuple[float, ...]] = (0.382, 0.500, 0.618, 0.786)

# Exclusion reasons (FR-17.8), in the order they are decided.
NO_VALID_LEG: Final = "NO_VALID_LEG"
LEG_BROKEN: Final = "LEG_BROKEN"
LEG_STALE: Final = "LEG_STALE"
OUT_OF_ZONE: Final = "OUT_OF_ZONE"
VOLUME_UNCONFIRMED: Final = "VOLUME_UNCONFIRMED"
NO_REVERSAL_BAR: Final = "NO_REVERSAL_BAR"
RR_BELOW_FLOOR: Final = "RR_BELOW_FLOOR"
INSUFFICIENT_HISTORY: Final = "INSUFFICIENT_HISTORY"
CA_UNRESOLVED: Final = "CA_UNRESOLVED"

TRADED_INTO: Final = "TRADED_INTO"
GAP_THROUGH: Final = "GAP_THROUGH"
RE_ENTERED: Final = "RE_ENTERED"

TRIGGERED: Final = "TRIGGERED"
ARMED: Final = "ARMED"
NONE: Final = "NONE"

# Minimum history: the shortest admissible leg plus the volume baseline that
# sits behind it. A long leg needs ~300.
MIN_SESSIONS: Final = 65

FIB_COLUMNS: Final[tuple[str, ...]] = (
    "fib_leg_low_date", "fib_leg_low_price", "fib_leg_high_date",
    "fib_leg_high_price", "fib_leg_confirmed_date", "fib_leg_amplitude_pct",
    "fib_leg_sessions", "fib_level_382", "fib_level_500", "fib_level_618",
    "fib_level_786", "fib_retracement_ratio", "fib_max_retracement",
    "in_fib_zone", "fib_sessions_in_zone", "fib_zone_status",
    "fib_zone_entry_type", "vol_impulse_ratio", "vol_dryup_ratio",
    "is_fib_reversal_bar", "fib_stop", "fib_target", "fib_reward_risk",
    "fib_exclusion_reason",
)


def _nan(n: int) -> Floats:
    out = np.empty(n, dtype=np.float64)
    out[:] = np.nan
    return out


def _window_mean(prefix: Floats, lo: NDArray[np.int64], hi: NDArray[np.int64]) -> Floats:
    """Mean of ``values[lo:hi+1]`` from a prefix sum. Sum *is* invertible."""
    count = hi - lo + 1
    total = prefix[hi + 1] - prefix[lo]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def _run_length(flag: NDArray[np.bool_]) -> Floats:
    """Length of the True run ending at each position. Zero where False.

    Vectorised: the run length is the distance since the last False, which is
    a cumulative maximum of the indices where the flag was False.
    """
    n = flag.size
    idx = np.arange(n)
    last_false = np.where(~flag, idx, -1)
    np.maximum.accumulate(last_false, out=last_false)
    return (idx - last_false).astype(np.float64) * flag


def compute_fib_metrics(
    trade_date: NDArray[Any],
    open_: Floats,
    high: Floats,
    low: Floats,
    close: Floats,
    volume: Floats,
    atr_14: Floats,
    rel_volume: Floats,
    ret_1d: Floats,
    adj_unresolved: bool = False,
) -> dict[str, NDArray[Any]]:
    """Every FR-17 column for one symbol, aligned to ``trade_date``."""
    n = close.size
    cols: dict[str, NDArray[Any]] = {}
    reason = np.full(n, INSUFFICIENT_HISTORY, dtype=object)

    def blank() -> dict[str, NDArray[Any]]:
        for name in FIB_COLUMNS:
            if name in ("fib_leg_low_date", "fib_leg_high_date", "fib_leg_confirmed_date"):
                cols[name] = np.full(n, None, dtype=object)
            elif name in ("in_fib_zone", "is_fib_reversal_bar"):
                cols[name] = np.zeros(n, dtype=bool)
            elif name == "fib_zone_status":
                cols[name] = np.full(n, NONE, dtype=object)
            elif name == "fib_zone_entry_type":
                cols[name] = np.full(n, None, dtype=object)
            elif name == "fib_exclusion_reason":
                cols[name] = reason
            else:
                cols[name] = _nan(n)
        return cols

    if n < MIN_SESSIONS:
        return blank()
    if adj_unresolved:
        reason[:] = CA_UNRESOLVED
        return blank()

    reach = settings.fib_swing_reach
    idx = np.arange(n)

    # --- anchors ---------------------------------------------------------
    sl_flag = k.swing_lows(low, reach)
    sh_flag = k.swing_highs(high, reach)
    sl_idx = np.flatnonzero(sl_flag)
    sh_idx = np.flatnonzero(sh_flag)
    if sl_idx.size == 0 or sh_idx.size == 0:
        reason[:] = NO_VALID_LEG
        return blank()

    high_tab = k.sparse_max_table(high)
    neg_low_tab = k.sparse_max_table(-low)
    abs_ret_tab = k.sparse_max_table(np.abs(np.nan_to_num(ret_1d, nan=0.0)))

    # For each confirmed swing high, the low the advance into it came *from*:
    # the deepest confirmed swing low within one maximum leg length behind it.
    # Not the nearest one — in a rising market that sits days before the high
    # and describes the last few bars of the advance rather than the advance.
    sl_price = low[sl_idx]
    within = (sl_idx[None, :] >= sh_idx[:, None] - settings.fib_max_leg_sessions) & (
        sl_idx[None, :] < sh_idx[:, None]
    )
    candidate_low = np.where(within, sl_price[None, :], np.inf)
    choice = np.argmin(candidate_low, axis=1)
    has_base = np.isfinite(candidate_low[np.arange(sh_idx.size), choice])
    base_for_high = sl_idx[choice]

    a_of = np.full(n, -1, dtype=np.int64)
    b_of = np.full(n, -1, dtype=np.int64)
    stale_only = np.zeros(n, dtype=bool)

    # Only swings whose confirming window has completed are visible at t, so
    # the newest usable extreme sits at t - reach.
    confirmed_count = np.searchsorted(sh_idx, idx - reach, side="right")

    for attempt in range(settings.fib_max_leg_attempts):
        todo = b_of < 0
        if not todo.any():
            break
        pos = confirmed_count - 1 - attempt
        cand = todo & (pos >= 0)
        if not cand.any():
            continue

        safe_pos = np.clip(pos, 0, sh_idx.size - 1)
        b = sh_idx[safe_pos]
        a = base_for_high[safe_pos]
        cand &= has_base[safe_pos]
        if not cand.any():
            continue

        amp_ok = np.zeros(n, dtype=bool)
        dur = b - a
        age = idx - b
        with np.errstate(divide="ignore", invalid="ignore"):
            amplitude = (high[b] - low[a]) / low[a]
        amp_ok = cand & np.isfinite(amplitude) & (amplitude >= settings.fib_min_amplitude)

        dur_ok = (dur >= settings.fib_min_leg_sessions) & (dur <= settings.fib_max_leg_sessions)
        age_ok = age <= settings.fib_max_leg_age
        # Max single-session move *within* the leg, i.e. over (A, B].
        shock = k.range_max(abs_ret_tab, np.minimum(a + 1, b), b)
        shock_ok = np.isfinite(shock) & (shock <= settings.fib_max_leg_shock)
        # B must still be the highest high all the way to today.
        peak = k.range_max(high_tab, a, idx)
        peak_ok = np.isfinite(peak) & (peak <= high[b] + 1e-12)

        ok = amp_ok & dur_ok & age_ok & shock_ok & peak_ok
        a_of = np.where(ok, a, a_of)
        b_of = np.where(ok, b, b_of)
        # Remember a leg that failed only because it has gone cold: that is a
        # different answer from "no leg was ever found".
        stale_only |= cand & amp_ok & dur_ok & shock_ok & peak_ok & ~age_ok

    found = b_of >= 0
    if not found.any():
        reason[:] = np.where(stale_only, LEG_STALE, NO_VALID_LEG)
        return blank()

    safe_a = np.clip(a_of, 0, n - 1)
    safe_b = np.clip(b_of, 0, n - 1)
    a_price = np.where(found, low[safe_a], np.nan)
    b_price = np.where(found, high[safe_b], np.nan)
    span = b_price - a_price

    cols["fib_leg_low_price"] = a_price
    cols["fib_leg_high_price"] = b_price
    cols["fib_leg_low_date"] = np.where(found, trade_date[safe_a], None)
    cols["fib_leg_high_date"] = np.where(found, trade_date[safe_b], None)
    # FR-17.1/FR-17.10: the session the leg actually became usable. The chart
    # marker and every backtest entry reference this, never the extreme date.
    confirm_idx = np.clip(k.swing_confirmation_index(safe_b, reach), 0, n - 1)
    cols["fib_leg_confirmed_date"] = np.where(found, trade_date[confirm_idx], None)
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["fib_leg_amplitude_pct"] = np.where(found, span / a_price, np.nan)
    cols["fib_leg_sessions"] = np.where(found, (b_of - a_of).astype(np.float64), np.nan)

    # --- levels and ratios (FR-17.2) -------------------------------------
    levels = {r: b_price - r * span for r in RATIOS}
    cols["fib_level_382"] = levels[0.382]
    cols["fib_level_500"] = levels[0.500]
    cols["fib_level_618"] = levels[0.618]
    cols["fib_level_786"] = levels[0.786]

    with np.errstate(divide="ignore", invalid="ignore"):
        cols["fib_retracement_ratio"] = np.where(span > 0, (b_price - close) / span, np.nan)
        # Deepest point reached since B. A leg wicked to 0.72 and recovered to
        # 0.55 has been tested; one that never traded past 0.55 has not.
        trough = -k.range_max(neg_low_tab, safe_b, idx)
        cols["fib_max_retracement"] = np.where(
            found & (span > 0), (b_price - trough) / span, np.nan
        )

    # --- zone membership (FR-17.3) ---------------------------------------
    # The 61.8% level is the LOWER price: deeper retracement, lower number.
    zone_low, zone_high = levels[0.618], levels[0.500]
    in_zone = found & np.isfinite(close) & (close >= zone_low) & (close <= zone_high)
    cols["in_fib_zone"] = in_zone
    cols["fib_sessions_in_zone"] = _run_length(in_zone)

    prev_low = np.concatenate(([np.nan], low[:-1]))
    gapped = found & (prev_low > zone_high) & (high < zone_low)
    prev_in = np.concatenate(([False], in_zone[:-1]))
    seen_before = np.concatenate(([0], np.cumsum(in_zone)[:-1])) > 0
    entry = np.full(n, None, dtype=object)
    entry[in_zone] = TRADED_INTO
    entry[in_zone & ~prev_in & seen_before] = RE_ENTERED
    entry[gapped] = GAP_THROUGH
    cols["fib_zone_entry_type"] = entry

    # --- volume shape (FR-17.4) ------------------------------------------
    vol = np.nan_to_num(volume, nan=0.0)
    vprefix = np.concatenate(([0.0], np.cumsum(vol)))
    base_lo = np.maximum(a_of - settings.fib_vol_baseline, 0)
    base_hi = np.maximum(a_of - 1, 0)
    pre = _window_mean(vprefix, np.clip(base_lo, 0, n - 1), np.clip(base_hi, 0, n - 1))
    leg = _window_mean(vprefix, safe_a, safe_b)
    post = _window_mean(vprefix, np.clip(safe_b + 1, 0, n - 1), idx)
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["vol_impulse_ratio"] = np.where(found & (pre > 0), leg / pre, np.nan)
        cols["vol_dryup_ratio"] = np.where(found & (leg > 0), post / leg, np.nan)

    # --- reversal bar (FR-17.5) ------------------------------------------
    bar_span = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        close_pos = np.where(bar_span > 0, (close - low) / bar_span, np.nan)
    reversal = (
        found
        & (close > open_)
        & (close_pos >= settings.fib_reversal_close_position)
        & (rel_volume >= settings.fib_reversal_rel_volume)
        & (low <= levels[0.500])
    )
    cols["is_fib_reversal_bar"] = np.nan_to_num(reversal, nan=False).astype(bool)

    # --- stop, target, reward:risk (FR-17.7) -----------------------------
    # The lowest confirmed swing low sitting inside the zone, if any. Only
    # swings confirmed by t count.
    in_zone_swing = _lowest_in_zone_swing(low, sl_flag, reach, zone_low, zone_high, safe_b)
    swing_stop = in_zone_swing - settings.fib_stop_atr_buffer * atr_14
    # `min` on purpose: the wider stop survives noise that the tighter one
    # would be shaken out by.
    stop = np.fmin(levels[0.786], swing_stop)
    stop = np.where(np.isnan(swing_stop), levels[0.786], stop)
    target = b_price
    with np.errstate(divide="ignore", invalid="ignore"):
        risk = close - stop
        rr = np.where(risk > 0, (target - close) / risk, np.nan)
    cols["fib_stop"] = np.where(found, stop, np.nan)
    cols["fib_target"] = target
    cols["fib_reward_risk"] = np.where(found, rr, np.nan)

    # --- status and exclusion (FR-17.3, FR-17.8) -------------------------
    vol_ok = (
        (cols["vol_impulse_ratio"] >= settings.fib_vol_impulse_min)
        & (cols["vol_dryup_ratio"] <= settings.fib_vol_dryup_max)
    )
    vol_ok = np.nan_to_num(vol_ok, nan=False).astype(bool)
    rr_ok = np.nan_to_num(cols["fib_reward_risk"] >= settings.fib_min_reward_risk, nan=False)
    bar_ok = cols["is_fib_reversal_bar"]
    broken = found & np.isfinite(close) & (close < a_price)

    status = np.full(n, NONE, dtype=object)
    status[in_zone & vol_ok & bar_ok & ~broken] = TRIGGERED
    status[in_zone & vol_ok & ~bar_ok & ~broken] = ARMED
    cols["fib_zone_status"] = status

    # First failing gate wins, so the reason names the nearest obstacle.
    reason = np.full(n, NO_VALID_LEG, dtype=object)
    reason[found] = OUT_OF_ZONE
    reason[found & stale_only & ~found] = LEG_STALE
    reason[in_zone] = VOLUME_UNCONFIRMED
    reason[in_zone & vol_ok] = NO_REVERSAL_BAR
    reason[in_zone & vol_ok & bar_ok] = RR_BELOW_FLOOR
    reason[in_zone & vol_ok & bar_ok & rr_ok] = None
    reason[broken] = LEG_BROKEN
    cols["fib_exclusion_reason"] = reason

    return cols


def _lowest_in_zone_swing(
    low: Floats,
    sl_flag: NDArray[np.bool_],
    reach: int,
    zone_low: Floats,
    zone_high: Floats,
    b_idx: NDArray[np.int64],
) -> Floats:
    """Lowest confirmed swing low lying inside the zone, per session.

    A swing low qualifies at session ``t`` when all three hold *at t*:

    * it is confirmed by then — the extreme printed at ``i`` is usable from
      ``i + reach``, never before (FR-17.1);
    * it printed at or after this session's B, so it belongs to the retracement
      being measured rather than to the advance into it;
    * its price lies inside *this session's* band.

    All three tests are evaluated per session, against the leg current at that
    session. A running minimum cannot express this. The band moves whenever the
    leg changes, so a swing that qualified under an earlier, lower leg is not a
    weaker candidate under the current one — it is not a candidate at all, and
    ``np.minimum.accumulate`` has no way to drop it once taken. That is not a
    tuning detail: carrying one forward put the stop a median 8.3 ATRs below
    level(0.786) and, in 92% of those rows, below the leg low A — a stop past
    the price at which ``LEG_BROKEN`` already declares the premise gone. It
    suppressed reward:risk enough that the FR-17.6 screen listed nothing on any
    session in four and a half years.

    So the candidates are tested as a session x swing matrix instead. There are
    O(n / reach) swings, so this is a few hundred columns, and it stays one
    array operation rather than a per-bar loop (D-10).
    """
    n = low.size
    src = np.flatnonzero(sl_flag)
    if src.size == 0:
        return np.full(n, np.nan)

    # Not clipped: a swing whose confirming window runs off the end of the
    # series never becomes usable, and clamping it to the last session would
    # hand today a swing that is still unconfirmed.
    conf = k.swing_confirmation_index(src, reach)
    price = low[src]
    idx = np.arange(n)

    eligible = (
        (conf[None, :] <= idx[:, None])            # confirmed by this session
        & (src[None, :] >= b_idx[:, None])         # printed at or after this B
        & (price[None, :] >= zone_low[:, None])    # inside this session's band
        & (price[None, :] <= zone_high[:, None])
    )
    # NaN bounds (no leg) compare False throughout, so those sessions fall out
    # here rather than needing a separate guard.
    lowest = np.where(eligible, price[None, :], np.inf).min(axis=1)
    return np.where(np.isfinite(lowest), lowest, np.nan)
