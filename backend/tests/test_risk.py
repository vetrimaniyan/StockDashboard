"""Position sizing, stops and round-trip cost (SRS sections 9 and 11.2)."""

from __future__ import annotations

from datetime import date

import pytest

from alpha500 import risk


# --- stops (FR-10.1) -----------------------------------------------------


def test_atr_stop_is_k_multiples_below_close():
    """stop = C_0 - (k x ATR_14), default k = 2.0.

    Close 100, ATR 5, k 2 -> stop 90, distance 10%.
    """
    s = risk.suggest_stop(close=100.0, atr_14=5.0, k=2.0)
    assert s.atr_stop_price == pytest.approx(90.0)
    assert s.atr_stop_distance_pct == pytest.approx(0.10)


def test_wider_of_the_two_stops_is_flagged():
    """FR-10.1 requires both stops shown, with the wider one identified."""
    wider_structural = risk.suggest_stop(close=100.0, atr_14=5.0, base_low=85.0, k=2.0)
    assert wider_structural.wider_stop == "structural"

    wider_atr = risk.suggest_stop(close=100.0, atr_14=5.0, base_low=95.0, k=2.0)
    assert wider_atr.wider_stop == "atr"


def test_structural_stop_above_close_is_rejected():
    """A stop above the entry is not a stop."""
    s = risk.suggest_stop(close=100.0, atr_14=5.0, base_low=120.0)
    assert s.structural_stop_price is None


def test_missing_atr_yields_no_atr_stop():
    s = risk.suggest_stop(close=100.0, atr_14=None)
    assert s.atr_stop_price is None
    assert s.atr_stop_distance_pct is None


# --- sizing (FR-10.2) ----------------------------------------------------


def test_position_size_from_risk_budget():
    """risk_amount = portfolio x risk_pct; qty = floor(risk / (close - stop)).

    1,000,000 x 0.75% = 7,500 risk. Close 100, stop 90 -> 10 per share.
    7500 / 10 = 750 shares, position value 75,000.
    """
    sized = risk.size_position(
        close=100.0, stop_price=90.0, portfolio_value=1_000_000.0,
        risk_per_trade_pct=0.0075, max_position_weight=0.10,
    )
    assert sized is not None
    assert sized.risk_amount == pytest.approx(7500.0)
    # 75,000 is exactly 7.5% of the portfolio, inside the 10% cap.
    assert sized.quantity == 750
    assert sized.position_value == pytest.approx(75_000.0)
    assert not sized.exceeds_max_weight


def test_tight_stop_is_capped_at_max_position_weight():
    """FR-10.2 requires both a warning and a cap.

    A 1% stop distance would size to 750,000 on a 1,000,000 portfolio — 75% of
    capital on one name. The cap brings it back to the 10% ceiling.
    """
    sized = risk.size_position(
        close=100.0, stop_price=99.0, portfolio_value=1_000_000.0,
        risk_per_trade_pct=0.0075, max_position_weight=0.10,
    )
    assert sized is not None
    assert sized.exceeds_max_weight
    assert sized.capped_at_max_weight
    assert sized.position_value <= 100_000.0 + 1e-6


def test_stop_at_or_above_entry_yields_no_size():
    assert risk.size_position(100.0, 100.0, 1_000_000.0) is None
    assert risk.size_position(100.0, 105.0, 1_000_000.0) is None


def test_no_leverage_input_exists():
    """FR-12.3: NRI accounts have no margin or pledged collateral.

    Sizing must assume 100% cash funding, so there is deliberately no
    leverage parameter to pass.
    """
    import inspect

    params = set(inspect.signature(risk.size_position).parameters)
    assert not params & {"leverage", "margin", "multiplier"}


# --- round-trip cost (FR-12.5) ------------------------------------------


def test_round_trip_cost_includes_every_component():
    out = risk.round_trip_cost_pct(expected_gain_pct=0.10, holding_days=30)
    assert out["frictions_pct"] > 0
    assert out["round_trip_cost_pct"] > out["frictions_pct"], "TDS must be included"


def test_breakeven_is_frictions_alone_not_inflated_by_tax():
    """TDS is withheld on the gain, so it cannot raise the break-even point.

    Below break-even there is no gain to withhold from. Conflating the two
    made the UI show a round-trip cost larger than the move needed to clear
    it, which reads as a contradiction.
    """
    out = risk.round_trip_cost_pct(expected_gain_pct=0.10, holding_days=30)
    assert out["breakeven_move_pct"] == pytest.approx(out["frictions_pct"])
    assert out["breakeven_move_pct"] < out["round_trip_cost_pct"]


def test_breakeven_does_not_move_with_the_expected_gain():
    """The threshold is a property of the frictions, not of the hoped-for win."""
    small = risk.round_trip_cost_pct(0.02, 30)
    large = risk.round_trip_cost_pct(0.50, 30)
    assert small["breakeven_move_pct"] == pytest.approx(large["breakeven_move_pct"])
    assert large["round_trip_cost_pct"] > small["round_trip_cost_pct"]


def test_net_gain_is_what_is_left_after_costs_and_withholding():
    out = risk.round_trip_cost_pct(0.10, holding_days=30)
    assert out["net_gain_pct"] == pytest.approx(
        0.10 - out["frictions_pct"] - out["tds_pct"]
    )
    assert out["net_gain_pct"] < 0.10


def test_a_move_below_breakeven_yields_no_tax_and_no_net_gain():
    out = risk.round_trip_cost_pct(0.0005, holding_days=30)
    assert out["tds_pct"] == 0.0
    assert out["net_gain_pct"] == 0.0


def test_short_holding_uses_the_stcg_rate():
    """FR-12.4: under 12 months is section 111A, ~23.92% effective."""
    out = risk.round_trip_cost_pct(0.10, holding_days=30)
    assert out["tax_rate"] == pytest.approx(0.2392)


def test_long_holding_uses_the_ltcg_rate():
    """Over 12 months is section 112A, ~14.95% effective."""
    out = risk.round_trip_cost_pct(0.10, holding_days=400)
    assert out["tax_rate"] == pytest.approx(0.1495)


def test_tax_drag_makes_short_holds_more_expensive():
    """The whole point of the capital-velocity model in FR-12.4.

    Frictions are identical either way; the withholding is what differs, so
    the same gross win nets less on a short hold.
    """
    short = risk.round_trip_cost_pct(0.10, holding_days=30)
    long = risk.round_trip_cost_pct(0.10, holding_days=400)
    assert short["round_trip_cost_pct"] > long["round_trip_cost_pct"]
    assert short["net_gain_pct"] < long["net_gain_pct"]


def test_stt_is_charged_on_the_sell_side_only():
    model = risk.CostModel()
    out = risk.round_trip_cost_pct(0.10, 30, model)
    # STT alone is 0.1%; the friction total must at least cover it.
    assert out["frictions_pct"] >= model.stt_sell_pct


# --- NRI trading constraints (FR-12.1) ----------------------------------


def test_earliest_sellable_date_is_after_settlement():
    """FR-12.1: NRI equity is delivery-based; no intraday, no BTST.

    Shares credit on T+1, so a Monday entry cannot be exited before Tuesday.
    """
    monday = date(2026, 8, 24)
    assert monday.weekday() == 0
    assert risk.earliest_sellable_date(monday) == date(2026, 8, 25)


def test_earliest_sellable_date_skips_the_weekend():
    """A Friday entry settles Monday, not Saturday."""
    friday = date(2026, 8, 28)
    assert friday.weekday() == 4
    sellable = risk.earliest_sellable_date(friday)
    assert sellable.weekday() < 5
    assert sellable == date(2026, 8, 31)


def test_earliest_sellable_is_never_the_entry_day():
    """Same-day round trips are not permitted on this account type."""
    for day in (date(2026, 8, 24), date(2026, 8, 26), date(2026, 8, 28)):
        assert risk.earliest_sellable_date(day) > day


# --- holding period awareness (FR-12.6) ---------------------------------


def test_days_to_ltcg_counts_down_to_the_twelve_month_threshold():
    entry = date(2026, 1, 1)
    assert risk.days_to_ltcg(entry, today=date(2026, 7, 1)) == 184
    assert risk.days_to_ltcg(entry, today=date(2027, 1, 1)) == 0
    assert risk.days_to_ltcg(entry, today=date(2027, 6, 1)) == 0


# --- tax on gain (FR-12.7) ----------------------------------------------


def test_no_tax_on_a_loss():
    assert risk.tax_on_gain(-5000.0, holding_days=30) == 0.0


def test_short_term_gain_is_taxed_at_the_higher_rate():
    short = risk.tax_on_gain(100_000.0, holding_days=30)
    long = risk.tax_on_gain(100_000.0, holding_days=400)
    assert short > long
    assert short == pytest.approx(23_920.0)
    assert long == pytest.approx(14_950.0)


def test_basic_exemption_offset_is_not_applied():
    """FR-12.7: that relief is available to residents only.

    Applying it would understate this operator's liability, so tax on a small
    gain must still be the full rate rather than zero.
    """
    assert risk.tax_on_gain(1000.0, holding_days=30) == pytest.approx(239.2)
