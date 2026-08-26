"""Screen compiler tests (SRS 6.1).

Screen definitions are user-authored and importable from a file (FR-7.4), so
they are untrusted input. These tests assert that field names are whitelisted
and that no literal reaches SQL text.
"""

from __future__ import annotations

import pytest

from alpha500.screens.filter_engine import (
    ScreenDefinitionError,
    compile_screen,
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


def test_momentum_breakdown_is_labelled_as_an_exit_screen():
    """FR-12.2: it must not read as a short-candidate list."""
    description = PRESETS["Momentum Breakdown"]["description"].lower()
    assert "exit" in description
    assert "not a short" in description
