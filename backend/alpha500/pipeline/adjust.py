"""Corporate-action adjustment (SRS 3.3).

FR-3.1: an unadjusted split shows up as a spurious -50% daily return and
corrupts every downstream metric and every screen.

FR-3.3: raw prices stay in ``ohlcv_daily``; a per-date ``adj_factor`` carries
the correction. Adjusted price = raw x factor, adjusted volume = raw / factor.

FR-3.4: splits and bonuses adjust the series; ordinary cash dividends do not.
The operator trades price, and price-return momentum is the convention in the
momentum literature.
"""

from __future__ import annotations

from datetime import date

import duckdb
import numpy as np
from numpy.typing import NDArray

from alpha500.providers.models import ActionType


def compute_adj_factors(
    trade_dates: NDArray[np.object_],
    actions: list[tuple[date, str, float | None, float | None]],
) -> NDArray[np.float64]:
    """Cumulative adjustment factor for each date in ``trade_dates``.

    A 1:2 split on date X means every price strictly before X must be halved,
    so those dates carry factor 0.5 and dates from X onward carry 1.0. Multiple
    events compound.
    """
    factors = np.ones(len(trade_dates), dtype=np.float64)
    for ex_date, action_type, ratio_from, ratio_to in actions:
        if action_type not in {ActionType.SPLIT, ActionType.BONUS}:
            continue
        if not ratio_to or not ratio_from or ratio_to <= 0 or ratio_from <= 0:
            continue
        multiple = ratio_to / ratio_from
        if multiple <= 0 or abs(multiple - 1.0) < 1e-12:
            continue
        before = np.array([d < ex_date for d in trade_dates], dtype=bool)
        factors[before] /= multiple
    return factors


def apply_adjustments(conn: duckdb.DuckDBPyConnection, instrument_token: int) -> int:
    """Recompute and persist ``adj_factor`` for one instrument."""
    rows = conn.execute(
        "SELECT trade_date FROM ohlcv_daily WHERE instrument_token = ? ORDER BY trade_date",
        [instrument_token],
    ).fetchall()
    if not rows:
        return 0
    trade_dates = np.array([r[0] for r in rows], dtype=object)

    actions = conn.execute(
        """
        SELECT ex_date, action_type, ratio_from, ratio_to
          FROM corporate_actions
         WHERE instrument_token = ? AND action_type IN ('SPLIT', 'BONUS')
         ORDER BY ex_date
        """,
        [instrument_token],
    ).fetchall()

    factors = compute_adj_factors(trade_dates, actions)
    conn.executemany(
        "UPDATE ohlcv_daily SET adj_factor = ? WHERE instrument_token = ? AND trade_date = ?",
        [(float(f), instrument_token, d) for f, d in zip(factors, trade_dates)],
    )
    return len(trade_dates)


def reconcile_adjustments(
    conn: duckdb.DuckDBPyConnection, threshold: float = 0.35
) -> list[dict[str, object]]:
    """FR-3.2 reconciliation: no adjusted return may exceed +/-35% on an ex-date.

    Broker and vendor feeds may or may not already be split-adjusted, and the
    behaviour is not contractually guaranteed. This asserts the outcome rather
    than trusting either answer. Where the vendor already adjusts, the computed
    factor is 1.0 and this test proves it.

    Returns the list of violations; empty means the gate passes.
    """
    rows = conn.execute(
        """
        WITH adjusted AS (
            SELECT o.instrument_token, o.trade_date,
                   o.close * o.adj_factor AS adj_close,
                   i.tradingsymbol
              FROM ohlcv_daily o
              JOIN instruments i ON i.instrument_token = o.instrument_token
        ),
        returns AS (
            SELECT instrument_token, tradingsymbol, trade_date, adj_close,
                   adj_close / LAG(adj_close) OVER (
                       PARTITION BY instrument_token ORDER BY trade_date
                   ) - 1 AS ret
              FROM adjusted
        )
        SELECT r.tradingsymbol, r.trade_date, r.ret, ca.action_type
          FROM returns r
          JOIN corporate_actions ca
            ON ca.instrument_token = r.instrument_token
           AND ca.ex_date = r.trade_date
           AND ca.action_type IN ('SPLIT', 'BONUS')
         WHERE abs(r.ret) > ?
         ORDER BY abs(r.ret) DESC
        """,
        [threshold],
    ).fetchall()
    return [
        {"tradingsymbol": r[0], "trade_date": r[1], "return": r[2], "action_type": r[3]}
        for r in rows
    ]
