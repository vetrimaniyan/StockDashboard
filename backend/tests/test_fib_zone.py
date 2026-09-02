"""Hand-computed tests for the FR-17 Fibonacci retracement zone (NFR-5.1).

Every expected value is derived in the docstring from the shared fixture, not
read back from the implementation. Fixture throughout:

    A = 400.00   B = 560.00   R = B - A = 160.00
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from alpha500.metrics import fib
from alpha500.metrics import kernels as k

A_PRICE = 400.00
B_PRICE = 560.00
R = 160.00

N_PRE, N_UP = 60, 40
A_IDX = N_PRE - 1
B_IDX = N_PRE + N_UP - 1


def build(
    tail_closes: list[float],
    *,
    tail_open: list[float] | None = None,
    tail_high: list[float] | None = None,
    tail_low: list[float] | None = None,
    turn_vol_last: float = 1.0,
    pre_vol: float = 100_000.0,
    leg_vol: float = 145_000.0,
    post_vol: float = 98_600.0,
    atr: float = 12.0,
):
    """A series with a clean 400 -> 560 impulse leg and a chosen retracement.

    The pre-leg wanders above 400 so the bar at ``A_IDX`` is a strict fractal
    minimum, and the leg peaks at ``B_IDX`` as a strict fractal maximum.
    """
    rng = np.random.default_rng(1)
    pre = 415 + rng.random(N_PRE) * 8
    up = np.linspace(402, 558, N_UP)
    close = np.concatenate([pre, up, np.asarray(tail_closes, dtype=float)])
    close[A_IDX] = 401.0
    close[B_IDX] = 558.0

    low = close - 1.0
    high = close + 1.0
    low[A_IDX] = A_PRICE
    high[B_IDX] = B_PRICE
    open_ = close - 0.5

    n = close.size
    tail = slice(B_IDX + 1, n)
    if tail_open is not None:
        open_[tail] = tail_open
    if tail_high is not None:
        high[tail] = tail_high
    if tail_low is not None:
        low[tail] = tail_low

    # Volume windows aligned exactly to the anchors: pre-leg is [A-50, A-1],
    # the leg is [A, B], the pullback is [B+1, today].
    volume = np.empty(n)
    volume[:A_IDX] = pre_vol
    volume[A_IDX : B_IDX + 1] = leg_vol
    volume[B_IDX + 1 :] = post_vol
    # Today's volume as a multiple of the pullback it is turning, which is what
    # the reversal bar now measures. The baseline excludes today, so this is
    # exactly fib_turn_vol_ratio on the last bar.
    volume[-1] = post_vol * turn_vol_last

    trade_date = np.array(
        [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(n)], dtype=object
    )
    ret_1d = np.concatenate([[np.nan], close[1:] / close[:-1] - 1.0])

    return fib.compute_fib_metrics(
        trade_date=trade_date,
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        atr_14=np.full(n, atr),
        ret_1d=ret_1d,
    )


# --- FR-17.2 levels and ratio --------------------------------------------


def test_fib_levels_and_ratio_worked_example():
    """R = 560 - 400 = 160. level(r) = B - r*R.

    0.382 -> 560 - 61.12 = 498.88
    0.500 -> 560 - 80.00 = 480.00
    0.618 -> 560 - 98.88 = 461.12
    0.786 -> 560 - 125.76 = 434.24

    Close 470.00 gives back 560 - 470 = 90, so 90/160 = 0.56250.
    """
    out = build([500.0, 490.0, 480.0, 475.0, 470.0])
    assert out["fib_leg_low_price"][-1] == pytest.approx(A_PRICE)
    assert out["fib_leg_high_price"][-1] == pytest.approx(B_PRICE)
    assert out["fib_level_382"][-1] == pytest.approx(498.88)
    assert out["fib_level_500"][-1] == pytest.approx(480.00)
    assert out["fib_level_618"][-1] == pytest.approx(461.12)
    assert out["fib_level_786"][-1] == pytest.approx(434.24)
    assert out["fib_retracement_ratio"][-1] == pytest.approx(0.56250)


def test_deeper_retracement_is_a_higher_ratio_not_a_stronger_signal():
    """FR-17.9: the ratio measures how much was given back, nothing more.

    470.00 -> 0.56250 and 465.00 -> 0.59375. The second is deeper, i.e.
    cheaper, and the score must not reward it (FR-17.6).
    """
    shallow = build([500.0, 490.0, 480.0, 475.0, 470.0])["fib_retracement_ratio"][-1]
    deep = build([500.0, 490.0, 480.0, 475.0, 465.0])["fib_retracement_ratio"][-1]
    assert shallow == pytest.approx(0.56250)
    assert deep == pytest.approx(0.59375)
    assert deep > shallow


# --- FR-17.3 zone membership ---------------------------------------------


@pytest.mark.parametrize(
    "close_px, ratio, inside",
    [
        (480.00, 0.50000, True),   # exactly the 50% level: inclusive
        (461.12, 0.61800, True),   # exactly the 61.8% level: inclusive
        (481.00, 0.49375, False),  # above the band
        (460.00, 0.62500, False),  # below the band
    ],
)
def test_fib_zone_boundaries_are_inclusive(close_px, ratio, inside):
    """The band runs from level(0.618) up to level(0.500).

    The 61.8% level is the LOWER price — a deeper retracement is a lower
    number. Written the intuitive way round the filter returns nothing.
    """
    out = build([500.0, 495.0, 490.0, 485.0, close_px])
    assert out["fib_retracement_ratio"][-1] == pytest.approx(ratio)
    assert bool(out["in_fib_zone"][-1]) is inside


def test_gap_through_the_band_is_not_an_entry():
    """From 485.00 (above the 480.00 level) to 455.00 in one session.

    The whole bar sits below level(0.618) = 461.12 while the prior bar sat
    entirely above level(0.500) = 480.00, so price never transacted in the
    band. That is a different event from trading down into it.
    """
    out = build(
        [500.0, 495.0, 490.0, 485.0, 455.0],
        tail_low=[499.0, 494.0, 489.0, 484.0, 452.0],
        tail_high=[501.0, 496.0, 491.0, 486.0, 458.0],
    )
    assert out["fib_zone_entry_type"][-1] == fib.GAP_THROUGH
    assert not bool(out["in_fib_zone"][-1])


def test_max_retracement_remembers_the_deepest_point():
    """Wicked to 455.00 then recovered to 470.00.

    fib_max_retracement uses the lowest Low since B: (560 - 452)/160 =
    0.67500, while the current ratio is (560 - 470)/160 = 0.56250. A leg
    that has been tested and held is not the same as one that never was.
    """
    out = build(
        [500.0, 490.0, 455.0, 465.0, 470.0],
        tail_low=[499.0, 489.0, 452.0, 464.0, 469.0],
    )
    assert out["fib_retracement_ratio"][-1] == pytest.approx(0.56250)
    assert out["fib_max_retracement"][-1] == pytest.approx(0.67500)


# --- FR-17.4 volume shape ------------------------------------------------


def test_fib_volume_shape_ratios():
    """Pre-leg mean 100000, leg mean 145000, pullback mean 98600.

    vol_impulse_ratio = 145000 / 100000 = 1.45  (the advance was confirmed)
    vol_dryup_ratio   =  98600 / 145000 = 0.68  (the pullback thinned)

    One "volume > 1.5x average" threshold cannot express this: in a
    retracement, elevated volume selects for distribution just as readily.
    """
    out = build([500.0, 490.0, 480.0, 475.0, 470.0])
    assert out["vol_impulse_ratio"][-1] == pytest.approx(1.45)
    assert out["vol_dryup_ratio"][-1] == pytest.approx(0.68)


def test_the_turn_bar_does_not_disqualify_itself_through_the_dryup_gate():
    """A heavy turn must not lift the pullback average that has to read thin.

    Pullback 98600 over the four sessions behind today; today 2x that, 197200.
    Averaged over [B+1, today] that is (4*98600 + 197200)/5 = 118320, so the
    dry-up ratio reads 118320/145000 = 0.816 and fails its own 0.80 gate. Over
    (B, today) it stays 98600/145000 = 0.68 and the bar is judged against a
    pullback it had no part in.
    """
    out = build(
        [500.0, 490.0, 480.0, 475.0, 470.0],
        tail_open=[499.0, 489.0, 479.0, 474.0, 462.0],
        tail_high=[501.0, 491.0, 481.0, 476.0, 472.0],
        tail_low=[499.0, 489.0, 479.0, 474.0, 460.0],
        turn_vol_last=2.0,
    )
    assert out["vol_dryup_ratio"][-1] == pytest.approx(0.68)
    assert out["fib_turn_vol_ratio"][-1] == pytest.approx(2.0)
    assert out["fib_zone_status"][-1] == fib.TRIGGERED


def test_turn_volume_is_measured_against_the_pullback_not_the_leg():
    """The baseline is the quiet pullback, never a window spanning the leg.

    Today is 148000 against a pullback of 98600, so turn volume is 1.50122 and
    the bar confirms. Against a 50-session mean carrying the 145000 leg it
    would read about 1.0 and fail — which is the volume the screen demands
    scaling with how heavy the advance was, for no stated reason.
    """
    out = build(
        [500.0, 490.0, 480.0, 475.0, 470.0],
        tail_open=[499.0, 489.0, 479.0, 474.0, 462.0],
        tail_high=[501.0, 491.0, 481.0, 476.0, 472.0],
        tail_low=[499.0, 489.0, 479.0, 474.0, 460.0],
        turn_vol_last=148_000.0 / 98_600.0,
    )
    assert out["fib_turn_vol_ratio"][-1] == pytest.approx(148_000 / 98_600)
    assert out["is_fib_reversal_bar"][-1]


def test_a_pullback_too_short_to_average_leaves_the_turn_unconfirmed():
    """Two sessions are not a baseline, and guessing is worse than a null.

    The tail here is three sessions, so today has two behind it - one short of
    the minimum - and the ratio is null rather than a comparison against noise.
    A null cannot clear the gate, so the bar stays unconfirmed.
    """
    out = build(
        [500.0, 480.0, 470.0],
        tail_open=[499.0, 479.0, 462.0],
        tail_high=[501.0, 481.0, 472.0],
        tail_low=[499.0, 479.0, 460.0],
        turn_vol_last=3.0,
    )
    assert np.isnan(out["fib_turn_vol_ratio"][-1])
    assert not out["is_fib_reversal_bar"][-1]


# --- FR-17.5 reversal bar ------------------------------------------------


def test_fib_reversal_bar_requires_close_in_upper_range():
    """O 462.00 H 472.00 L 460.00 C 470.00, turn volume 2.0.

    Close position = (470 - 460) / (472 - 460) = 10/12 = 0.83333, above the
    0.60 floor; close > open; today trades at 2.0x the four pullback sessions
    behind it; and the low 460.00 reached below level(0.500) = 480.00. Passes.
    """
    out = build(
        [500.0, 490.0, 480.0, 475.0, 470.0],
        tail_open=[499.0, 489.0, 479.0, 474.0, 462.0],
        tail_high=[501.0, 491.0, 481.0, 476.0, 472.0],
        tail_low=[499.0, 489.0, 479.0, 474.0, 460.0],
        turn_vol_last=2.0,
    )
    assert bool(out["is_fib_reversal_bar"][-1])


def test_fib_reversal_bar_rejects_a_weak_close():
    """Same bar closing at 465.00: (465 - 460)/12 = 0.41667, below 0.60.

    The range was travelled but not held, which is the distinction the close
    position exists to draw.
    """
    out = build(
        [500.0, 490.0, 480.0, 475.0, 465.0],
        tail_open=[499.0, 489.0, 479.0, 474.0, 462.0],
        tail_high=[501.0, 491.0, 481.0, 476.0, 472.0],
        tail_low=[499.0, 489.0, 479.0, 474.0, 460.0],
        turn_vol_last=2.0,
    )
    assert not bool(out["is_fib_reversal_bar"][-1])


def test_all_three_conditions_together_do_trigger():
    """Zone + volume shape + reversal bar is the only route to TRIGGERED.

    Guards against the opposite failure from the test below: a screen whose
    conditions can never all hold is indistinguishable from one that is
    merely quiet, and both show an empty grid.
    """
    out = build(
        [500.0, 490.0, 480.0, 475.0, 470.0],
        tail_open=[499.0, 489.0, 479.0, 474.0, 462.0],
        tail_high=[501.0, 491.0, 481.0, 476.0, 472.0],
        tail_low=[499.0, 489.0, 479.0, 474.0, 460.0],
        turn_vol_last=2.0,
    )
    assert bool(out["in_fib_zone"][-1])
    assert out["vol_impulse_ratio"][-1] == pytest.approx(1.45)
    assert out["vol_dryup_ratio"][-1] == pytest.approx(0.68)
    assert bool(out["is_fib_reversal_bar"][-1])
    assert out["fib_zone_status"][-1] == fib.TRIGGERED
    assert out["fib_exclusion_reason"][-1] is None


def test_zone_membership_alone_is_never_triggered():
    """FR-17.5: being in the band is a location, not an event.

    Without a reversal bar the status is ARMED at best. A screen that
    conflated the two would publish a standing list of stocks in decline.
    """
    out = build([500.0, 490.0, 480.0, 475.0, 470.0])
    assert bool(out["in_fib_zone"][-1])
    assert out["fib_zone_status"][-1] != fib.TRIGGERED


# --- FR-17.7 stop, target, reward:risk -----------------------------------


def test_fib_stop_takes_the_wider_of_two_candidates():
    """C_0 470.00, level(0.786) 434.24, in-zone swing low 460.00, ATR 12.00.

    Swing candidate = 460.00 - 0.5 * 12.00 = 454.00.
    min(434.24, 454.00) = 434.24 — the wider stop, deliberately, because it
    survives noise the tighter one would be shaken out by.

    risk   = 470.00 - 434.24 = 35.76  (7.61% of price)
    target = B = 560.00
    R:R    = (560.00 - 470.00) / 35.76 = 90 / 35.76 = 2.51678 -> clears 2.0
    """
    out = build(
        [500.0, 490.0, 460.0, 465.0, 470.0],
        tail_low=[499.0, 489.0, 460.0, 464.0, 469.0],
    )
    assert out["fib_stop"][-1] == pytest.approx(434.24)
    assert out["fib_target"][-1] == pytest.approx(560.00)
    assert (470.0 - out["fib_stop"][-1]) == pytest.approx(35.76)
    assert out["fib_reward_risk"][-1] == pytest.approx(2.51678, rel=1e-4)
    assert out["fib_reward_risk"][-1] >= 2.0


# --- FR-17.1 point-in-time ------------------------------------------------


def test_swing_anchor_is_not_available_before_confirmation():
    """A leg must never be visible before its swing high is confirmed.

    The fractal is centred, so a high printed at B is only knowable at
    B + reach. Reporting it earlier is look-ahead, and it is silent: the
    screen still returns rows and a backtest still produces a CAGR that
    could not have been earned.
    """
    out = build([500.0, 490.0, 480.0, 475.0, 470.0])
    reach = 3
    high_dates = out["fib_leg_high_date"]
    first = next(i for i, v in enumerate(high_dates) if v is not None)
    assert first >= B_IDX + reach, (
        f"leg surfaced at index {first}, before B ({B_IDX}) was confirmed "
        f"at {B_IDX + reach}"
    )


def test_confirmation_index_trails_the_extreme_by_reach():
    """The arithmetic the guarantee above rests on."""
    got = k.swing_confirmation_index(np.array([10, 40, 99]), reach=3)
    assert got.tolist() == [13, 43, 102]


def test_swing_highs_are_the_mirror_of_swing_lows():
    """One definition of a swing, used both ways (FR-17.1).

    Lows 5,1,4,2,3 inverted are highs -5,-1,-4,-2,-3; the detector must find
    the same bars.
    """
    values = np.array([9.0, 7.0, 3.0, 7.0, 9.0, 8.0, 10.0])
    lows = k.swing_lows(values, reach=3)
    highs = k.swing_highs(-values, reach=3)
    assert lows.tolist() == highs.tolist()


# --- FR-17.8 exclusion transparency ---------------------------------------


def test_short_history_is_named_not_silently_empty():
    """Fewer than 65 sessions cannot carry a leg plus its volume baseline."""
    n = 30
    flat = np.full(n, 100.0)
    out = fib.compute_fib_metrics(
        trade_date=np.array([dt.date(2024, 1, 1)] * n, dtype=object),
        open_=flat, high=flat + 1, low=flat - 1, close=flat,
        volume=np.full(n, 1000.0), atr_14=np.full(n, 1.0), ret_1d=np.zeros(n),
    )
    assert out["fib_exclusion_reason"][-1] == fib.INSUFFICIENT_HISTORY


def test_a_broken_leg_is_marked_rather_than_dropped():
    """Close below A means the premise is gone, and says so.

    FR-17.8: an absent row and a disqualified row are different answers.
    """
    out = build([480.0, 460.0, 440.0, 420.0, 395.0])
    assert out["fib_exclusion_reason"][-1] == fib.LEG_BROKEN
    assert out["fib_zone_status"][-1] == fib.NONE


def test_stop_reference_drops_a_swing_once_the_leg_moves_on():
    """A swing that was in zone under an earlier leg is not a candidate now.

    The band moves with the leg. Under leg 1 the zone is 8..12 and the swing
    at 10.0 is the stop reference; once leg 2 puts the zone at 100..120 the
    only valid reference is the swing at 110.0. Carrying 10.0 forward is not a
    conservative stop, it is a price from a different chart — and it is what
    put 92% of live stops below the leg low A, where LEG_BROKEN has already
    declared the premise gone.
    """
    n, reach = 200, 3
    low = np.full(n, 500.0)
    for offset in range(-reach, reach + 1):
        low[20 + offset] = 10.0 + abs(offset)
        low[120 + offset] = 110.0 + abs(offset)

    sl_flag = np.zeros(n, dtype=bool)
    sl_flag[[20, 120]] = True

    session = np.arange(n)
    zone_low = np.where(session < 100, 8.0, 100.0)
    zone_high = np.where(session < 100, 12.0, 120.0)
    b_idx = np.where(session < 100, 15, 100).astype(np.int64)

    out = fib._lowest_in_zone_swing(low, sl_flag, reach, zone_low, zone_high, b_idx)

    assert out[30] == pytest.approx(10.0)
    assert out[99] == pytest.approx(10.0)
    assert out[130] == pytest.approx(110.0)
    assert out[199] == pytest.approx(110.0)


def test_stop_reference_is_never_outside_the_band_it_searches():
    """Whatever comes back must be inside that session's own zone."""
    n, reach = 200, 3
    low = np.full(n, 500.0)
    for offset in range(-reach, reach + 1):
        low[20 + offset] = 10.0 + abs(offset)
        low[120 + offset] = 110.0 + abs(offset)
    sl_flag = np.zeros(n, dtype=bool)
    sl_flag[[20, 120]] = True

    session = np.arange(n)
    zone_low = np.where(session < 100, 8.0, 100.0)
    zone_high = np.where(session < 100, 12.0, 120.0)
    b_idx = np.where(session < 100, 15, 100).astype(np.int64)

    out = fib._lowest_in_zone_swing(low, sl_flag, reach, zone_low, zone_high, b_idx)
    found = np.isfinite(out)
    assert found.any()
    assert np.all(out[found] >= zone_low[found])
    assert np.all(out[found] <= zone_high[found])


def test_stop_reference_waits_for_the_confirming_window():
    """FR-17.1 again, on this path specifically.

    The swing prints at 120 and is usable from 123. Sessions 120-122 must not
    see it, or the stop is set from a fractal that had not completed.
    """
    n, reach = 200, 3
    low = np.full(n, 500.0)
    for offset in range(-reach, reach + 1):
        low[120 + offset] = 110.0 + abs(offset)
    sl_flag = np.zeros(n, dtype=bool)
    sl_flag[120] = True

    zone_low = np.full(n, 100.0)
    zone_high = np.full(n, 120.0)
    b_idx = np.full(n, 100, dtype=np.int64)

    out = fib._lowest_in_zone_swing(low, sl_flag, reach, zone_low, zone_high, b_idx)

    assert np.isnan(out[119])
    assert np.isnan(out[122])
    assert out[123] == pytest.approx(110.0)


def test_stop_reference_ignores_swings_that_predate_this_leg_high():
    """A low printed before B belongs to the advance, not to the retracement."""
    n, reach = 200, 3
    low = np.full(n, 500.0)
    for offset in range(-reach, reach + 1):
        low[40 + offset] = 110.0 + abs(offset)   # priced in the band, but early
    sl_flag = np.zeros(n, dtype=bool)
    sl_flag[40] = True

    zone_low = np.full(n, 100.0)
    zone_high = np.full(n, 120.0)
    b_idx = np.full(n, 100, dtype=np.int64)      # B sits after that swing

    out = fib._lowest_in_zone_swing(low, sl_flag, reach, zone_low, zone_high, b_idx)
    assert np.all(np.isnan(out))
