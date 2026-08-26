"""Central configuration. Secrets come from .env or the OS keyring only (NFR-4.2)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_prefix="ALPHA500_",
        extra="ignore",
    )

    data_dir: Path = REPO_ROOT / "data"
    export_dir: Path = REPO_ROOT / "exports"

    # --- Providers -------------------------------------------------------
    # Kite Connect is a paid subscription; this build runs on free sources.
    # Yahoo does bulk backfill, NSE archives do nightly incremental + delivery.
    backfill_provider: str = "yahoo"
    incremental_provider: str = "nse"
    http_timeout_s: float = 20.0  # NFR-2.5: no unbounded waits
    max_retries: int = 5

    # Token-bucket rates (FR-2.4). Yahoo is unofficial: stay gentle.
    yahoo_rate_per_s: float = 2.0
    nse_rate_per_s: float = 1.5

    # --- Universe / eligibility -----------------------------------------
    index_name: str = "NIFTY500"
    min_history_days: int = 252  # FR-1.5
    liquidity_floor_inr: float = 5e7  # FR-1.6: Rs 5 crore
    allowed_series: tuple[str, ...] = ("EQ", "BE")

    # --- Metric engine ---------------------------------------------------
    momentum_lookback: int = 90  # FR-6.5: L = 90 sessions
    gap_disqualifier_pct: float = 0.15  # FR-6.6
    rel_volume_threshold: float = 1.5  # FR-6.11
    base_window: int = 15  # FR-6.14 default W

    # --- Composite weights (FR-6.8) --------------------------------------
    w_momentum: float = 0.30
    w_ret_12m_1m: float = 0.20
    w_rs_rating: float = 0.20
    w_range_position: float = 0.15
    w_atr_pct: float = 0.10  # subtracted
    w_rel_volume: float = 0.05

    # --- Risk (FR-10) ----------------------------------------------------
    atr_stop_multiple: float = 2.0
    risk_per_trade_pct: float = 0.0075
    max_position_weight: float = 0.10
    portfolio_heat_ceiling: float = 0.06
    sector_concentration_limit: float = 0.25

    # --- API -------------------------------------------------------------
    api_host: str = "127.0.0.1"  # NFR-4.1
    api_port: int = 8000

    # --- Optional Kite (unused by default) -------------------------------
    kite_api_key: str | None = Field(default=None, repr=False)
    kite_api_secret: str | None = Field(default=None, repr=False)

    @property
    def analytical_db(self) -> Path:
        return self.data_dir / "alpha500.duckdb"

    @property
    def app_db(self) -> Path:
        return self.data_dir / "app.sqlite"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "cache").mkdir(parents=True, exist_ok=True)


settings = Settings()
