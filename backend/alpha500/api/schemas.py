"""Pydantic response models. The OpenAPI spec is generated from these."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class DataStatus(BaseModel):
    """FR-8.9: staleness must be loud, and must carry a reason.

    Silently serving yesterday's data as though it were today's is the single
    most dangerous failure mode in this class of tool, so every response that
    carries market data carries this alongside it.
    """

    data_as_of: date | None
    latest_session: date | None
    is_stale: bool
    reason: str | None = None
    last_run_status: str | None = None
    last_run_at: str | None = None


class MarketRegime(BaseModel):
    regime: str
    index_close: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    net_new_highs: int | None = None
    advisory: str | None = None


class Breadth(BaseModel):
    new_highs: int
    new_lows: int
    net_new_highs: int
    advances: int
    declines: int
    universe: int


class UniverseChange(BaseModel):
    tradingsymbol: str
    change_type: str
    change_date: str


class ScreenRow(BaseModel):
    model_config = {"extra": "allow"}

    tradingsymbol: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    close: float | None = None


class ScreenResponse(BaseModel):
    screen_name: str
    version: int = 1
    definition: dict[str, Any]
    data_as_of: date | None
    status: DataStatus
    row_count: int
    rows: list[dict[str, Any]]


class PresetSummary(BaseModel):
    name: str
    description: str
    is_exit_screen: bool = False
    row_count: int | None = None


class SectorPerformance(BaseModel):
    sector: str
    median_ret_1w: float | None
    count: int


class DashboardResponse(BaseModel):
    status: DataStatus
    regime: MarketRegime
    breadth: Breadth
    exit_signals: list[dict[str, Any]]
    momentum_leaders: list[dict[str, Any]]
    sector_heatmap: list[SectorPerformance]
    universe_changes: list[UniverseChange]
    presets: list[PresetSummary]


class Candle(BaseModel):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    delivery_pct: float | None = None


class RiskSuggestion(BaseModel):
    """FR-10.1/FR-10.2. Cash-funded only — NRI accounts have no margin (FR-12.3)."""

    atr_stop_price: float | None = None
    atr_stop_distance_pct: float | None = None
    structural_stop_price: float | None = None
    wider_stop: str | None = None
    quantity: int | None = None
    position_value: float | None = None
    exceeds_max_weight: bool = False
    # breakeven is the frictions alone; round_trip_cost adds the withholding
    # incurred on a 1R win. They are different questions and must not be
    # presented as competing answers to the same one.
    breakeven_move_pct: float | None = None
    round_trip_cost_pct: float | None = None
    net_gain_at_target_pct: float | None = None
    cost_exceeds_atr_target: bool = False


class StockDetail(BaseModel):
    tradingsymbol: str
    name: str | None
    sector: str | None
    industry: str | None
    status: DataStatus
    metrics: dict[str, Any]
    candles: list[Candle]
    corporate_actions: list[dict[str, Any]]
    upcoming_ex_dates: list[dict[str, Any]]
    risk: RiskSuggestion


class MetricDefinition(BaseModel):
    """FR-8.10: every derived metric exposes its own definition."""

    name: str
    label: str
    formula: str
    description: str
    group: str
    unit: str = "number"
