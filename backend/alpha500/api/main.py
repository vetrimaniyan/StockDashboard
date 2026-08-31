"""FastAPI service layer.

NFR-4.1: binds to 127.0.0.1 by default. This is a single-user, self-hosted
tool and market-data licensing does not permit redistribution.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from alpha500 import risk
from alpha500.api.schemas import (
    BacktestAvailability,
    BacktestRequest,
    Breadth,
    DashboardResponse,
    DataStatus,
    MarketRegime,
    MetricDefinition,
    PresetSummary,
    RiskSuggestion,
    ScreenResponse,
    SectorPerformance,
    StockDetail,
    UniverseChange,
)
from alpha500.config import settings
from alpha500.db.connection import (
    DatabaseBusyError,
    analytical,
    app as app_db,
    init_databases,
)
from alpha500.metrics import registry
from alpha500.metrics.engine import METRIC_COLUMNS
from alpha500.metrics.fingerprint import engine_fingerprint
from alpha500.mktcal import calendar as cal
from alpha500.screens.filter_engine import ScreenDefinitionError, run_screen
from alpha500.screens.presets import (
    ALL_CONSTITUENTS,
    MOMENTUM_BREAKDOWN,
    PULLBACK_REVERSAL,
    PRESETS,
    breadth,
    get_preset,
    market_regime,
)

IST = ZoneInfo("Asia/Kolkata")
# The pipeline's scheduled slot (FR-5.1). Before this, today's EOD data does
# not yet exist upstream and its absence is not a fault.
# Re-exported: the cutoff is calendar logic, but callers import it from here.
PUBLISH_CUTOFF_IST = cal.PUBLISH_CUTOFF_IST


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_databases()
    yield


app = FastAPI(
    title="Alpha-500",
    description="NSE momentum & swing-trading dashboard. Decision support only — "
                "this application places no orders in any phase.",
    version="0.1.0",
    lifespan=lifespan,
)

# The SPA runs on the Vite dev server during development; both are loopback.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(DatabaseBusyError)
async def _busy_handler(_request: Request, exc: DatabaseBusyError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc), "retry": True, "reason": "pipeline_running"},
    )


# --- shared helpers ------------------------------------------------------


def _expected_session(conn: Any, now: datetime | None = None) -> date:
    """See ``cal.expected_session``. Kept as a name the handlers already use."""
    return cal.expected_session(conn, now)


def _data_status() -> DataStatus:
    """FR-8.9: the staleness indicator carries a reason, not just a date."""
    with analytical(read_only=True) as conn:
        row = conn.execute("SELECT max(trade_date) FROM metrics_daily").fetchone()
        data_as_of = row[0] if row else None
        expected = _expected_session(conn)

        stamped = conn.execute(
            "SELECT engine_fingerprint FROM metrics_meta WHERE trade_date = ?",
            [data_as_of],
        ).fetchone() if data_as_of else None

    # A fingerprint that predates the current engine means the served numbers
    # came from code no longer in the tree.
    engine_stale = bool(stamped) and stamped[0] != engine_fingerprint()
    unstamped = data_as_of is not None and not stamped

    last_status: str | None = None
    last_at: str | None = None
    with app_db() as conn:
        run = conn.execute(
            "SELECT status, ended_at FROM job_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if run:
            last_status, last_at = run["status"], run["ended_at"]

    if data_as_of is None:
        return DataStatus(
            data_as_of=None, latest_session=expected, is_stale=True,
            reason="No data ingested yet — run the pipeline.",
            last_run_status=last_status, last_run_at=last_at,
        )

    stale = data_as_of < expected
    reason: str | None = None
    if stale:
        gap = (expected - data_as_of).days
        if last_status == "FAILED":
            reason = f"Pipeline failed; showing data from {data_as_of} ({gap}d old)."
        else:
            reason = (
                f"Latest completed session is {expected}; served data is from "
                f"{data_as_of}. Pipeline has not yet run for that session."
            )

    if engine_stale or unstamped:
        engine_note = (
            "Metrics were computed by a different build of the metric engine "
            "than the one now installed. Run 'alpha500 rebuild' — until then "
            "these rankings are not reproducible from the current code."
            if engine_stale
            else "Metrics predate engine-version stamping; run 'alpha500 rebuild'."
        )
        reason = f"{reason} {engine_note}" if reason else engine_note

    return DataStatus(
        data_as_of=data_as_of, latest_session=expected,
        is_stale=stale or engine_stale or unstamped,
        reason=reason, last_run_status=last_status, last_run_at=last_at,
        engine_stale=engine_stale or unstamped,
    )


def _resolve_as_of(requested: date | None) -> date:
    if requested is not None:
        return requested
    with analytical(read_only=True) as conn:
        row = conn.execute("SELECT max(trade_date) FROM metrics_daily").fetchone()
    if not row or row[0] is None:
        raise HTTPException(404, "No metrics computed yet. Run the pipeline first.")
    return row[0]


# --- endpoints -----------------------------------------------------------


@app.get("/api/status", response_model=DataStatus)
def get_status() -> DataStatus:
    return _data_status()


@app.get("/api/metrics/definitions", response_model=list[MetricDefinition])
def get_metric_definitions() -> list[MetricDefinition]:
    """FR-8.10: every derived metric exposes its formula."""
    return [
        MetricDefinition(
            name=m.name, label=m.label, formula=m.formula,
            description=m.description, group=m.group, unit=m.unit,
        )
        for m in registry.REGISTRY
    ]


@app.get("/api/presets", response_model=list[PresetSummary])
def get_presets() -> list[PresetSummary]:
    return [
        PresetSummary(
            name=name,
            description=str(definition.get("description", "")),
            is_exit_screen=name == MOMENTUM_BREAKDOWN,
            is_universe=name == ALL_CONSTITUENTS,
        )
        for name, definition in PRESETS.items()
    ]


@app.get("/api/screen/{preset_name}", response_model=ScreenResponse)
def get_preset_screen(preset_name: str, as_of: date | None = None) -> ScreenResponse:
    try:
        definition = get_preset(preset_name)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc

    resolved = _resolve_as_of(as_of)
    with analytical(read_only=True) as conn:
        rows = run_screen(conn, definition, resolved)

    return ScreenResponse(
        screen_name=preset_name,
        version=int(definition.get("version", 1)),
        definition=definition,
        data_as_of=resolved,
        status=_data_status(),
        row_count=len(rows),
        rows=rows,
    )


@app.post("/api/screen", response_model=ScreenResponse)
def post_custom_screen(
    definition: dict[str, Any], as_of: date | None = None
) -> ScreenResponse:
    resolved = _resolve_as_of(as_of)
    try:
        with analytical(read_only=True) as conn:
            rows = run_screen(conn, definition, resolved)
    except ScreenDefinitionError as exc:
        raise HTTPException(400, str(exc)) from exc

    return ScreenResponse(
        screen_name=str(definition.get("name", "Custom screen")),
        version=int(definition.get("version", 1)),
        definition=definition,
        data_as_of=resolved,
        status=_data_status(),
        row_count=len(rows),
        rows=rows,
    )


@app.get("/api/dashboard", response_model=DashboardResponse)
def get_dashboard(as_of: date | None = None) -> DashboardResponse:
    resolved = _resolve_as_of(as_of)

    with analytical(read_only=True) as conn:
        regime_data = market_regime(conn, resolved)
        breadth_data = breadth(conn, resolved)

        # FR-7.6: exit signals appear above the entry candidates, always.
        exits = run_screen(conn, get_preset(MOMENTUM_BREAKDOWN), resolved)[:15]
        leaders = run_screen(conn, get_preset("Momentum Leaders"), resolved)[:10]
        # FR-14.6: the preset already carries the ordering and the limit of 10.
        reversals = run_screen(conn, get_preset(PULLBACK_REVERSAL), resolved)

        sectors = conn.execute(
            """
            SELECT i.industry, median(m.ret_1w) AS med, count(*) AS n
              FROM metrics_daily m
              JOIN instruments i USING (instrument_token)
             WHERE m.trade_date = ? AND m.is_eligible AND i.industry IS NOT NULL
             GROUP BY 1 HAVING count(*) >= 3
             ORDER BY med DESC NULLS LAST
            """,
            [resolved],
        ).fetchall()

    # FR-1.4: universe changes stay visible for 5 sessions after the change.
    cutoff = (resolved - timedelta(days=12)).isoformat()
    with app_db() as conn:
        changes = conn.execute(
            "SELECT tradingsymbol, change_type, change_date FROM universe_changes "
            "WHERE change_date >= ? ORDER BY change_date DESC LIMIT 50",
            (cutoff,),
        ).fetchall()

    return DashboardResponse(
        status=_data_status(),
        regime=MarketRegime(**regime_data),
        breadth=Breadth(**breadth_data),
        exit_signals=exits,
        momentum_leaders=leaders,
        pullback_reversals=reversals,
        sector_heatmap=[
            SectorPerformance(
                sector=r[0],
                median_ret_1w=float(r[1]) if r[1] is not None else None,
                count=int(r[2]),
            )
            for r in sectors
        ],
        universe_changes=[
            UniverseChange(
                tradingsymbol=r["tradingsymbol"],
                change_type=r["change_type"],
                change_date=r["change_date"],
            )
            for r in changes
        ],
        presets=[
            PresetSummary(
                name=name,
                description=str(d.get("description", "")),
                is_exit_screen=name == MOMENTUM_BREAKDOWN,
            )
            for name, d in PRESETS.items()
        ],
    )


@app.post("/api/export/{fmt}")
def post_export(
    fmt: str,
    payload: dict[str, Any],
    as_of: date | None = None,
) -> dict[str, Any]:
    """Export a screen to xlsx, csv or html (FR-9.1).

    ``payload`` carries the screen definition and, optionally, the visible
    column list — FR-9.2's "current view" scope.
    """
    from alpha500 import exports

    writers = {
        "xlsx": exports.export_xlsx,
        "csv": exports.export_csv,
        "html": exports.export_html,
    }
    if fmt not in writers:
        raise HTTPException(400, f"unsupported format: {fmt}")

    definition = payload.get("definition") or {}
    screen_name = str(payload.get("screen_name") or definition.get("name") or "Screen")
    resolved = _resolve_as_of(as_of)

    try:
        with analytical(read_only=True) as conn:
            rows = run_screen(conn, definition, resolved)
    except ScreenDefinitionError as exc:
        raise HTTPException(400, str(exc)) from exc

    columns = payload.get("columns") or (
        ["tradingsymbol", "name", "sector", "close", *METRIC_COLUMNS]
    )

    path = writers[fmt](rows, columns, screen_name, definition, resolved)
    return {
        "path": str(path),
        "filename": path.name,
        "row_count": len(rows),
        "data_as_of": str(resolved),
    }


@app.get("/api/stock/{symbol}", response_model=StockDetail)
def get_stock(
    symbol: str,
    as_of: date | None = None,
    candles: int = Query(500, ge=50, le=2600),
    portfolio_value: float | None = None,
) -> StockDetail:
    resolved = _resolve_as_of(as_of)
    symbol = symbol.strip().upper()

    with analytical(read_only=True) as conn:
        instrument = conn.execute(
            "SELECT instrument_token, tradingsymbol, name, sector, industry "
            "FROM instruments WHERE tradingsymbol = ?",
            [symbol],
        ).fetchone()
        if instrument is None:
            raise HTTPException(404, f"unknown symbol: {symbol}")
        token = int(instrument[0])

        metric_cursor = conn.execute(
            f"SELECT {', '.join(METRIC_COLUMNS)} FROM metrics_daily "
            "WHERE instrument_token = ? AND trade_date = ?",
            [token, resolved],
        )
        metric_row = metric_cursor.fetchone()
        metrics = dict(zip(METRIC_COLUMNS, metric_row)) if metric_row else {}

        price_rows = conn.execute(
            """
            SELECT trade_date,
                   open * adj_factor, high * adj_factor,
                   low * adj_factor, close * adj_factor,
                   CAST(volume / adj_factor AS BIGINT), delivery_pct
              FROM ohlcv_daily
             WHERE instrument_token = ? AND trade_date <= ?
             ORDER BY trade_date DESC LIMIT ?
            """,
            [token, resolved, candles],
        ).fetchall()

        actions = conn.execute(
            "SELECT ex_date, action_type, ratio_from, ratio_to, amount, raw_purpose "
            "FROM corporate_actions WHERE instrument_token = ? ORDER BY ex_date DESC LIMIT 40",
            [token],
        ).fetchall()

    price_rows.reverse()
    candle_list = [
        {
            "trade_date": r[0], "open": r[1], "high": r[2], "low": r[3],
            "close": r[4], "volume": int(r[5] or 0), "delivery_pct": r[6],
        }
        for r in price_rows
    ]

    action_list = [
        {
            "ex_date": r[0], "action_type": r[1], "ratio_from": r[2],
            "ratio_to": r[3], "amount": r[4], "raw_purpose": r[5],
        }
        for r in actions
    ]
    # FR-3.5: a swing entry into an ex-date gap is a known avoidable error.
    horizon = resolved + timedelta(days=15)
    upcoming = [a for a in action_list if resolved <= a["ex_date"] <= horizon]

    close = candle_list[-1]["close"] if candle_list else None
    stop = risk.suggest_stop(
        close=close,
        atr_14=metrics.get("atr_14"),
        base_low=metrics.get("low_52w") if metrics.get("is_in_base") else None,
    )

    risk_out = RiskSuggestion(
        atr_stop_price=stop.atr_stop_price,
        atr_stop_distance_pct=stop.atr_stop_distance_pct,
        structural_stop_price=stop.structural_stop_price,
        wider_stop=stop.wider_stop,
    )

    if close and stop.atr_stop_price and portfolio_value:
        sized = risk.size_position(close, stop.atr_stop_price, portfolio_value)
        if sized:
            risk_out.quantity = sized.quantity
            risk_out.position_value = sized.position_value
            risk_out.exceeds_max_weight = sized.exceeds_max_weight

    if stop.atr_stop_distance_pct:
        # Assume a 1R target, i.e. a win the same size as the stop distance.
        costs = risk.round_trip_cost_pct(stop.atr_stop_distance_pct)
        risk_out.round_trip_cost_pct = costs["round_trip_cost_pct"]
        risk_out.breakeven_move_pct = costs["breakeven_move_pct"]
        risk_out.net_gain_at_target_pct = costs["net_gain_pct"]
        # FR-12.5: flag a candidate whose ATR target cannot clear its own costs.
        risk_out.cost_exceeds_atr_target = (
            costs["round_trip_cost_pct"] >= stop.atr_stop_distance_pct
        )

    return StockDetail(
        tradingsymbol=instrument[1],
        name=instrument[2],
        sector=instrument[3],
        industry=instrument[4],
        status=_data_status(),
        metrics=metrics,
        candles=candle_list,  # type: ignore[arg-type]
        corporate_actions=action_list,
        upcoming_ex_dates=upcoming,
        risk=risk_out,
    )


@app.get("/api/backtest/availability", response_model=BacktestAvailability)
def backtest_availability() -> BacktestAvailability:
    """Is there enough materialised history to simulate against?

    A backtest needs the metrics as they stood on each past session. The
    nightly pipeline stores only the latest, so this reports plainly whether
    'alpha500 materialise' has been run rather than letting the UI offer a
    control that cannot work.
    """
    with analytical(read_only=True) as conn:
        row = conn.execute(
            "SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date) "
            "FROM metrics_daily"
        ).fetchone()

    sessions, first, last = (row or (0, None, None))
    if sessions < 2:
        return BacktestAvailability(
            ready=False, sessions=sessions, start=first, end=last,
            reason=(
                "Metrics are materialised for "
                f"{sessions} session{'' if sessions == 1 else 's'}. "
                "Run 'alpha500 materialise' to compute the metrics as they stood "
                "on each historical session — a backtest cannot be run without them."
            ),
        )
    return BacktestAvailability(ready=True, sessions=sessions, start=first, end=last)


@app.post("/api/backtest")
def run_backtest_endpoint(request: BacktestRequest) -> dict[str, Any]:
    """Replay a screen over history (Phase 3).

    Runs two full simulations (with and without TDS withheld), so it is
    seconds rather than milliseconds and sits outside the NFR-1.4 screen
    budget by design.
    """
    import dataclasses

    from alpha500.backtest.engine import BacktestConfig, run_backtest
    from alpha500.backtest.walkforward import sweep, walk_forward
    from alpha500.screens.presets import PRESETS, get_preset

    if request.screen_name not in PRESETS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown screen {request.screen_name!r}",
        )

    with analytical(read_only=True) as conn:
        bounds = conn.execute(
            "SELECT min(trade_date), max(trade_date) FROM metrics_daily"
        ).fetchone()
        if bounds is None or bounds[0] is None or bounds[0] == bounds[1]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Metrics are materialised for at most one session. "
                    "Run 'alpha500 materialise' first."
                ),
            )

        config = BacktestConfig(
            screen=get_preset(request.screen_name),
            exit_screen=get_preset("Momentum Breakdown") if request.use_exit_screen else None,
            start=request.start or bounds[0],
            end=request.end or bounds[1],
            initial_capital=request.initial_capital,
            max_positions=request.max_positions,
            stop_atr_multiple=request.stop_atr_multiple,
            trailing_stop=request.trailing_stop,
            slippage_pct=request.slippage_pct,
        )

        result = run_backtest(conn, config)
        payload: dict[str, Any] = result.as_dict()
        payload["benchmark"] = _benchmark(conn, config.start, config.end)
        payload["config"] = {
            "screen_name": request.screen_name,
            "stop_atr_multiple": request.stop_atr_multiple,
            "trailing_stop": request.trailing_stop,
            "use_exit_screen": request.use_exit_screen,
            "max_positions": request.max_positions,
            "initial_capital": request.initial_capital,
        }

        def set_stop(cfg: Any, value: Any) -> Any:
            return dataclasses.replace(cfg, stop_atr_multiple=value)

        if request.sweep:
            payload["sweep"] = sweep(conn, config, request.sweep, set_stop).as_dict()
        if request.walk_forward:
            values = request.sweep or [1.5, 2.0, 2.5, 3.0, 4.0]
            payload["walk_forward"] = walk_forward(conn, config, values, set_stop).as_dict()

    return payload


def _benchmark(conn: Any, start: date, end: date) -> dict[str, Any] | None:
    """Buy-and-hold the index over the same window.

    Without it a CAGR is uninterpretable: a strategy earning 13% in a market
    that returned 11% is a different proposition from one earning 13% in a
    market that returned 20%.
    """
    rows = conn.execute(
        "SELECT trade_date, close FROM index_ohlcv_daily "
        "WHERE index_name = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
        [settings.index_name, start, end],
    ).fetchall()
    if len(rows) < 2:
        return None

    closes = [float(r[1]) for r in rows]
    peak = closes[0]
    worst = 0.0
    for value in closes:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)

    years = len(closes) / 252.0
    total = closes[-1] / closes[0] - 1.0
    cagr = ((closes[-1] / closes[0]) ** (1.0 / years) - 1.0) if years > 0 else 0.0
    return {
        "index_name": settings.index_name,
        "cagr_pct": cagr * 100.0,
        "total_return_pct": total * 100.0,
        "max_drawdown_pct": worst * 100.0,
        "curve": [
            {"date": r[0].isoformat(), "close": float(r[1])} for r in rows
        ],
    }


@app.get("/api/indices/valuation")
def get_index_valuation() -> dict[str, Any]:
    """Current P/E for the tracked indices against their own 7y/10y medians.

    Answers "is this segment expensive by its own standards", which a level
    alone cannot: a midcap P/E of 30 means nothing until you know the index has
    historically sat near 25.
    """
    from alpha500.pipeline.indices import valuation_summary

    with analytical(read_only=True) as conn:
        rows = valuation_summary(conn)
        span = conn.execute(
            "SELECT min(trade_date), max(trade_date), count(*) "
            "FROM index_valuation_daily"
        ).fetchone()

    return {
        "indices": rows,
        "history_from": span[0].isoformat() if span and span[0] else None,
        "history_to": span[1].isoformat() if span and span[1] else None,
        "observations": int(span[2]) if span else 0,
        # Stated so a median is never mistaken for a daily-sampled one.
        "note": (
            "History is sampled weekly; the latest session is always exact. "
            "A median needs data spanning at least 80% of its window, or it "
            "is reported as unavailable rather than computed from a partial one."
        ),
    }
