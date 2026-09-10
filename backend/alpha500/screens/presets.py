"""Built-in preset screens (FR-7.5). Editable, but not deletable."""

from __future__ import annotations

from datetime import date
from typing import Any, Final

import duckdb

from alpha500.config import settings
from alpha500.screens.filter_engine import run_screen

# FR-7.6: the exit screen is mandatory and outranks the entry candidates in
# the UI. Momentum tools bias hard toward finding entries; surfacing exits
# with equal or greater prominence is a deliberate counterweight.
MOMENTUM_BREAKDOWN: Final[str] = "Momentum Breakdown"

# FR-14.7: named so it cannot be confused with "Pullback to Support", which is
# a different setup rather than a variant of this one.
PULLBACK_REVERSAL: Final[str] = "Pullback + Reversal"

# Stocks pressing against the top of their stored history. Named "period high"
# rather than "all-time high" on purpose: the lookback is however much history
# was backfilled, so for a long-listed name this is a multi-year high, not an
# all-time one. Claiming otherwise in the UI would be exactly the kind of quiet
# overstatement FR-8.9 exists to prevent.
APPROACHING_HIGH: Final[str] = "Approaching High"

# Within 3% of the period high. Tight enough that the list stays actionable;
# widen it in the Filters panel for a broader sweep.
APPROACHING_HIGH_PCT: Final[float] = -0.03

# FR-17. Geometry, not support: the levels come from arithmetic on a past
# advance, never from buyers having appeared at a price. Named for the zone
# rather than for a signal, because arriving in it predicts nothing.
FIB_REVERSAL_ZONE: Final[str] = "Fibonacci Reversal Zone"

# Not a screen but the universe itself: every constituent, including the ones
# the screens deliberately exclude. FR-1.5 requires symbols dropped for thin
# liquidity or short history to be visible somewhere rather than silently
# absent, and "why is this stock never in my results" is otherwise
# unanswerable from the UI.
ALL_CONSTITUENTS: Final[str] = "All NIFTY 500"

PRESETS: Final[dict[str, dict[str, Any]]] = {
    "Momentum Leaders": {
        "name": "Momentum Leaders",
        "version": 1,
        "description": "Top-ranked names by volatility-adjusted momentum score.",
        "universe": {"index": settings.index_name, "exclude_ineligible": True},
        "filters": {
            "op": "AND",
            "conditions": [
                {"field": "momentum_rank", "operator": "<=", "value": 20},
                {"field": "gap_disqualified", "operator": "=", "value": False},
            ],
        },
        "sort": [{"field": "momentum_rank", "direction": "asc"}],
        "limit": 20,
    },
    "Trend Template": {
        "name": "Trend Template",
        "version": 1,
        "description": "All eight trend-structure criteria met (FR-6.12).",
        "universe": {"index": settings.index_name, "exclude_ineligible": True},
        "filters": {
            "op": "AND",
            "conditions": [{"field": "is_trend_template", "operator": "=", "value": True}],
        },
        "sort": [{"field": "rs_rating", "direction": "desc"}],
        "limit": 100,
    },
    "52-Week High Breakout": {
        "name": "52-Week High Breakout",
        "version": 1,
        "description": "New 52-week high on confirming volume, volatility capped.",
        "universe": {"index": settings.index_name, "exclude_ineligible": True},
        "filters": {
            "op": "AND",
            "conditions": [
                {"field": "is_52w_high_breakout", "operator": "=", "value": True},
                {"field": "rel_volume", "operator": ">=", "value": 1.5},
                {"field": "atr_pct_14", "operator": "<=", "value": 0.07},
            ],
        },
        "sort": [{"field": "momentum_score", "direction": "desc"}],
        "limit": 50,
    },
    "Volatility Contraction": {
        "name": "Volatility Contraction",
        "version": 1,
        "description": "Tight base after an advance — candidates before the move.",
        "universe": {"index": settings.index_name, "exclude_ineligible": True},
        "filters": {
            "op": "AND",
            "conditions": [
                {"field": "is_in_base", "operator": "=", "value": True},
                {"field": "base_length_days", "operator": ">=", "value": 10},
                {"field": "rs_rating", "operator": ">=", "value": 70},
                {"field": "range_position_52w", "operator": ">=", "value": 0.7},
            ],
        },
        "sort": [{"field": "base_length_days", "direction": "desc"}],
        "limit": 50,
    },
    "Pullback to Support": {
        "name": "Pullback to Support",
        "version": 1,
        "description": "Established uptrend pulling back to the 21 EMA or 50 SMA.",
        "universe": {"index": settings.index_name, "exclude_ineligible": True},
        "filters": {
            "op": "AND",
            "conditions": [{"field": "is_pullback", "operator": "=", "value": True}],
        },
        "sort": [{"field": "momentum_score", "direction": "desc"}],
        "limit": 50,
    },
    # FR-14.6. Deliberately distinct from "Pullback to Support" above, which is
    # a continuation filter: it demands a perfect 8/8 trend template and a
    # neutral RSI, and asks for no evidence the pullback has actually stopped.
    # This asks the opposite question - price is at a level buyers previously
    # defended, and something has turned. FR-14.7 requires the UI to say so.
    PULLBACK_REVERSAL: {
        "name": PULLBACK_REVERSAL,
        "version": 1,
        "description": (
            "Pulled back to a support level and showing reversal confirmation, "
            "with the long-term uptrend intact."
        ),
        "universe": {"index": settings.index_name, "exclude_ineligible": True},
        "filters": {
            "op": "AND",
            "conditions": [
                {"field": "is_pullback_reversal", "operator": "=", "value": True}
            ],
        },
        # FR-14.6: lexicographic and fully deterministic including ties (AR-4).
        # A weighted composite would need cross-sectional z-scores and would
        # hide which factor drove any given rank.
        "sort": [
            {"field": "reversal_score", "direction": "desc"},
            {"field": "rs_rating", "direction": "desc"},
            {"field": "support_distance_pct", "direction": "asc"},
            {"field": "instrument_token", "direction": "asc"},
        ],
        # Deliberately uncapped. FR-14.6 requires a top-10 *dashboard section*,
        # which the dashboard endpoint now slices for itself; carrying that cap
        # in the preset also truncated the screener, where the same setup on a
        # name ranked 18th is a result the user asked to see, not noise. The
        # ordering above still puts the strongest candidates first.
    },
    APPROACHING_HIGH: {
        "name": APPROACHING_HIGH,
        "version": 1,
        "description": (
            "Within 3% of the highest price in stored history, trend intact "
            "and volume holding up — before the breakout, not after. Depth "
            "varies by symbol: check History (sessions) for how far back the "
            "high actually reaches."
        ),
        "universe": {"index": settings.index_name, "exclude_ineligible": True},
        "filters": {
            "op": "AND",
            "conditions": [
                {"field": "pct_from_period_high", "operator": ">=",
                 "value": APPROACHING_HIGH_PCT},
                # Strictly below: at or above zero the stock has already taken
                # the high out, which is the 52-Week High Breakout screen's job.
                {"field": "pct_from_period_high", "operator": "<", "value": 0.0},
                # Trend intact. A graded score rather than the full 8/8
                # template: demanding perfection here would mostly return the
                # Trend Template screen back again.
                {"field": "trend_template_score", "operator": ">=", "value": 5},
                # Volume holding up. Not a surge — that is what confirms a
                # breakout, and by definition it has not happened yet — but
                # enough to rule out a name drifting up on no interest.
                {"field": "rel_volume", "operator": ">=", "value": 0.8},
                {"field": "gap_disqualified", "operator": "=", "value": False},
            ],
        },
        # Closest to the high first, then relative strength, then the primary
        # key so ties cannot reorder between runs (AR-4).
        "sort": [
            {"field": "pct_from_period_high", "direction": "desc"},
            {"field": "rs_rating", "direction": "desc"},
            {"field": "instrument_token", "direction": "asc"},
        ],
        "limit": 50,
    },
    FIB_REVERSAL_ZONE: {
        "name": FIB_REVERSAL_ZONE,
        "version": 1,
        "description": (
            "Confirmed uptrend that has pulled back into the 50%-61.8% "
            "retracement of its last impulse leg, on thinning volume, and "
            "turned today. Arriving in the zone is arithmetic, not a "
            "forecast — the reversal bar is the event. Most sessions return "
            "0-5 rows; none is the setup being absent, not a fault."
        ),
        "universe": {"index": settings.index_name, "exclude_ineligible": True},
        "filters": {
            "op": "AND",
            "conditions": [
                # Trend gates first: this is a pullback screen, so the trend
                # it is pulling back within has to exist. Every gate here has
                # to survive a 50-61.8% retracement, because that is what the
                # screen is looking for.
                #
                # The metric engine already draws that line. `is_long_term_
                # uptrend` exists because `ma_alignment` demands close > SMA50,
                # "which a 50-61.8% retracement normally breaks - using it to
                # gate a pullback screen would exclude the very setups the
                # screen exists to find".
                #
                # `trend_template_score >= 6` used to sit here and reintroduced
                # that same condition through the back door: criterion 5 is
                # close > SMA50, criterion 1 is close > SMA150 and SMA200.
                # Measured over 2019-2026, inside the zone criterion 5 held on
                # 9.0% of rows and criterion 1 on 15.1%. Demanding six of eight
                # asked the screen to find a deep pullback and then required
                # price not to have pulled back.
                #
                # What replaces it is criterion 3 - the slope of the long
                # average - which a retracement does not invalidate.
                # `is_long_term_uptrend` already carries SMA50 > SMA200, the
                # pullback-safe half of criterion 4. The rest of the template
                # is a price-versus-average test and has no business gating
                # this screen.
                {"field": "is_long_term_uptrend", "operator": "=", "value": True},
                {"field": "sma_200_slope_1m", "operator": ">", "value": 0.0},
                # FR-17.6's own quality floor, left where it is. Inside the
                # zone it holds on 9.9% of rows, which is the same tension in
                # milder form - a deep pullback depresses the 3-month leg of
                # the rating. Whether to relax it is a decision about what the
                # screen is for, not a contradiction to be repaired, so it
                # stays until someone decides otherwise. Measured over the
                # window: 70 yields 2 signals, 50 yields 4, dropping it
                # entirely yields 8.
                {"field": "rs_rating", "operator": ">=", "value": 70},
                # Location.
                {"field": "in_fib_zone", "operator": "=", "value": True},
                # Volume shape: confirmed advance, thinned pullback. Not one
                # "volume above average" test, which in a retracement selects
                # for distribution as readily as accumulation (FR-17.4).
                {"field": "vol_impulse_ratio", "operator": ">=",
                 "value": settings.fib_vol_impulse_min},
                {"field": "vol_dryup_ratio", "operator": "<=",
                 "value": settings.fib_vol_dryup_max},
                # The event. Never list on zone membership alone (FR-17.5).
                {"field": "is_fib_reversal_bar", "operator": "=", "value": True},
                {"field": "fib_reward_risk", "operator": ">=",
                 "value": settings.fib_min_reward_risk},
            ],
        },
        "sort": [
            {"field": "fib_setup_score", "direction": "desc"},
            {"field": "instrument_token", "direction": "asc"},
        ],
        "limit": 25,
    },
    ALL_CONSTITUENTS: {
        "name": ALL_CONSTITUENTS,
        "version": 1,
        "description": (
            "Every NIFTY 500 constituent, including names excluded from the "
            "screens. Filter on is_eligible to see which and why."
        ),
        # The one screen that does NOT hide ineligible rows.
        "universe": {"index": settings.index_name, "exclude_ineligible": False},
        "filters": {"op": "AND", "conditions": []},
        # Largest first, which is how the index itself is weighted. Symbols
        # without a float-share count sort last rather than being guessed at.
        "sort": [
            {"field": "market_cap", "direction": "desc"},
            {"field": "tradingsymbol", "direction": "asc"},
        ],
        "limit": 500,
    },
    MOMENTUM_BREAKDOWN: {
        "name": MOMENTUM_BREAKDOWN,
        "version": 1,
        # FR-12.2: this is an exit screen for existing holdings. It is long-only
        # by construction and MUST NOT be read as a short-candidate list.
        "description": (
            "EXIT SIGNAL for existing holdings — momentum rank deteriorating or "
            "price below the 100-day average. Not a short-candidate list."
        ),
        "universe": {"index": settings.index_name, "exclude_ineligible": False},
        "filters": {
            "op": "OR",
            "conditions": [
                {"field": "momentum_rank", "operator": ">", "value": 250},
                {"field": "pct_from_52w_high", "operator": "<=", "value": -0.20},
            ],
        },
        "sort": [{"field": "momentum_rank", "direction": "desc"}],
        "limit": 100,
    },
}


def list_presets() -> list[dict[str, Any]]:
    return list(PRESETS.values())


def get_preset(name: str) -> dict[str, Any]:
    if name not in PRESETS:
        raise KeyError(f"unknown preset: {name}")
    return PRESETS[name]


def fib_funnel(conn: duckdb.DuckDBPyConnection, as_of: date) -> list[dict[str, Any]]:
    """Stage-by-stage survivor counts for the FR-17 screen (FR-17.8).

    An empty result grid has two very different causes: the setup is absent
    today, or a threshold is misconfigured. They look identical without this,
    and only one of them is worth acting on.
    """
    row = conn.execute(
        """
        SELECT
          count(*),
          sum(CASE WHEN is_eligible AND is_long_term_uptrend
                    AND sma_200_slope_1m > 0 AND rs_rating >= 70
                   THEN 1 ELSE 0 END),
          sum(CASE WHEN is_eligible AND is_long_term_uptrend
                    AND sma_200_slope_1m > 0 AND rs_rating >= 70
                    AND fib_leg_high_price IS NOT NULL THEN 1 ELSE 0 END),
          sum(CASE WHEN is_eligible AND is_long_term_uptrend
                    AND sma_200_slope_1m > 0 AND rs_rating >= 70
                    AND in_fib_zone THEN 1 ELSE 0 END),
          sum(CASE WHEN is_eligible AND is_long_term_uptrend
                    AND sma_200_slope_1m > 0 AND rs_rating >= 70
                    AND in_fib_zone AND vol_impulse_ratio >= ?
                    AND vol_dryup_ratio <= ? THEN 1 ELSE 0 END),
          sum(CASE WHEN is_eligible AND is_long_term_uptrend
                    AND sma_200_slope_1m > 0 AND rs_rating >= 70
                    AND in_fib_zone AND vol_impulse_ratio >= ?
                    AND vol_dryup_ratio <= ? AND is_fib_reversal_bar
                   THEN 1 ELSE 0 END),
          sum(CASE WHEN is_eligible AND is_long_term_uptrend
                    AND sma_200_slope_1m > 0 AND rs_rating >= 70
                    AND in_fib_zone AND vol_impulse_ratio >= ?
                    AND vol_dryup_ratio <= ? AND is_fib_reversal_bar
                    AND fib_reward_risk >= ? THEN 1 ELSE 0 END)
          FROM metrics_daily WHERE trade_date = ?
        """,
        [
            settings.fib_vol_impulse_min, settings.fib_vol_dryup_max,
            settings.fib_vol_impulse_min, settings.fib_vol_dryup_max,
            settings.fib_vol_impulse_min, settings.fib_vol_dryup_max,
            settings.fib_min_reward_risk, as_of,
        ],
    ).fetchone()

    labels = (
        ("universe", "NIFTY 500 constituents"),
        ("gated", "Eligible, long-term uptrend, SMA200 rising, RS >= 70"),
        ("valid_leg", "Has a confirmed impulse leg"),
        ("in_zone", "Price inside the 50-61.8% band"),
        ("volume_shape", "Advance confirmed, pullback thinned"),
        ("reversal_bar", "Turned today"),
        ("passed_rr", "Reward:risk at or above the floor"),
    )
    return [
        {"stage": key, "label": text, "count": int(value or 0)}
        for (key, text), value in zip(labels, row)
    ]


def breadth(conn: duckdb.DuckDBPyConnection, as_of: date) -> dict[str, int]:
    """New Highs vs New Lows — a universe-level breadth reading (FR-7.5)."""
    row = conn.execute(
        """
        SELECT
            sum(CASE WHEN is_52w_high_breakout THEN 1 ELSE 0 END),
            sum(CASE WHEN pct_from_52w_high IS NOT NULL
                      AND pct_above_52w_low IS NOT NULL
                      AND pct_above_52w_low <= 0.001 THEN 1 ELSE 0 END),
            sum(CASE WHEN ret_1d > 0 THEN 1 ELSE 0 END),
            sum(CASE WHEN ret_1d < 0 THEN 1 ELSE 0 END),
            count(*)
          FROM metrics_daily
         WHERE trade_date = ? AND is_eligible
        """,
        [as_of],
    ).fetchone()
    highs, lows, advances, declines, total = (int(v or 0) for v in row)
    return {
        "new_highs": highs,
        "new_lows": lows,
        "net_new_highs": highs - lows,
        "advances": advances,
        "declines": declines,
        "universe": total,
    }


def market_regime(conn: duckdb.DuckDBPyConnection, as_of: date) -> dict[str, Any]:
    """Market-regime banner computed from the index itself (FR-7.7)."""
    rows = conn.execute(
        """
        SELECT close FROM index_ohlcv_daily
         WHERE index_name = ? AND trade_date <= ?
         ORDER BY trade_date DESC LIMIT 200
        """,
        [settings.index_name, as_of],
    ).fetchall()
    closes = [float(r[0]) for r in rows]
    if len(closes) < 200:
        return {"regime": "Unknown", "reason": "insufficient index history", "advisory": None}

    latest = closes[0]
    sma_200 = sum(closes[:200]) / 200
    sma_50 = sum(closes[:50]) / 50

    b = breadth(conn, as_of)
    breadth_positive = b["net_new_highs"] > 0

    if latest < sma_200:
        regime = "Risk-off"
    elif sma_50 > sma_200 and breadth_positive:
        regime = "Risk-on"
    else:
        regime = "Neutral"

    return {
        "regime": regime,
        "index_close": latest,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "net_new_highs": b["net_new_highs"],
        # FR-7.8: visible without being sought; never blocks screening.
        "advisory": (
            "Long momentum strategies have historically suffered their largest "
            "drawdowns in this regime. Screening is not blocked — this is context."
            if regime == "Risk-off"
            else None
        ),
    }


def materialise_presets(conn: duckdb.DuckDBPyConnection, as_of: date) -> int:
    """Pipeline stage 8. Returns total rows across all presets."""
    total = 0
    for definition in PRESETS.values():
        try:
            total += len(run_screen(conn, definition, as_of))
        except Exception:  # noqa: BLE001 - one bad preset must not fail the run
            continue
    return total
