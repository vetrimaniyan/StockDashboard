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
        "limit": 10,
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
