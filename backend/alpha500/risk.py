"""Position sizing, stops and round-trip cost (SRS sections 9 and 11.2).

Nothing here is tax advice. Rates are configurable defaults and must be
confirmed with a cross-border chartered accountant and a French conseiller
fiscal before any output is relied on for filing (FR-12.11, open items B-5/B-6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from alpha500.config import settings


@dataclass(frozen=True, slots=True)
class CostModel:
    """Round-trip friction (FR-12.5). Every component is configurable."""

    brokerage_pct: float = 0.0            # most Indian brokers: 0 on delivery
    brokerage_flat_inr: float = 0.0
    stt_sell_pct: float = 0.001           # 0.1% of sell value, delivery
    exchange_txn_pct: float = 0.0000297
    sebi_fee_pct: float = 0.000001
    stamp_duty_buy_pct: float = 0.00015
    gst_pct: float = 0.18                 # on brokerage + transaction charges

    # FR-12.4: an NRI's broker withholds TDS on the gain at settlement of each
    # profitable exit, rather than the tax being settled at filing. Over a year
    # of frequent turnover this compounds into a materially lower effective
    # rate than the same gross return earned by a resident.
    stcg_effective_rate: float = 0.2392   # < 12 months, s.111A + surcharge + cess
    ltcg_effective_rate: float = 0.1495   # >= 12 months, s.112A above the exemption


@dataclass(frozen=True, slots=True)
class StopSuggestion:
    atr_stop_price: float | None
    atr_stop_distance_pct: float | None
    structural_stop_price: float | None
    wider_stop: str | None


def suggest_stop(
    close: float | None,
    atr_14: float | None,
    base_low: float | None = None,
    k: float | None = None,
) -> StopSuggestion:
    """ATR stop plus the structural alternative, with the wider one flagged (FR-10.1)."""
    if close is None or close <= 0:
        return StopSuggestion(None, None, None, None)

    k = k if k is not None else settings.atr_stop_multiple
    atr_stop = close - k * atr_14 if atr_14 and atr_14 > 0 else None
    distance = (close - atr_stop) / close if atr_stop and atr_stop < close else None

    structural = base_low if base_low and 0 < base_low < close else None

    wider: str | None = None
    if atr_stop is not None and structural is not None:
        wider = "structural" if structural < atr_stop else "atr"
    elif atr_stop is not None:
        wider = "atr"
    elif structural is not None:
        wider = "structural"

    return StopSuggestion(atr_stop, distance, structural, wider)


@dataclass(frozen=True, slots=True)
class PositionSize:
    quantity: int
    position_value: float
    risk_amount: float
    exceeds_max_weight: bool
    capped_at_max_weight: bool


def size_position(
    close: float,
    stop_price: float,
    portfolio_value: float,
    risk_per_trade_pct: float | None = None,
    max_position_weight: float | None = None,
) -> PositionSize | None:
    """Risk-based sizing (FR-10.2).

    FR-12.3: NRI accounts have no margin or pledged collateral, so this assumes
    100% cash funding and offers no leverage input.
    """
    if close <= 0 or stop_price >= close or portfolio_value <= 0:
        return None

    risk_pct = risk_per_trade_pct if risk_per_trade_pct is not None else settings.risk_per_trade_pct
    max_weight = (
        max_position_weight if max_position_weight is not None else settings.max_position_weight
    )

    risk_amount = portfolio_value * risk_pct
    quantity = math.floor(risk_amount / (close - stop_price))
    if quantity <= 0:
        return None

    position_value = quantity * close
    max_value = portfolio_value * max_weight
    exceeds = position_value > max_value

    capped = False
    if exceeds:
        # FR-10.2 requires both the warning and the cap.
        quantity = math.floor(max_value / close)
        position_value = quantity * close
        capped = True

    return PositionSize(quantity, position_value, risk_amount, exceeds, capped)


def round_trip_cost_pct(
    expected_gain_pct: float,
    holding_days: int = 30,
    model: CostModel | None = None,
) -> dict[str, float]:
    """Break-even move required to clear all frictions (FR-12.5).

    Expressed so the UI can say "this trade must move X% before it is
    profitable net of costs and withholding", next to the ATR stop distance.
    """
    m = model or CostModel()

    brokerage = m.brokerage_pct * 2
    stt = m.stt_sell_pct
    exchange = m.exchange_txn_pct * 2
    sebi = m.sebi_fee_pct * 2
    stamp = m.stamp_duty_buy_pct
    gst = m.gst_pct * (brokerage + exchange)

    frictions = brokerage + stt + exchange + sebi + stamp + gst

    tax_rate = m.ltcg_effective_rate if holding_days >= 365 else m.stcg_effective_rate
    taxable_gain = max(expected_gain_pct - frictions, 0.0)
    tds = taxable_gain * tax_rate

    # Gross move g must satisfy: (g - frictions) * (1 - tax_rate) > 0, so
    # break-even before tax is simply the friction total; the withholding then
    # scales whatever remains.
    breakeven = frictions / (1 - tax_rate) if tax_rate < 1 else frictions

    return {
        "frictions_pct": frictions,
        "tds_pct": tds,
        "tax_rate": tax_rate,
        "round_trip_cost_pct": frictions + tds,
        "breakeven_move_pct": breakeven,
    }


def earliest_sellable_date(entry_date: date, settlement_days: int = 1) -> date:
    """FR-12.1: NRI equity must be delivery-based — no intraday, no BTST.

    Shares credit to demat on settlement (T+1 under the current NSE cycle), so
    the earliest permissible exit is the session after credit. Weekends are
    skipped here; the caller should re-check against the holiday calendar.
    """
    day = entry_date
    added = 0
    while added < settlement_days:
        day += timedelta(days=1)
        if day.weekday() < 5:
            added += 1
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def days_to_ltcg(entry_date: date, today: date | None = None) -> int:
    """Days remaining until the 12-month long-term threshold (FR-12.6).

    Information only. The UI must never present this as a reason to hold —
    letting a tax tail wag a risk-management dog is a well-known way to turn a
    small loss into a large one.
    """
    today = today or date.today()
    threshold = entry_date.replace(year=entry_date.year + 1)
    return max((threshold - today).days, 0)


def tax_on_gain(gain_inr: float, holding_days: int, model: CostModel | None = None) -> float:
    """TDS withheld on a profitable exit.

    FR-12.7: the resident benefit of setting an unexhausted basic-exemption
    limit against s.111A short-term gains is deliberately not applied — that
    relief is available to residents only, and applying it would understate
    this operator's liability.
    """
    if gain_inr <= 0:
        return 0.0
    m = model or CostModel()
    rate = m.ltcg_effective_rate if holding_days >= 365 else m.stcg_effective_rate
    return gain_inr * rate
