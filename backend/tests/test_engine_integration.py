"""End-to-end metric engine and validation gate tests.

Covers several Phase 1 sign-off criteria from SRS section 15 directly:
  #5  golden-dataset regression is byte-identical across two runs
  #9  a corrupted input blocks the gate and preserves the prior dataset
  #11 a synthetic 60% gap excludes the symbol from momentum ranking
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from alpha500.metrics.engine import compute_metrics_for_date
from alpha500.pipeline.validation import Severity, run_gate


def _metrics(conn, as_of):  # type: ignore[no-untyped-def]
    rows = conn.execute(
        """
        SELECT i.tradingsymbol, m.momentum_score, m.momentum_rank, m.rs_rating,
               m.is_eligible, m.trend_template_score, m.exp_reg_r2_90,
               m.gap_disqualified, m.range_position_52w, m.atr_pct_14,
               m.composite_z, m.history_days
          FROM metrics_daily m
          JOIN instruments i USING (instrument_token)
         WHERE m.trade_date = ?
        """,
        [as_of],
    ).fetchall()
    return {r[0]: r for r in rows}


def test_engine_computes_every_universe_member(conn, universe):
    as_of = universe[-1]
    written = compute_metrics_for_date(conn, as_of, "NIFTY500")
    assert written == 6


def test_clean_trend_outranks_choppy_trend_of_similar_drift(conn, universe):
    """FR-6.5: R^2 penalises gap-driven and choppy advances.

    Both series carry the same drift; CHOPPY adds oscillation. For swing
    trading the smoother vehicle is the better one, and the score must say so.
    """
    as_of = universe[-1]
    compute_metrics_for_date(conn, as_of, "NIFTY500")
    m = _metrics(conn, as_of)

    assert m["CLEANUP"][6] > m["CHOPPY"][6], "clean series must have higher R^2"
    assert m["CLEANUP"][1] > m["CHOPPY"][1], "clean series must score higher"
    assert m["CLEANUP"][2] < m["CHOPPY"][2], "rank 1 is strongest"


def test_gap_disqualifier_excludes_from_momentum_ranking(conn, universe):
    """Acceptance criterion 11, and FR-6.6.

    GAPPER has the strongest raw advance but moved 60% in a single session
    within the lookback. A one-off event move is not a tradeable trend.
    """
    as_of = universe[-1]
    compute_metrics_for_date(conn, as_of, "NIFTY500")
    m = _metrics(conn, as_of)

    assert m["GAPPER"][7] is True, "gap should be flagged"
    assert m["GAPPER"][1] is None, "momentum score must be null when disqualified"
    assert m["GAPPER"][2] is None, "disqualified symbols must not be ranked"


def test_illiquid_symbol_is_ineligible_but_still_stored(conn, universe):
    """FR-1.5/FR-1.6: excluded from screen results, not dropped from the store."""
    as_of = universe[-1]
    compute_metrics_for_date(conn, as_of, "NIFTY500")
    m = _metrics(conn, as_of)

    assert m["THIN"][4] is False
    assert m["CLEANUP"][4] is True
    stored = conn.execute(
        "SELECT count(*) FROM ohlcv_daily WHERE instrument_token = 1006"
    ).fetchone()[0]
    assert stored > 0, "ineligible symbols must still be ingested and stored"


def test_rs_rating_spans_the_scale_and_ranks_correctly(conn, universe):
    as_of = universe[-1]
    compute_metrics_for_date(conn, as_of, "NIFTY500")
    m = _metrics(conn, as_of)

    ratings = {k: v[3] for k, v in m.items() if v[3] is not None}
    assert all(1 <= r <= 99 for r in ratings.values())
    assert ratings["CLEANUP"] > ratings["FALLER"]
    # THIN is ineligible, so it takes no part in the percentile.
    assert m["THIN"][3] is None


def test_trend_template_score_is_bounded_and_ordered(conn, universe):
    as_of = universe[-1]
    compute_metrics_for_date(conn, as_of, "NIFTY500")
    m = _metrics(conn, as_of)

    for symbol, row in m.items():
        if row[5] is not None:
            assert 0 <= row[5] <= 8, f"{symbol} scored {row[5]}"
    assert m["CLEANUP"][5] > m["FALLER"][5]


def test_downtrend_sits_low_in_its_52_week_range(conn, universe):
    as_of = universe[-1]
    compute_metrics_for_date(conn, as_of, "NIFTY500")
    m = _metrics(conn, as_of)

    assert m["CLEANUP"][8] > 0.9, "a steady riser should sit near its 52-week high"
    assert m["FALLER"][8] < 0.1, "a steady faller should sit near its 52-week low"


def test_boolean_metrics_are_null_not_false_during_warm_up(conn, universe):
    """FR-6.1: a metric that cannot be computed is null, never False.

    Any comparison against nan yields False, so without explicit null handling
    a symbol still inside its warm-up window reports "not a breakout" in
    exactly the same way as one that genuinely failed the test — and a screen
    filtering on ``= False`` would silently scoop up every warm-up row.
    """
    from alpha500.metrics.series import compute_series_metrics

    import numpy as np

    from tests.conftest import synth_series, trading_days

    # 40 sessions: far short of the 200 and 252 the long windows need.
    dates = trading_days(40)
    rows = synth_series(dates, 100, 0.001)
    arrays = {
        name: np.array([r[i] for r in rows], dtype=np.float64)
        for i, name in enumerate(("_", "open", "high", "low", "close", "volume"))
        if name != "_"
    }

    computed = compute_series_metrics(
        trade_date=np.array(dates, dtype=object),
        open_=arrays["open"],
        high=arrays["high"],
        low=arrays["low"],
        close=arrays["close"],
        volume=arrays["volume"],
    )

    for name in ("ma_alignment", "is_52w_high_breakout", "is_in_base"):
        assert computed.columns[name][-1] is None, (
            f"{name} should be null with only 40 sessions of history, "
            f"got {computed.columns[name][-1]!r}"
        )


def test_base_can_persist_long_enough_for_the_preset_to_fire(conn, universe):
    """FR-6.14 as written is self-extinguishing; see DECISIONS.md D-8.

    The literal contraction test compares ATR to ATR one window ago. Once a
    base is a full window old that reference sits inside the quiet period, the
    ratio drifts to 1, and the condition kills itself. Measured on real data
    it never held beyond 7 consecutive sessions, which makes the Volatility
    Contraction preset's ``base_length_days >= 10`` unsatisfiable.

    Anchoring the reference to the advance that preceded the consolidation
    lets the base run as long as it genuinely stays quiet.
    """
    import numpy as np

    from alpha500.metrics.series import compute_series_metrics
    from tests.conftest import synth_series, trading_days

    # A steep advance, then a quiet consolidation. The advance has to stay
    # inside the 63-session lookback that precedes the window, so the base
    # cannot be arbitrarily long — a range that has held for a full quarter is
    # no longer contracting against a recent move.
    dates = trading_days(360)
    advance = synth_series(dates[:330], 100, 0.005)
    last_close = advance[-1][4]
    base = [
        (day, last_close, last_close * 1.002, last_close * 0.998, last_close, 400_000)
        for day in dates[330:]
    ]
    rows = advance + base

    computed = compute_series_metrics(
        trade_date=np.array(dates, dtype=object),
        open_=np.array([r[1] for r in rows], dtype=np.float64),
        high=np.array([r[2] for r in rows], dtype=np.float64),
        low=np.array([r[3] for r in rows], dtype=np.float64),
        close=np.array([r[4] for r in rows], dtype=np.float64),
        volume=np.array([r[5] for r in rows], dtype=np.float64),
    )

    assert computed.columns["is_in_base"][-1] is True
    length = computed.columns["base_length_days"][-1]
    assert length >= 10, f"base ran only {length} sessions; the preset needs 10"


def _base_flag(rows, dates):  # type: ignore[no-untyped-def]
    import numpy as np

    from alpha500.metrics.series import compute_series_metrics

    computed = compute_series_metrics(
        trade_date=np.array(dates, dtype=object),
        open_=np.array([r[1] for r in rows], dtype=np.float64),
        high=np.array([r[2] for r in rows], dtype=np.float64),
        low=np.array([r[3] for r in rows], dtype=np.float64),
        close=np.array([r[4] for r in rows], dtype=np.float64),
        volume=np.array([r[5] for r in rows], dtype=np.float64),
    )
    return computed.columns["is_in_base"][-1]


def _quiet_tail(last_close, days):  # type: ignore[no-untyped-def]
    return [
        (day, last_close, last_close * 1.002, last_close * 0.998, last_close, 400_000)
        for day in days
    ]


def test_base_requires_a_prior_advance(conn, universe):
    """A quiet stock that never rallied is not a base — it is just dormant."""
    from tests.conftest import trading_days

    dates = trading_days(360)
    rows = [(d, 100.0, 100.2, 99.8, 100.0, 400_000) for d in dates]
    assert _base_flag(rows, dates) is False


def test_a_crash_followed_by_quiet_is_not_a_base(conn, universe):
    """The advance must be directional, not merely a 25% range.

    Regression: measuring the lookback's max over its min is symmetric, so a
    stock that fell 25% and went quiet near its low scored exactly like one
    that rose 25% and paused near its high. On real data that filled the
    Volatility Contraction screen with dead stocks — RS ratings of 1 to 53,
    sitting at 1-45% of their 52-week range.
    """
    from tests.conftest import synth_series, trading_days

    dates = trading_days(360)
    decline = synth_series(dates[:330], 500, -0.005)
    rows = decline + _quiet_tail(decline[-1][4], dates[330:])

    assert _base_flag(rows, dates) is False


def test_recomputation_is_deterministic(conn, universe):
    """Acceptance criterion 5, and AR-4.

    Metric output must be bit-identical across runs given the same history.
    """
    as_of = universe[-1]
    compute_metrics_for_date(conn, as_of, "NIFTY500")
    first = conn.execute(
        "SELECT * FROM metrics_daily WHERE trade_date = ? ORDER BY instrument_token",
        [as_of],
    ).fetchall()

    compute_metrics_for_date(conn, as_of, "NIFTY500")
    second = conn.execute(
        "SELECT * FROM metrics_daily WHERE trade_date = ? ORDER BY instrument_token",
        [as_of],
    ).fetchall()

    assert first == second


def test_recomputation_does_not_duplicate_rows(conn, universe):
    """AR-3: re-running for a processed date must not duplicate."""
    as_of = universe[-1]
    compute_metrics_for_date(conn, as_of, "NIFTY500")
    compute_metrics_for_date(conn, as_of, "NIFTY500")

    count = conn.execute(
        "SELECT count(*) FROM metrics_daily WHERE trade_date = ?", [as_of]
    ).fetchone()[0]
    assert count == 6


# --- validation gate -----------------------------------------------------


def test_gate_passes_on_clean_data(conn, universe):
    gate = run_gate(conn, universe[-1], "NIFTY500", universe_size=6)
    assert not gate.blocked, [f"{c.check_id}: {c.detail}" for c in gate.failures]


def test_corrupted_ohlc_blocks_the_gate(conn, universe):
    """Acceptance criterion 9, check V3.

    A high below the low is structurally impossible and must abort the run
    rather than publish.
    """
    as_of = universe[-1]
    conn.execute(
        "UPDATE ohlcv_daily SET high = low - 10 WHERE instrument_token = 1001 "
        "AND trade_date = ?",
        [as_of],
    )
    gate = run_gate(conn, as_of, "NIFTY500", universe_size=6)

    assert gate.blocked
    v3 = next(c for c in gate.results if c.check_id == "V3")
    assert not v3.passed and v3.severity is Severity.BLOCK


def test_negative_price_blocks_the_gate(conn, universe):
    as_of = universe[-1]
    conn.execute(
        "UPDATE ohlcv_daily SET close = -5, low = -10 WHERE instrument_token = 1002 "
        "AND trade_date = ?",
        [as_of],
    )
    gate = run_gate(conn, as_of, "NIFTY500", universe_size=6)
    assert gate.blocked


def test_row_count_shortfall_blocks_the_gate(conn, universe):
    """V1: a partial ingest must not be published as a complete session."""
    as_of = universe[-1]
    conn.execute("DELETE FROM ohlcv_daily WHERE trade_date = ? AND instrument_token > 1002",
                 [as_of])
    gate = run_gate(conn, as_of, "NIFTY500", universe_size=6)

    assert gate.blocked
    v1 = next(c for c in gate.results if c.check_id == "V1")
    assert not v1.passed


def test_non_trading_day_blocks_the_gate(conn, universe):
    """V7: the calendar is authoritative, never the presence of data."""
    saturday = universe[-1] + timedelta(days=(5 - universe[-1].weekday()) % 7 or 7)
    conn.execute(
        "INSERT INTO trading_calendar VALUES (?,FALSE,'weekend') ON CONFLICT DO NOTHING",
        [saturday],
    )
    gate = run_gate(conn, saturday, "NIFTY500", universe_size=6)

    v7 = next(c for c in gate.results if c.check_id == "V7")
    assert not v7.passed and gate.blocked


def test_large_move_without_corporate_action_warns_and_quarantines(conn, universe):
    """V5 is a Warn, not a Block, and the offending row is quarantined."""
    as_of = universe[-1]
    conn.execute(
        "UPDATE ohlcv_daily SET open = 500, high = 520, low = 480, close = 500 "
        "WHERE instrument_token = 1004 AND trade_date = ?",
        [as_of],
    )
    gate = run_gate(conn, as_of, "NIFTY500", universe_size=6)

    v5 = next(c for c in gate.results if c.check_id == "V5")
    assert not v5.passed
    assert v5.severity is Severity.WARN

    quarantined = conn.execute(
        "SELECT count(*) FROM quarantined_rows WHERE check_id = 'V5'"
    ).fetchone()[0]
    assert quarantined >= 1


def test_zero_volume_warns_but_does_not_block(conn, universe):
    as_of = universe[-1]
    conn.execute(
        "UPDATE ohlcv_daily SET volume = 0 WHERE instrument_token = 1003 AND trade_date = ?",
        [as_of],
    )
    gate = run_gate(conn, as_of, "NIFTY500", universe_size=6)

    v6 = next(c for c in gate.results if c.check_id == "V6")
    assert not v6.passed and v6.severity is Severity.WARN
    assert not gate.blocked


def test_cross_source_mismatch_warns(conn, universe):
    """V9: a 0.1% tolerance between independent sources."""
    gate = run_gate(
        conn, universe[-1], "NIFTY500", universe_size=6,
        cross_source_sample={"CLEANUP": (100.0, 105.0)},
    )
    v9 = next(c for c in gate.results if c.check_id == "V9")
    assert not v9.passed and v9.severity is Severity.WARN
    assert not gate.blocked


def test_block_leaves_the_prior_dataset_in_place(conn, universe):
    """FR-4.2: stale-but-correct beats fresh-but-corrupt.

    The gate decides; it must not itself remove what is already served.
    """
    previous, latest = universe[-2], universe[-1]
    compute_metrics_for_date(conn, previous, "NIFTY500")

    conn.execute(
        "UPDATE ohlcv_daily SET high = low - 1 WHERE trade_date = ?", [latest]
    )
    gate = run_gate(conn, latest, "NIFTY500", universe_size=6)
    assert gate.blocked

    served = conn.execute(
        "SELECT count(*) FROM metrics_daily WHERE trade_date = ?", [previous]
    ).fetchone()[0]
    assert served == 6
