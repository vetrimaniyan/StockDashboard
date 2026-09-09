"""Screen compiler tests (SRS 6.1).

Screen definitions are user-authored and importable from a file (FR-7.4), so
they are untrusted input. These tests assert that field names are whitelisted
and that no literal reaches SQL text.
"""

from __future__ import annotations

from datetime import date

import pytest

from alpha500.screens.filter_engine import (
    ScreenDefinitionError,
    compile_screen,
    run_screen,
    run_screen_counted,
)
from alpha500.screens.presets import PRESETS


def _filters(*conditions, op="AND"):  # type: ignore[no-untyped-def]
    return {"filters": {"op": op, "conditions": list(conditions)}}


# --- operators -----------------------------------------------------------


def test_comparison_binds_the_value_rather_than_inlining_it():
    compiled = compile_screen(
        _filters({"field": "rs_rating", "operator": ">=", "value": 80})
    )
    assert "m.rs_rating >= ?" in compiled.where_sql
    assert 80 in compiled.params
    assert "80" not in compiled.where_sql


def test_between_binds_both_bounds():
    compiled = compile_screen(
        _filters({"field": "rsi_14", "operator": "between", "value": [40, 55]})
    )
    assert "BETWEEN ? AND ?" in compiled.where_sql
    assert compiled.params[:2] == [40, 55]


def test_in_generates_one_placeholder_per_value():
    compiled = compile_screen(
        _filters({"field": "sector", "operator": "in", "value": ["A", "B", "C"]})
    )
    assert compiled.where_sql.count("?") == 3
    assert compiled.params == ["A", "B", "C"]


def test_null_operators_take_no_parameters():
    compiled = compile_screen(
        _filters({"field": "delivery_pct", "operator": "is not null"})
    )
    assert "IS NOT NULL" in compiled.where_sql
    assert compiled.params == []


def test_or_grouping():
    compiled = compile_screen(
        _filters(
            {"field": "momentum_rank", "operator": ">", "value": 250},
            {"field": "rsi_14", "operator": "<", "value": 30},
            op="OR",
        )
    )
    assert " OR " in compiled.where_sql


def test_one_level_of_nesting_is_allowed():
    definition = {
        "filters": {
            "op": "AND",
            "conditions": [
                {"field": "is_eligible", "operator": "=", "value": True},
                {
                    "op": "OR",
                    "conditions": [
                        {"field": "rs_rating", "operator": ">=", "value": 90},
                        {"field": "momentum_rank", "operator": "<=", "value": 10},
                    ],
                },
            ],
        }
    }
    compiled = compile_screen(definition)
    assert " OR " in compiled.where_sql and " AND " in compiled.where_sql


def test_two_levels_of_nesting_are_rejected():
    """FR-7.3: a screen needing deeper nesting is better expressed as two screens."""
    definition = {
        "filters": {
            "op": "AND",
            "conditions": [
                {
                    "op": "OR",
                    "conditions": [
                        {
                            "op": "AND",
                            "conditions": [
                                {"field": "rs_rating", "operator": ">=", "value": 90}
                            ],
                        }
                    ],
                }
            ],
        }
    }
    with pytest.raises(ScreenDefinitionError, match="nesting"):
        compile_screen(definition)


# --- injection safety ----------------------------------------------------


def test_unknown_field_is_rejected():
    with pytest.raises(ScreenDefinitionError, match="unknown or disallowed"):
        compile_screen(_filters({"field": "nonexistent", "operator": ">", "value": 1}))


def test_sql_in_a_field_name_is_rejected_not_escaped():
    """The field name reaches SQL text, so it must be whitelisted outright."""
    for hostile in (
        "close; DROP TABLE ohlcv_daily",
        "1=1 OR close",
        "close--",
        "(SELECT 1)",
    ):
        with pytest.raises(ScreenDefinitionError):
            compile_screen(_filters({"field": hostile, "operator": ">", "value": 1}))


def test_sql_in_a_value_stays_a_parameter():
    """Values are bound, so hostile content is inert data rather than syntax."""
    hostile = "'; DROP TABLE ohlcv_daily; --"
    compiled = compile_screen(
        _filters({"field": "sector", "operator": "=", "value": hostile})
    )
    assert hostile in compiled.params
    assert "DROP" not in compiled.where_sql


def test_sort_field_is_whitelisted_too():
    with pytest.raises(ScreenDefinitionError):
        compile_screen(
            {
                "filters": {"op": "AND", "conditions": []},
                "sort": [{"field": "close; DELETE FROM instruments", "direction": "asc"}],
            }
        )


def test_unsupported_operator_is_rejected():
    with pytest.raises(ScreenDefinitionError, match="unsupported operator"):
        compile_screen(_filters({"field": "close", "operator": "LIKE", "value": "%x%"}))


# --- defaults ------------------------------------------------------------


def test_nulls_sort_last():
    """A null metric is missing information, never the strongest candidate."""
    compiled = compile_screen(
        {
            "filters": {"op": "AND", "conditions": []},
            "sort": [{"field": "momentum_score", "direction": "desc"}],
        }
    )
    assert "NULLS LAST" in compiled.order_sql


def test_eligibility_filter_is_applied_by_default():
    compiled = compile_screen(_filters({"field": "close", "operator": ">", "value": 10}))
    assert "m.is_eligible" in compiled.where_sql


def test_eligibility_can_be_opted_out_for_the_exit_screen():
    """Exit signals must reach held names even if they have become ineligible."""
    compiled = compile_screen(
        {
            "universe": {"exclude_ineligible": False},
            "filters": {
                "op": "AND",
                "conditions": [{"field": "close", "operator": ">", "value": 10}],
            },
        }
    )
    assert "m.is_eligible" not in compiled.where_sql


def test_negative_limit_is_rejected():
    with pytest.raises(ScreenDefinitionError, match="limit"):
        compile_screen({"filters": {"op": "AND", "conditions": []}, "limit": -5})


# --- presets -------------------------------------------------------------


def test_every_preset_compiles():
    for name, definition in PRESETS.items():
        compiled = compile_screen(definition)
        assert compiled.where_sql, f"{name} produced an empty predicate"


def test_approaching_high_excludes_names_that_already_broke_out():
    """"About to break" must stop at the high, not span it.

    Without the strict upper bound the screen would also return everything
    that took the high out today, which is the 52-Week High Breakout screen's
    job and would make this one indistinguishable from it.
    """
    conditions = PRESETS["Approaching High"]["filters"]["conditions"]
    bounds = {
        (c["operator"], c["value"])
        for c in conditions
        if c["field"] == "pct_from_period_high"
    }
    assert (">=", -0.03) in bounds, "lost the 3% proximity floor"
    assert ("<", 0.0) in bounds, "would include names already through the high"


def test_approaching_high_does_not_claim_to_be_an_all_time_high():
    """The stored lookback is whatever was backfilled, so ATH would overstate it.

    history_days reports the real depth per symbol; the description has to
    point at it rather than implying every name reaches back to listing.
    """
    description = PRESETS["Approaching High"]["description"].lower()
    assert "all-time" not in description
    assert "stored history" in description


def test_momentum_breakdown_is_labelled_as_an_exit_screen():
    """FR-12.2: it must not read as a short-candidate list."""
    description = PRESETS["Momentum Breakdown"]["description"].lower()
    assert "exit" in description
    assert "not a short" in description


# --- truncation reporting -------------------------------------------------


def _seed_for_limit(conn, count: int) -> None:
    """``count`` eligible symbols, each with a distinct rs_rating."""
    for i in range(count):
        token = 9000 + i
        conn.execute(
            "INSERT INTO instruments (instrument_token, tradingsymbol, series) "
            "VALUES (?, ?, 'EQ')",
            [token, f"SYM{i:03d}"],
        )
        conn.execute(
            "INSERT INTO metrics_daily (instrument_token, trade_date, rs_rating, "
            "is_eligible) VALUES (?, ?, ?, TRUE)",
            [token, date(2026, 9, 8), 50 + i],
        )


def test_matched_count_reports_the_rows_the_limit_discarded(conn):
    """A capped screen must not look like a complete answer.

    Ten rows back from a screen that matched thirty means something different
    from ten rows back from a screen that matched ten, and row_count alone
    cannot tell them apart.
    """
    _seed_for_limit(conn, 30)
    definition = {
        "filters": {"op": "AND", "conditions": []},
        "sort": [{"field": "rs_rating", "direction": "desc"}],
        "limit": 10,
    }

    rows, matched = run_screen_counted(conn, definition, date(2026, 9, 8))

    assert len(rows) == 10
    assert matched == 30


def test_matched_count_equals_row_count_when_nothing_was_cut(conn):
    _seed_for_limit(conn, 4)
    definition = {"filters": {"op": "AND", "conditions": []}, "limit": 10}

    rows, matched = run_screen_counted(conn, definition, date(2026, 9, 8))

    assert len(rows) == 4
    assert matched == 4


def test_run_screen_still_returns_just_the_rows(conn):
    """The plain entry point keeps its signature; callers were not touched."""
    _seed_for_limit(conn, 3)
    rows = run_screen(
        conn, {"filters": {"op": "AND", "conditions": []}}, date(2026, 9, 8)
    )
    assert isinstance(rows, list)
    assert len(rows) == 3
