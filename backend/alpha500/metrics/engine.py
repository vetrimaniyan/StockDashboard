"""Metric engine orchestration.

Loads adjusted price history, runs the per-symbol pass, then the
cross-sectional pass, then writes ``metrics_daily``.

AR-2/AR-4: reads only stored raw data, needs no network, and is bit-identical
across runs given the same history.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Sequence

import duckdb
import numpy as np
from numpy.typing import NDArray

from alpha500.config import settings
from alpha500.metrics import cross_section as xs
from alpha500.metrics import periods as p
from alpha500.metrics.fib import FIB_COLUMNS
from alpha500.metrics.fingerprint import engine_fingerprint
from alpha500.metrics.series import SeriesMetrics, compute_series_metrics

# Column order for the metrics_daily write. Kept explicit so a schema change
# cannot silently shift values into the wrong column.
METRIC_COLUMNS: tuple[str, ...] = (
    "ret_1d", "ret_1w", "ret_2w", "ret_3w", "ret_1m", "ret_2m",
    "ret_3m", "ret_3m_2m", "ret_6m", "ret_9m", "ret_12m", "ret_12m_1m",
    "rs_1m", "rs_3m", "rs_6m", "rs_12m", "rs_rating",
    "sma_20", "sma_50", "sma_100", "sma_150", "sma_200", "ema_21", "ema_50",
    "sma_200_slope_1m", "ma_alignment", "is_long_term_uptrend",
    "high_52w", "low_52w", "pct_from_52w_high", "pct_above_52w_low",
    "range_position_52w", "days_since_52w_high",
    "high_period", "pct_from_period_high",
    "exp_reg_slope_90", "exp_reg_r2_90", "momentum_score", "momentum_rank", "composite_z",
    "atr_14", "atr_pct_14", "stdev_21", "stdev_63", "adr_pct_20",
    "vol_sma_20", "vol_sma_50", "rel_volume", "turnover_20d_median", "delivery_pct_sma_20",
    "rsi_14", "adx_14", "macd", "macd_signal", "macd_hist",
    "is_52w_high_breakout", "is_n_day_breakout_20", "is_n_day_breakout_50",
    "is_in_base", "base_depth_pct", "base_length_days",
    "support_level", "support_distance_pct", "is_at_support",
    "pullback_from_high_pct", "reversal_score", "is_reversal",
    "is_pullback_reversal",
    "is_trend_template", "trend_template_score", "is_pullback", "gap_disqualified",
    "history_days", "is_eligible", "ineligible_reason",
    # FR-17 Fibonacci retracement zone.
    *FIB_COLUMNS, "fib_setup_score",
)

_INT_COLUMNS = frozenset(
    {
        "rs_rating", "days_since_52w_high", "momentum_rank", "vol_sma_20", "vol_sma_50",
        "base_length_days", "trend_template_score", "history_days",
        "reversal_score", "fib_leg_sessions", "fib_sessions_in_zone",
    }
)
# The only free-text metric: which rule held a symbol out of screen results.
_TEXT_COLUMNS = frozenset(
    {
        "ineligible_reason",
        # FR-17.8/17.3: string-valued, so they must reach the text
        # formatter. A string through the numeric one renders NaN, which
        # is the FR-15.1 bug.
        "fib_zone_status", "fib_zone_entry_type", "fib_exclusion_reason",
    }
)
# Date-valued metrics. Stored as DATE so the chart overlay and the
# point-in-time guarantee can both read them without parsing.
_DATE_COLUMNS = frozenset(
    {"fib_leg_low_date", "fib_leg_high_date", "fib_leg_confirmed_date"}
)
_BOOL_COLUMNS = frozenset(
    {
        "ma_alignment", "is_52w_high_breakout", "is_n_day_breakout_20",
        "is_n_day_breakout_50", "is_in_base", "is_trend_template", "is_pullback",
        "is_at_support", "is_reversal", "is_pullback_reversal",
        "gap_disqualified", "is_eligible", "in_fib_zone", "is_fib_reversal_bar",
        "is_long_term_uptrend",
    }
)


def _load_prices(
    conn: duckdb.DuckDBPyConnection, tokens: Sequence[int], as_of: date
) -> dict[int, dict[str, NDArray[Any]]]:
    """Adjusted OHLCV per instrument, oldest first, up to and including ``as_of``."""
    if not tokens:
        return {}
    import pyarrow as pa

    conn.register("_tok_src", pa.table({"instrument_token": pa.array(list(tokens), pa.int64())}))
    conn.execute("CREATE OR REPLACE TEMP TABLE _tok AS SELECT * FROM _tok_src")
    conn.unregister("_tok_src")

    table = conn.execute(
        """
        SELECT o.instrument_token, o.trade_date,
               o.open  * o.adj_factor AS open,
               o.high  * o.adj_factor AS high,
               o.low   * o.adj_factor AS low,
               o.close * o.adj_factor AS close,
               o.volume / o.adj_factor AS volume,
               o.delivery_pct
          FROM ohlcv_daily o
          JOIN _tok t ON t.instrument_token = o.instrument_token
         WHERE o.trade_date <= ?
         ORDER BY o.instrument_token, o.trade_date
        """,
        [as_of],
    ).to_arrow_table()

    out: dict[int, dict[str, NDArray[Any]]] = {}
    if table.num_rows == 0:
        return out

    tokens_col = table.column("instrument_token").to_numpy(zero_copy_only=False)
    columns: dict[str, NDArray[Any]] = {
        "trade_date": np.array(table.column("trade_date").to_pylist(), dtype=object)
    }
    for name in ("open", "high", "low", "close", "volume", "delivery_pct"):
        columns[name] = table.column(name).to_numpy(zero_copy_only=False).astype(np.float64)

    # Rows arrive grouped by token, so split on the boundaries rather than
    # filtering the full table once per symbol.
    boundaries = np.flatnonzero(np.diff(tokens_col)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(tokens_col)]))

    for start, end in zip(starts, ends):
        out[int(tokens_col[start])] = {
            name: values[start:end] for name, values in columns.items()
        }
    return out


def _index_returns(
    conn: duckdb.DuckDBPyConnection, index_name: str, as_of: date
) -> dict[int, float | None]:
    rows = conn.execute(
        """
        SELECT close FROM index_ohlcv_daily
         WHERE index_name = ? AND trade_date <= ?
         ORDER BY trade_date
        """,
        [index_name, as_of],
    ).fetchall()
    closes = np.array([r[0] for r in rows], dtype=np.float64)
    out: dict[int, float | None] = {}
    for window in (p.MONTH, p.QUARTER, p.HALF_YEAR, p.YEAR):
        if closes.size > window and closes[-window - 1] > 0:
            out[window] = float(closes[-1] / closes[-window - 1] - 1.0)
        else:
            out[window] = None
    return out


def compute_metrics_for_date(
    conn: duckdb.DuckDBPyConnection,
    as_of: date,
    index_name: str | None = None,
    excluded_symbols: set[str] | None = None,
) -> int:
    """Compute and persist ``metrics_daily`` for one session. Returns row count."""
    index_name = index_name or settings.index_name

    universe = conn.execute(
        """
        SELECT i.instrument_token, i.tradingsymbol, COALESCE(i.series, 'EQ')
          FROM instruments i
          JOIN index_membership m ON m.instrument_token = i.instrument_token
         WHERE m.index_name = ? AND m.valid_to IS NULL
         ORDER BY i.tradingsymbol
        """,
        [index_name],
    ).fetchall()
    if not universe:
        return 0

    tokens = [int(r[0]) for r in universe]
    symbols = [str(r[1]) for r in universe]
    series_codes = [str(r[2]) for r in universe]

    prices = _load_prices(conn, tokens, as_of)
    idx_returns = _index_returns(conn, index_name, as_of)

    latest: dict[str, list[Any]] = {name: [] for name in METRIC_COLUMNS}
    latest["trend_template_partial"] = []
    latest["close_adj"] = []
    kept_tokens: list[int] = []
    kept_symbols: list[str] = []
    kept_series: list[str] = []

    for token, symbol, series_code in zip(tokens, symbols, series_codes):
        data = prices.get(token)
        if data is None or data["close"].size == 0:
            continue
        # The metric row belongs to as_of only if the symbol actually traded then.
        if data["trade_date"][-1] != as_of:
            continue

        computed = compute_series_metrics(
            trade_date=data["trade_date"],
            open_=data["open"].astype(np.float64),
            high=data["high"].astype(np.float64),
            low=data["low"].astype(np.float64),
            close=data["close"].astype(np.float64),
            volume=data["volume"].astype(np.float64),
            delivery_pct=data["delivery_pct"].astype(np.float64),
        )
        kept_tokens.append(token)
        kept_symbols.append(symbol)
        kept_series.append(series_code)
        _append_last(latest, computed)

    if not kept_tokens:
        return 0

    arrays = {name: np.array(values, dtype=object) for name, values in latest.items()}
    _finalise_cross_section(arrays, kept_symbols, kept_series, idx_returns, excluded_symbols)

    return _write_metrics(conn, as_of, kept_tokens, arrays)


def _append_last(target: dict[str, list[Any]], computed: SeriesMetrics) -> None:
    for name in target:
        column = computed.columns.get(name)
        target[name].append(column[-1] if column is not None and column.size else None)


def _as_float(values: NDArray[Any]) -> NDArray[np.float64]:
    return np.array(
        [np.nan if v is None else float(v) for v in values], dtype=np.float64
    )


def _finalise_cross_section(
    arrays: dict[str, NDArray[Any]],
    symbols: list[str],
    series_codes: list[str],
    idx_returns: dict[int, float | None],
    excluded_symbols: set[str] | None,
) -> None:
    history_days = _as_float(arrays["history_days"])
    turnover = _as_float(arrays["turnover_20d_median"])

    eligible, reasons = xs.eligibility(
        history_days=history_days,
        turnover_20d_median=turnover,
        series=series_codes,
        excluded_symbols=excluded_symbols,
        symbols=symbols,
    )
    arrays["is_eligible"] = np.array(eligible, dtype=object)
    # FR-1.5: a symbol held out of screen results must be explainable, not
    # merely absent. The reason is computed here anyway; storing it is what
    # makes "why is this stock never in my results" answerable in the UI.
    arrays["ineligible_reason"] = np.array(
        [r or None for r in reasons], dtype=object
    )

    # Relative strength against the index (FR-6.3).
    for label, window in (("1m", p.MONTH), ("3m", p.QUARTER),
                          ("6m", p.HALF_YEAR), ("12m", p.YEAR)):
        stock_ret = _as_float(arrays[f"ret_{label}"])
        arrays[f"rs_{label}"] = xs.relative_strength(stock_ret, idx_returns.get(window))

    _raw, rating = xs.rs_rating(
        _as_float(arrays["ret_3m"]),
        _as_float(arrays["ret_6m"]),
        _as_float(arrays["ret_9m"]),
        _as_float(arrays["ret_12m"]),
        eligible,
    )
    arrays["rs_rating"] = rating

    score, is_template = xs.finalise_trend_template(
        _as_float(arrays["trend_template_partial"]), rating
    )
    arrays["trend_template_score"] = score
    arrays["is_trend_template"] = is_template

    arrays["is_pullback"] = xs.detect_pullback(
        ma_alignment=arrays["ma_alignment"],
        is_trend_template=is_template,
        close=_as_float(arrays["close_adj"]),
        ema_21=_as_float(arrays["ema_21"]),
        sma_50=_as_float(arrays["sma_50"]),
        ret_1w=_as_float(arrays["ret_1w"]),
        rsi_14=_as_float(arrays["rsi_14"]),
    )

    momentum = _as_float(arrays["momentum_score"])
    arrays["momentum_score"] = momentum
    arrays["momentum_rank"] = xs.momentum_rank(momentum, eligible)

    # FR-17.6 ranking. A thinner pullback scores higher, so the dry-up ratio
    # enters inverted; the retracement ratio is absent on purpose.
    dryup = _as_float(arrays["vol_dryup_ratio"])
    with np.errstate(divide="ignore", invalid="ignore"):
        inv_dryup = np.where(dryup > 0, 1.0 / dryup, np.nan)
    arrays["fib_setup_score"] = xs.fib_setup_score(
        {
            "momentum_score": momentum,
            "rs_rating": _as_float(rating),
            "inv_vol_dryup": inv_dryup,
            "rel_volume": _as_float(arrays["rel_volume"]),
            "fib_sessions_in_zone": _as_float(arrays["fib_sessions_in_zone"]),
        },
        eligible=eligible,
    )

    arrays["composite_z"] = xs.composite_z(
        components={
            "momentum_score": momentum,
            "ret_12m_1m": _as_float(arrays["ret_12m_1m"]),
            "rs_rating": rating,
            "range_position_52w": _as_float(arrays["range_position_52w"]),
            "atr_pct_14": _as_float(arrays["atr_pct_14"]),
            "rel_volume": _as_float(arrays["rel_volume"]),
        },
        weights=xs.CompositeWeights.from_settings(),
        eligible=eligible,
    )


def _coerce(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in _DATE_COLUMNS:
        return value if isinstance(value, date) else None
    if name in _TEXT_COLUMNS:
        text = str(value).strip()
        # An eligible row has no reason; store absence as NULL rather than "".
        return text or None
    if name in _BOOL_COLUMNS:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        return None if not np.isfinite(float(value)) else bool(value)
    numeric = float(value)
    if not np.isfinite(numeric):
        return None
    return int(round(numeric)) if name in _INT_COLUMNS else numeric


def _write_metrics(
    conn: duckdb.DuckDBPyConnection,
    as_of: date,
    tokens: list[int],
    arrays: dict[str, NDArray[Any]],
) -> int:
    rows = []
    for i, token in enumerate(tokens):
        row: list[Any] = [token, as_of]
        for name in METRIC_COLUMNS:
            row.append(_coerce(name, arrays[name][i]))
        rows.append(tuple(row))

    placeholders = ",".join(["?"] * (2 + len(METRIC_COLUMNS)))
    columns = ", ".join(("instrument_token", "trade_date", *METRIC_COLUMNS))

    # AR-3: delete-then-insert for the target date keeps the write idempotent.
    conn.execute("DELETE FROM metrics_daily WHERE trade_date = ?", [as_of])
    conn.executemany(
        f"INSERT INTO metrics_daily ({columns}) VALUES ({placeholders})", rows
    )

    # Stamp which build produced these numbers, so serving metrics from a
    # since-edited engine is detectable rather than silent.
    conn.execute(
        "INSERT OR REPLACE INTO metrics_meta VALUES (?,?,?,?)",
        [as_of, engine_fingerprint(), datetime.now(timezone.utc), len(rows)],
    )
    return len(rows)
