"""Screen definition compiler (SRS 6.1).

Compiles the FR-7.4 JSON schema into parameterised SQL over ``metrics_daily``
joined to ``instruments``.

Screen definitions are user-authored and importable from a file, so they are
untrusted input. Field names are whitelisted against the known column set and
every literal is bound as a parameter — no value from a definition is ever
interpolated into SQL text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Sequence

import duckdb

from alpha500.metrics.engine import METRIC_COLUMNS

INSTRUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {"tradingsymbol", "name", "isin", "series", "industry", "sector", "basic_industry"}
)
PRICE_FIELDS: Final[frozenset[str]] = frozenset(
    {"close", "open", "high", "low", "volume", "delivery_pct", "traded_value"}
)
ALLOWED_FIELDS: Final[frozenset[str]] = (
    frozenset(METRIC_COLUMNS) | INSTRUMENT_FIELDS | PRICE_FIELDS
)

_COMPARISON: Final[dict[str, str]] = {
    ">": ">", ">=": ">=", "<": "<", "<=": "<=", "=": "=", "!=": "!=",
}
_RANK_OPERATORS: Final[frozenset[str]] = frozenset({"top n", "bottom n", "top n%"})


class ScreenDefinitionError(ValueError):
    """The screen definition is malformed or references an unknown field."""


@dataclass(slots=True)
class CompiledScreen:
    where_sql: str
    params: list[Any]
    order_sql: str
    limit: int | None
    rank_clauses: list[tuple[str, str, float]]


def _qualify(field: str) -> str:
    if field in INSTRUMENT_FIELDS:
        return f"i.{field}"
    if field in PRICE_FIELDS:
        return f"o.{field}"
    return f"m.{field}"


def _validate_field(field: Any) -> str:
    if not isinstance(field, str) or field not in ALLOWED_FIELDS:
        raise ScreenDefinitionError(f"unknown or disallowed field: {field!r}")
    return field


def _compile_condition(
    condition: dict[str, Any], params: list[Any], rank_clauses: list[tuple[str, str, float]]
) -> str:
    field = _validate_field(condition.get("field"))
    operator = str(condition.get("operator", "")).strip().lower()
    value = condition.get("value")
    column = _qualify(field)

    if operator in _COMPARISON:
        params.append(value)
        return f"{column} {_COMPARISON[operator]} ?"

    if operator == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ScreenDefinitionError("'between' needs a two-element value")
        params.extend(value)
        return f"{column} BETWEEN ? AND ?"

    if operator in {"in", "not in"}:
        if not isinstance(value, (list, tuple)) or not value:
            raise ScreenDefinitionError(f"'{operator}' needs a non-empty list")
        placeholders = ",".join(["?"] * len(value))
        params.extend(value)
        negate = "NOT " if operator == "not in" else ""
        return f"{column} {negate}IN ({placeholders})"

    if operator == "is null":
        return f"{column} IS NULL"
    if operator == "is not null":
        return f"{column} IS NOT NULL"

    if operator in _RANK_OPERATORS:
        try:
            amount = float(value)
        except (TypeError, ValueError) as exc:
            raise ScreenDefinitionError(f"'{operator}' needs a numeric value") from exc
        # Applied as a post-filter over the ranked result, not as SQL here.
        rank_clauses.append((field, operator, amount))
        return "TRUE"

    raise ScreenDefinitionError(f"unsupported operator: {operator!r}")


def _compile_group(
    group: dict[str, Any],
    params: list[Any],
    rank_clauses: list[tuple[str, str, float]],
    depth: int = 0,
) -> str:
    if depth > 1:
        # FR-7.3: one level of nesting. A screen needing more is two screens.
        raise ScreenDefinitionError("filter nesting deeper than one level is not supported")

    op = str(group.get("op", "AND")).strip().upper()
    if op not in {"AND", "OR"}:
        raise ScreenDefinitionError(f"unsupported group operator: {op!r}")

    conditions = group.get("conditions") or []
    if not isinstance(conditions, list) or not conditions:
        return "TRUE"

    parts: list[str] = []
    for item in conditions:
        if not isinstance(item, dict):
            raise ScreenDefinitionError("each condition must be an object")
        if "conditions" in item:
            parts.append(f"({_compile_group(item, params, rank_clauses, depth + 1)})")
        else:
            parts.append(_compile_condition(item, params, rank_clauses))

    return f" {op} ".join(parts)


def compile_screen(definition: dict[str, Any]) -> CompiledScreen:
    params: list[Any] = []
    rank_clauses: list[tuple[str, str, float]] = []
    where_sql = _compile_group(definition.get("filters") or {}, params, rank_clauses)

    universe = definition.get("universe") or {}
    if universe.get("exclude_ineligible", True):
        where_sql = f"({where_sql}) AND m.is_eligible"

    sort_spec = definition.get("sort") or [
        {"field": "momentum_score", "direction": "desc"}
    ]
    order_parts: list[str] = []
    for entry in sort_spec:
        field = _validate_field(entry.get("field"))
        direction = "DESC" if str(entry.get("direction", "desc")).lower() == "desc" else "ASC"
        # Nulls always sort last: a null metric is missing information, never
        # the strongest candidate.
        order_parts.append(f"{_qualify(field)} {direction} NULLS LAST")
    order_sql = ", ".join(order_parts)

    limit = definition.get("limit")
    if limit is not None:
        limit = int(limit)
        if limit <= 0:
            raise ScreenDefinitionError("limit must be positive")

    return CompiledScreen(where_sql, params, order_sql, limit, rank_clauses)


SELECT_COLUMNS: Final[str] = """
    i.tradingsymbol, i.name, i.sector, i.industry, i.series,
    m.instrument_token, m.trade_date,
    o.close, o.volume, o.delivery_pct,
    """ + ", ".join(f"m.{c}" for c in METRIC_COLUMNS)


def run_screen(
    conn: duckdb.DuckDBPyConnection,
    definition: dict[str, Any],
    as_of: date,
) -> list[dict[str, Any]]:
    compiled = compile_screen(definition)

    sql = f"""
        SELECT {SELECT_COLUMNS}
          FROM metrics_daily m
          JOIN instruments i ON i.instrument_token = m.instrument_token
          LEFT JOIN ohlcv_daily o
                 ON o.instrument_token = m.instrument_token AND o.trade_date = m.trade_date
         WHERE m.trade_date = ? AND ({compiled.where_sql})
         ORDER BY {compiled.order_sql}
    """
    cursor = conn.execute(sql, [as_of, *compiled.params])
    columns = [d[0] for d in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    rows = _apply_rank_clauses(rows, compiled.rank_clauses)
    if compiled.limit is not None:
        rows = rows[: compiled.limit]
    return rows


def _apply_rank_clauses(
    rows: list[dict[str, Any]], clauses: Sequence[tuple[str, str, float]]
) -> list[dict[str, Any]]:
    for field, operator, amount in clauses:
        present = [r for r in rows if r.get(field) is not None]
        if not present:
            return []
        descending = operator in {"top n", "top n%"}
        present.sort(key=lambda r: r[field], reverse=descending)
        count = (
            max(1, round(len(present) * amount / 100.0))
            if operator == "top n%"
            else int(amount)
        )
        keep = {id(r) for r in present[:count]}
        rows = [r for r in rows if id(r) in keep]
    return rows
