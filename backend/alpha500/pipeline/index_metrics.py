"""FR-18.3/18.4 — range, drawdown and trend state per tracked index.

Two rules shape everything here.

**The current bar is excluded from the peak, and included in the 52-week
window.** That asymmetry is deliberate. FR-15.2's rule exists so that an index
making a new high today does not read as 0% below its peak — which would make
it indistinguishable from one still climbing toward it — so the peak looks
strictly backwards. The 52-week high has no such problem: an index at a new
52-week high should read ``range_position_52w = 1.0``, and that is the useful
answer.

**A metric that cannot be computed is absent, not approximated.** Six of the
tracked indices are close-only projections of a sampled valuation history and
hold 5-12% of the sessions their date range implies. A 252-session window over
a series that thin spans years while looking like a year, and an SMA200 over it
is not a 200-day average of anything. Those indices are reported unavailable
with the reason attached, rather than given numbers that would be read as
comparable to the other eighteen.

The peak is named ``period_high``, never an all-time high, until an index's
series is shown to reach its documented inception (D-11). None does today.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

import duckdb
import numpy as np

from alpha500.pipeline.index_series import CLOSE, index_coverage
from alpha500.pipeline.index_universe import TRACKED, TrackedIndex

WINDOW_52W = 252
SMA_FAST = 50
SMA_SLOW = 200
SLOPE_LOOKBACK = 21

# What counts as a rising or falling 200 SMA. Without a tolerance, an index
# oscillating around a flat slow average is classified by whichever side of
# zero the last basis point fell on, which is noise wearing a trend's name.
# FR-18.4's acceptance pins this: a slope inside +/-0.1% over 21 sessions is
# neither rising nor falling, and the honest answer is TRANSITIONAL.
SLOPE_TOLERANCE = 0.001

UPTREND = "UPTREND"
DOWNTREND = "DOWNTREND"
TRANSITIONAL = "TRANSITIONAL"

# Sessions needed before a trend state means anything: the slow average, plus
# the lookback its slope is measured over.
MIN_TREND_SESSIONS = SMA_SLOW + SLOPE_LOOKBACK


@dataclass(slots=True)
class IndexMetrics:
    index_name: str
    category: str
    as_of: date | None = None
    close: float | None = None
    ohlc_basis: str | None = None
    sessions: int = 0

    high_52w: float | None = None
    low_52w: float | None = None
    range_position_52w: float | None = None
    pct_from_52w_high: float | None = None

    period_high: float | None = None
    period_high_date: date | None = None
    pct_from_period_high: float | None = None
    sessions_since_period_high: int | None = None

    sma_50: float | None = None
    sma_200: float | None = None
    trend_state: str | None = None
    sessions_in_state: int | None = None

    available: bool = True
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index_name": self.index_name,
            "category": self.category,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "close": self.close,
            "ohlc_basis": self.ohlc_basis,
            "sessions": self.sessions,
            "high_52w": self.high_52w,
            "low_52w": self.low_52w,
            "range_position_52w": self.range_position_52w,
            "pct_from_52w_high": self.pct_from_52w_high,
            "period_high": self.period_high,
            "period_high_date": (
                self.period_high_date.isoformat() if self.period_high_date else None
            ),
            "pct_from_period_high": self.pct_from_period_high,
            "sessions_since_period_high": self.sessions_since_period_high,
            "sma_50": self.sma_50,
            "sma_200": self.sma_200,
            "trend_state": self.trend_state,
            "sessions_in_state": self.sessions_in_state,
            "available": self.available,
            "reason": self.reason,
        }


def _sma(values: np.ndarray, window: int) -> np.ndarray:
    """Trailing simple moving average; NaN until the window is full."""
    out = np.full(values.shape, np.nan)
    if values.size < window:
        return out
    cumulative = np.cumsum(np.insert(values, 0, 0.0))
    out[window - 1:] = (cumulative[window:] - cumulative[:-window]) / window
    return out


def _trend_series(closes: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-session trend state, plus the two averages it is built from.

    Computed across the whole series rather than for the latest bar alone,
    because ``sessions_in_state`` is the difference between a sector three
    sessions into an uptrend and one eleven months in, and that cannot be
    recovered from a single session's values.
    """
    fast, slow = _sma(closes, SMA_FAST), _sma(closes, SMA_SLOW)
    states = np.full(closes.shape, "", dtype=object)

    for i in range(closes.size):
        if i < MIN_TREND_SESSIONS - 1 or np.isnan(slow[i]) or np.isnan(fast[i]):
            continue
        earlier = slow[i - SLOPE_LOOKBACK]
        if np.isnan(earlier) or earlier <= 0:
            continue
        slope = slow[i] / earlier - 1.0
        if closes[i] > slow[i] and fast[i] > slow[i] and slope > SLOPE_TOLERANCE:
            states[i] = UPTREND
        elif closes[i] < slow[i] and fast[i] < slow[i] and slope < -SLOPE_TOLERANCE:
            states[i] = DOWNTREND
        else:
            states[i] = TRANSITIONAL
    return states, fast, slow


def _run_length(states: np.ndarray) -> int:
    """How many sessions the latest state has held, unbroken."""
    latest = states[-1]
    count = 0
    for value in reversed(states):
        if value != latest:
            break
        count += 1
    return count


def compute_index_metrics(
    conn: duckdb.DuckDBPyConnection,
    indices: Sequence[TrackedIndex] = TRACKED,
    as_of: date | None = None,
) -> list[IndexMetrics]:
    """FR-18.3 and FR-18.4 for each tracked index."""
    coverage = {row["index_name"]: row for row in index_coverage(conn, indices)}
    out: list[IndexMetrics] = []

    for index in indices:
        cover = coverage.get(index.name, {})
        metrics = IndexMetrics(
            index_name=index.name,
            category=index.category,
            ohlc_basis=cover.get("ohlc_basis"),
            sessions=int(cover.get("sessions") or 0),
        )

        if not metrics.sessions:
            metrics.available = False
            metrics.reason = "No series ingested. Run `alpha500 index-series`."
            out.append(metrics)
            continue

        # The gate that matters. A sampled series answers every formula below
        # and every answer is wrong by a factor nobody can see in the number.
        if not cover.get("daily"):
            density = cover.get("density")
            shown = f"{density * 100:.0f}%" if density is not None else "unknown"
            metrics.available = False
            metrics.reason = (
                f"Series is sampled, not daily ({shown} of its span, "
                f"{metrics.sessions} sessions), so a 52-week window and a 200 SMA "
                f"would span years rather than the periods they name."
            )
            out.append(metrics)
            continue

        rows = conn.execute(
            "SELECT trade_date, high, low, close FROM index_ohlcv_daily "
            "WHERE index_name = ? AND (? IS NULL OR trade_date <= ?) "
            "ORDER BY trade_date",
            [index.name, as_of, as_of],
        ).fetchall()
        if not rows:
            metrics.available = False
            metrics.reason = "No sessions on or before the requested date."
            out.append(metrics)
            continue

        dates = [r[0] for r in rows]
        closes = np.array([float(r[3]) for r in rows], dtype=np.float64)
        # A close-only series has no highs; the basis is recorded so the view
        # can say the range was measured on closes rather than imply otherwise.
        if metrics.ohlc_basis == CLOSE:
            highs = lows = closes
        else:
            highs = np.array([float(r[1]) if r[1] is not None else float(r[3])
                              for r in rows], dtype=np.float64)
            lows = np.array([float(r[2]) if r[2] is not None else float(r[3])
                             for r in rows], dtype=np.float64)

        metrics.as_of = dates[-1]
        metrics.close = float(closes[-1])

        # --- FR-18.3: range, including the current bar -------------------
        if closes.size >= WINDOW_52W:
            high_52w = float(highs[-WINDOW_52W:].max())
            low_52w = float(lows[-WINDOW_52W:].min())
            metrics.high_52w, metrics.low_52w = high_52w, low_52w
            span = high_52w - low_52w
            if span > 0:
                metrics.range_position_52w = (metrics.close - low_52w) / span
            if high_52w > 0:
                metrics.pct_from_52w_high = metrics.close / high_52w - 1.0

        # --- FR-18.3: the peak, excluding the current bar ----------------
        if closes.size >= 2:
            prior = highs[:-1]
            # argmax takes the earliest bar on a tie, which reads the metric as
            # "the session the peak was first set" rather than the last time
            # the level was touched. Exact ties in a float high are vanishingly
            # rare in real series; the choice is recorded so the reading of
            # sessions_since_period_high is not left to be inferred.
            peak_at = int(prior.argmax())
            peak = float(prior[peak_at])
            if peak > 0:
                metrics.period_high = peak
                metrics.period_high_date = dates[peak_at]
                metrics.pct_from_period_high = metrics.close / peak - 1.0
                metrics.sessions_since_period_high = (closes.size - 1) - peak_at

        # --- FR-18.4: trend state ----------------------------------------
        if closes.size >= MIN_TREND_SESSIONS:
            states, fast, slow = _trend_series(closes)
            if states[-1]:
                metrics.trend_state = str(states[-1])
                metrics.sessions_in_state = _run_length(states)
                metrics.sma_50 = float(fast[-1])
                metrics.sma_200 = float(slow[-1])
        if metrics.trend_state is None:
            metrics.reason = (
                f"{metrics.sessions} sessions; a trend state needs "
                f"{MIN_TREND_SESSIONS}."
            )

        out.append(metrics)

    return out


# Sort order for the view (FR-18.10): trend state first, then how far through
# its own 52-week range the index sits. Until FR-18.8's momentum score exists,
# range position is the honest stand-in - it is a position, not a ranking, and
# is not presented as one.
_STATE_ORDER = {UPTREND: 0, TRANSITIONAL: 1, DOWNTREND: 2}


def sort_key(row: IndexMetrics) -> tuple[int, float]:
    return (
        _STATE_ORDER.get(row.trend_state or "", 3),
        -(row.range_position_52w if row.range_position_52w is not None else -1.0),
    )
