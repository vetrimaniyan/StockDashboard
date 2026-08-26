-- Transactional store (SQLite). User-authored data only.
-- Deliberately separate from the analytical store so a full price rebuild
-- can never put watchlists or the journal at risk.

CREATE TABLE IF NOT EXISTS watchlist (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tradingsymbol    TEXT NOT NULL UNIQUE,
    instrument_token INTEGER,
    added_at         TEXT NOT NULL,
    notes            TEXT,
    trigger_price    REAL,
    trigger_hit_at   TEXT
);

CREATE TABLE IF NOT EXISTS journal (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    tradingsymbol         TEXT NOT NULL,
    instrument_token      INTEGER,
    entry_date            TEXT NOT NULL,
    entry_price           REAL NOT NULL,
    quantity              INTEGER NOT NULL,
    stop_price            REAL,
    exit_date             TEXT,
    exit_price            REAL,
    exit_reason           TEXT,
    origin_screen         TEXT,
    thesis                TEXT,
    -- FR-12.1: NRI accounts are delivery-only; no intraday, no BTST.
    earliest_sellable_date TEXT,
    tds_withheld          REAL,
    fx_rate_entry         REAL,
    fx_rate_exit          REAL,
    fx_rate_source        TEXT
);

CREATE TABLE IF NOT EXISTS screen_defs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT,
    definition   TEXT NOT NULL,   -- JSON per FR-7.4
    is_preset    INTEGER NOT NULL DEFAULT 0,
    version      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,          -- correlation id (NFR / FR-11.3)
    stage        TEXT NOT NULL,
    status       TEXT NOT NULL,          -- RUNNING|OK|FAILED|SKIPPED
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    row_count    INTEGER,
    message      TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_runs_run ON job_runs (run_id, stage);

CREATE TABLE IF NOT EXISTS settings_kv (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- FR-6.8: composite weight sets are named, persisted profiles.
CREATE TABLE IF NOT EXISTS weight_profiles (
    name       TEXT PRIMARY KEY,
    weights    TEXT NOT NULL,   -- JSON
    is_active  INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- FR-1.4: universe additions/deletions surfaced for 5 sessions.
CREATE TABLE IF NOT EXISTS universe_changes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    change_date   TEXT NOT NULL,
    tradingsymbol TEXT NOT NULL,
    change_type   TEXT NOT NULL,   -- ADDED|REMOVED
    index_name    TEXT NOT NULL
);
