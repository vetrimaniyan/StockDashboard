-- Analytical store (DuckDB). Schema per SRS section 3.5.
-- Rebuildable from raw data; contains no user-authored content.

CREATE TABLE IF NOT EXISTS instruments (
    instrument_token   BIGINT PRIMARY KEY,
    exchange_token     BIGINT,
    tradingsymbol      VARCHAR NOT NULL,
    name               VARCHAR,
    isin               VARCHAR,
    series             VARCHAR,
    exchange           VARCHAR NOT NULL DEFAULT 'NSE',
    industry           VARCHAR,
    sector             VARCHAR,
    basic_industry     VARCHAR,
    lot_size           INTEGER,
    tick_size          DOUBLE,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_date    DATE,
    last_seen_date     DATE
);

CREATE TABLE IF NOT EXISTS index_membership (
    index_name         VARCHAR NOT NULL,
    instrument_token   BIGINT NOT NULL,
    valid_from         DATE NOT NULL,
    valid_to           DATE,
    PRIMARY KEY (index_name, instrument_token, valid_from)
);

CREATE TABLE IF NOT EXISTS ohlcv_daily (
    instrument_token   BIGINT NOT NULL,
    trade_date         DATE NOT NULL,
    open               DOUBLE NOT NULL,
    high               DOUBLE NOT NULL,
    low                DOUBLE NOT NULL,
    close              DOUBLE NOT NULL,
    volume             BIGINT NOT NULL,
    traded_value       DOUBLE,
    vwap               DOUBLE,
    num_trades         BIGINT,
    delivery_qty       BIGINT,
    delivery_pct       DOUBLE,
    adj_factor         DOUBLE NOT NULL DEFAULT 1.0,
    source             VARCHAR NOT NULL,
    ingested_at        TIMESTAMP NOT NULL,
    PRIMARY KEY (instrument_token, trade_date)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    instrument_token   BIGINT NOT NULL,
    ex_date            DATE NOT NULL,
    action_type        VARCHAR NOT NULL,
    ratio_from         DOUBLE,
    ratio_to           DOUBLE,
    amount             DOUBLE,
    raw_purpose        VARCHAR,
    PRIMARY KEY (instrument_token, ex_date, action_type)
);

CREATE TABLE IF NOT EXISTS metrics_daily (
    instrument_token   BIGINT NOT NULL,
    trade_date         DATE NOT NULL,
    ret_1d DOUBLE, ret_1w DOUBLE, ret_1m DOUBLE,
    ret_3m DOUBLE, ret_6m DOUBLE, ret_9m DOUBLE,
    ret_12m DOUBLE, ret_12m_1m DOUBLE,
    rs_1m DOUBLE, rs_3m DOUBLE, rs_6m DOUBLE, rs_12m DOUBLE,
    rs_rating INTEGER,
    sma_20 DOUBLE, sma_50 DOUBLE, sma_100 DOUBLE,
    sma_150 DOUBLE, sma_200 DOUBLE,
    ema_21 DOUBLE, ema_50 DOUBLE,
    sma_200_slope_1m DOUBLE,
    ma_alignment BOOLEAN,
    high_52w DOUBLE, low_52w DOUBLE,
    pct_from_52w_high DOUBLE, pct_above_52w_low DOUBLE,
    range_position_52w DOUBLE,
    days_since_52w_high INTEGER,
    exp_reg_slope_90 DOUBLE,
    exp_reg_r2_90 DOUBLE,
    momentum_score DOUBLE,
    momentum_rank INTEGER,
    composite_z DOUBLE,
    atr_14 DOUBLE, atr_pct_14 DOUBLE,
    stdev_21 DOUBLE, stdev_63 DOUBLE,
    adr_pct_20 DOUBLE,
    vol_sma_20 BIGINT, vol_sma_50 BIGINT,
    rel_volume DOUBLE,
    turnover_20d_median DOUBLE,
    delivery_pct_sma_20 DOUBLE,
    rsi_14 DOUBLE, adx_14 DOUBLE,
    macd DOUBLE, macd_signal DOUBLE, macd_hist DOUBLE,
    is_52w_high_breakout BOOLEAN,
    is_n_day_breakout_20 BOOLEAN,
    is_n_day_breakout_50 BOOLEAN,
    is_in_base BOOLEAN,
    base_depth_pct DOUBLE,
    base_length_days INTEGER,
    is_trend_template BOOLEAN,
    trend_template_score INTEGER,
    is_pullback BOOLEAN,
    gap_disqualified BOOLEAN,
    history_days INTEGER,
    is_eligible BOOLEAN,
    PRIMARY KEY (instrument_token, trade_date)
);

-- The two hot access paths named in the SRS.
CREATE INDEX IF NOT EXISTS idx_metrics_date_rank ON metrics_daily (trade_date, momentum_rank);
CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv_daily (trade_date);

-- Index level series (NIFTY 500 itself), used for relative strength and the
-- market-regime banner. Stored separately: it is not a tradeable instrument.
CREATE TABLE IF NOT EXISTS index_ohlcv_daily (
    index_name         VARCHAR NOT NULL,
    trade_date         DATE NOT NULL,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE NOT NULL,
    volume BIGINT,
    source             VARCHAR NOT NULL,
    ingested_at        TIMESTAMP NOT NULL,
    PRIMARY KEY (index_name, trade_date)
);

-- FR-4.3: "market was open" must never be derived from the presence of data.
CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date         DATE PRIMARY KEY,
    is_trading_day     BOOLEAN NOT NULL,
    description        VARCHAR
);

-- Which build of the metric engine produced each date's metrics. AR-4's
-- reproducibility guarantee only means something if the served numbers came
-- from the code that is actually in the tree.
CREATE TABLE IF NOT EXISTS metrics_meta (
    trade_date         DATE PRIMARY KEY,
    engine_fingerprint VARCHAR NOT NULL,
    computed_at        TIMESTAMP NOT NULL,
    row_count          INTEGER NOT NULL
);

-- FR-4.1 V5: rows failing a Warn check are quarantined rather than published.
CREATE TABLE IF NOT EXISTS quarantined_rows (
    instrument_token   BIGINT NOT NULL,
    trade_date         DATE NOT NULL,
    check_id           VARCHAR NOT NULL,
    detail             VARCHAR,
    quarantined_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (instrument_token, trade_date, check_id)
);
