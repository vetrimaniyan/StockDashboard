"""Cross-sectional metrics — computed across the universe for one date.

FR-6.4 is explicit that RS rating cannot be computed per-symbol in isolation:
it is a percentile against the eligible universe and must be recomputed for
the whole universe every session. The same is true of momentum rank and the
composite z-score.

Eligibility is applied before ranking, not after. A rank computed over
ineligible names and then filtered would leave gaps in the sequence and
misstate every percentile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray

from alpha500.config import settings
from alpha500.metrics import kernels as k

Floats = NDArray[np.float64]


@dataclass(slots=True)
class CompositeWeights:
    momentum: float = 0.30
    ret_12m_1m: float = 0.20
    rs_rating: float = 0.20
    range_position: float = 0.15
    atr_pct: float = 0.10  # subtracted: lower volatility scores better
    rel_volume: float = 0.05

    @classmethod
    def from_settings(cls) -> "CompositeWeights":
        return cls(
            momentum=settings.w_momentum,
            ret_12m_1m=settings.w_ret_12m_1m,
            rs_rating=settings.w_rs_rating,
            range_position=settings.w_range_position,
            atr_pct=settings.w_atr_pct,
            rel_volume=settings.w_rel_volume,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "momentum_score": self.momentum,
            "ret_12m_1m": self.ret_12m_1m,
            "rs_rating": self.rs_rating,
            "range_position_52w": self.range_position,
            "atr_pct_14": -self.atr_pct,
            "rel_volume": self.rel_volume,
        }


def relative_strength(stock_return: Floats, index_return: float | None) -> Floats:
    """``(1 + r_stock) / (1 + r_index) - 1`` (FR-6.3)."""
    if index_return is None or not math.isfinite(index_return) or index_return <= -1.0:
        return np.full_like(stock_return, np.nan)
    return (1.0 + stock_return) / (1.0 + index_return) - 1.0


def rs_rating(
    ret_3m: Floats, ret_6m: Floats, ret_9m: Floats, ret_12m: Floats, eligible: NDArray[np.bool_]
) -> tuple[Floats, Floats]:
    """1-99 RS rating from the quarterly-weighted blend (FR-6.4).

    Returns ``(rs_raw, rs_rating)``. Only eligible names take part in the
    percentile; ineligible ones get null rather than a rating computed against
    a population they were excluded from.
    """
    rs_raw = 0.40 * ret_3m + 0.20 * ret_6m + 0.20 * ret_9m + 0.20 * ret_12m
    masked = np.where(eligible, rs_raw, np.nan)
    pct = k.percentile_rank(masked)
    with np.errstate(invalid="ignore"):
        rating = np.ceil(99.0 * pct)
    # A percentile of exactly 0 would floor to 0; the scale starts at 1.
    rating = np.where(np.isfinite(rating), np.maximum(rating, 1.0), np.nan)
    return rs_raw, rating


def momentum_rank(momentum_score: Floats, eligible: NDArray[np.bool_]) -> Floats:
    """Dense rank of momentum score, descending, 1 = strongest (FR-6.7)."""
    return k.dense_rank_desc(np.where(eligible, momentum_score, np.nan))


def composite_z(
    components: dict[str, Floats],
    weights: CompositeWeights,
    eligible: NDArray[np.bool_],
) -> Floats:
    """Weighted sum of winsorised, z-scored components (FR-6.8).

    Winsorisation happens before z-scoring and is not optional. Components are
    z-scored over eligible names only, so an ineligible outlier cannot move
    the mean the eligible names are measured against.
    """
    total: Floats | None = None
    for name, weight in weights.as_dict().items():
        raw = components.get(name)
        if raw is None:
            continue
        masked = np.where(eligible, raw, np.nan)
        z = k.zscore(k.winsorise(masked))
        contribution = weight * np.nan_to_num(z, nan=0.0)
        total = contribution if total is None else total + contribution

    if total is None:
        return np.full(len(eligible), np.nan)
    return np.where(eligible, total, np.nan)


def eligibility(
    history_days: Floats,
    turnover_20d_median: Floats,
    series: Sequence[str],
    excluded_symbols: set[str] | None = None,
    symbols: Sequence[str] | None = None,
) -> tuple[NDArray[np.bool_], list[str]]:
    """Screen-result eligibility (FR-1.5, FR-1.6).

    Excluded names are still ingested and stored — they are removed from
    screen results only. Returns the mask plus the reason for each row, so the
    UI can show an "Insufficient history" list rather than silently dropping.
    """
    n = len(series)
    reasons: list[str] = [""] * n
    mask = np.ones(n, dtype=bool)
    excluded_symbols = excluded_symbols or set()
    symbols = symbols or [""] * n

    for i in range(n):
        if series[i] not in settings.allowed_series:
            mask[i] = False
            reasons[i] = f"series {series[i]}"
        elif symbols[i] in excluded_symbols:
            mask[i] = False
            reasons[i] = "surveillance (ASM/GSM/T2T/suspended)"
        elif not np.isfinite(history_days[i]) or history_days[i] < settings.min_history_days:
            mask[i] = False
            reasons[i] = "insufficient history"
        elif (
            not np.isfinite(turnover_20d_median[i])
            or turnover_20d_median[i] < settings.liquidity_floor_inr
        ):
            mask[i] = False
            reasons[i] = "below liquidity floor"

    return mask, reasons


def finalise_trend_template(
    partial: Floats, rs_rating_values: Floats
) -> tuple[Floats, NDArray[Any]]:
    """Apply criterion 8 (``rs_rating >= 70``) and flag the 8/8 names.

    The partial score is kept and displayed: a 7/8 stock approaching its
    eighth criterion is an actionable watchlist item that a binary flag hides.
    """
    with np.errstate(invalid="ignore"):
        eighth = np.where(rs_rating_values >= 70, 1.0, 0.0)
    score = partial + eighth
    score = np.where(np.isfinite(partial), score, np.nan)
    is_template = np.where(np.isfinite(score), score >= 8.0, False).astype(object)
    return score, is_template


def detect_pullback(
    ma_alignment: NDArray[Any],
    is_trend_template: NDArray[Any],
    close: Floats,
    ema_21: Floats,
    sma_50: Floats,
    ret_1w: Floats,
    rsi_14: Floats,
) -> NDArray[Any]:
    """Pullback in an established uptrend (FR-6.15)."""
    with np.errstate(invalid="ignore"):
        near_ema = np.abs(close / ema_21 - 1.0) <= 0.03
        near_sma = np.abs(close / sma_50 - 1.0) <= 0.03
        result = (
            (ma_alignment == True)  # noqa: E712 - object arrays need == not `is`
            & (is_trend_template == True)  # noqa: E712
            & (near_ema | near_sma)
            & (ret_1w < 0)
            & (rsi_14 >= 40)
            & (rsi_14 <= 55)
        )
    return np.where(result, True, False).astype(object)
