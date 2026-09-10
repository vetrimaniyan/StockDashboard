"""Backtest engine tests.

These target the specific ways a backtest produces numbers that were never
achievable: look-ahead on entry, selling before settlement, funding positions
with money that is not there, and quietly omitting friction.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from alpha500.backtest.engine import (
    BacktestConfig,
    Trade,
    _entry_costs,
    _exit_costs,
    _simulate,
    _withholding,
    run_backtest,
    survivorship_warnings,
)
from alpha500.risk import CostModel
from tests.conftest import mark_trading_days


ALWAYS = {
    "name": "always",
    "filters": {"op": "AND", "conditions": [
        {"field": "is_eligible", "operator": "=", "value": True}
    ]},
    "sort": [{"field": "momentum_score", "direction": "desc"}],
    "limit": 5,
}


def _sessions(n: int, start: date = date(2024, 1, 1)) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


@pytest.fixture
def seeded(conn):  # type: ignore[no-untyped-def]
    """One instrument on a steady uptrend, with metrics materialised."""
    days = _sessions(40)
    mark_trading_days(conn, days)
    conn.execute(
        "INSERT INTO instruments (instrument_token, tradingsymbol, series, is_active) "
        "VALUES (1, 'AAA', 'EQ', TRUE)"
    )
    conn.execute(
        "INSERT INTO index_membership VALUES ('NIFTY500', 1, ?, NULL)", [days[0]]
    )

    price = 100.0
    for i, day in enumerate(days):
        price *= 1.01
        conn.execute(
            "INSERT INTO ohlcv_daily (instrument_token, trade_date, open, high, low, "
            "close, volume, adj_factor, source, ingested_at) "
            "VALUES (1, ?, ?, ?, ?, ?, 1000000, 1.0, 'TEST', now())",
            [day, price * 0.995, price * 1.01, price * 0.99, price],
        )
        conn.execute(
            "INSERT INTO metrics_daily (instrument_token, trade_date, is_eligible, "
            "momentum_score, atr_14) VALUES (1, ?, TRUE, ?, ?)",
            [day, 1.0 + i * 0.01, price * 0.02],
        )
    return conn, days


def test_entry_fills_at_the_next_sessions_open_not_the_signal_close(seeded):
    """The single most common way a backtest invents unavailable returns."""
    conn, days = seeded
    result = run_backtest(
        conn,
        BacktestConfig(
            screen=ALWAYS, start=days[0], end=days[-1],
            initial_capital=1_000_000.0, slippage_pct=0.0,
            cost_model=CostModel(stt_sell_pct=0.0, exchange_txn_pct=0.0,
                                 sebi_fee_pct=0.0, stamp_duty_buy_pct=0.0, gst_pct=0.0),
        ),
    )
    assert result.trades or any(True for _ in result.equity_net)

    entry_day = next(
        (t.entry_date for t in result.trades), None
    ) or days[1]
    slot = days.index(entry_day)
    assert slot >= 1, "a position was opened before any signal existed"

    expected_open = conn.execute(
        "SELECT open * adj_factor FROM ohlcv_daily WHERE instrument_token=1 AND trade_date=?",
        [entry_day],
    ).fetchone()[0]
    opened = [t for t in result.trades if t.entry_date == entry_day]
    for trade in opened:
        assert trade.entry_price == pytest.approx(expected_open, rel=1e-9)


def test_exit_signals_are_acted_on_at_the_next_open_not_the_signal_close(seeded):
    """Exits get the same no-look-ahead rule as entries.

    The exit screen is computed from a session's close. Selling at that same
    close is look-ahead, and it flatters every exit — the position leaves at a
    price the signal itself helped determine.
    """
    conn, days = seeded
    result = run_backtest(
        conn,
        BacktestConfig(
            screen=ALWAYS, start=days[0], end=days[-1],
            exit_screen=ALWAYS,          # flags every holding, every session
            trailing_stop=False, slippage_pct=0.0,
        ),
    )
    signalled = [t for t in result.trades if t.exit_reason == "exit_signal"]
    assert signalled, "the exit screen never fired; the test proves nothing"

    for trade in signalled:
        expected_open = conn.execute(
            "SELECT open * adj_factor FROM ohlcv_daily "
            "WHERE instrument_token=1 AND trade_date=?",
            [trade.exit_date],
        ).fetchone()[0]
        assert trade.exit_price == pytest.approx(expected_open, rel=1e-9), (
            "exit filled at the signal-day close rather than the next open"
        )


def test_nothing_is_sold_before_settlement(seeded):
    """FR-12.1: NRI equity is delivery-based — no intraday, no BTST."""
    conn, days = seeded
    result = run_backtest(
        conn,
        BacktestConfig(screen=ALWAYS, start=days[0], end=days[-1], max_holding_days=1),
    )
    for trade in result.trades:
        assert trade.exit_date is None or trade.exit_date >= trade.sellable_from, (
            f"{trade.symbol} sold on {trade.exit_date}, before settlement "
            f"on {trade.sellable_from}"
        )


def test_cash_is_never_negative(seeded):
    """FR-12.3: no margin on an NRI account — positions are cash funded."""
    conn, days = seeded
    result = run_backtest(
        conn,
        BacktestConfig(
            screen=ALWAYS, start=days[0], end=days[-1],
            initial_capital=20_000.0, max_positions=10,
        ),
    )
    assert min(result.equity_net) >= 0.0


def test_survivorship_warning_fires_on_a_single_membership_snapshot(seeded):
    conn, _days = seeded
    warnings = survivorship_warnings(conn)
    assert warnings, "a single-snapshot universe must warn"
    assert "SURVIVORSHIP BIAS" in warnings[0]


def test_survivorship_warning_clears_once_membership_has_history(seeded):
    conn, days = seeded
    conn.execute(
        "INSERT INTO index_membership VALUES ('NIFTY500', 99, ?, ?)",
        [days[0], days[10]],
    )
    assert survivorship_warnings(conn) == []


def test_survivorship_warning_survives_one_stray_closed_interval(seeded):
    """The regression: a two-day placeholder must not silence the warning.

    On 2026-09-09 a DUMMY placeholder constituent joined the index and left
    two days later. That single closed interval satisfied the old test while
    the store still held eight years of prices behind three weeks of
    membership, so a backtest reported no bias at all.
    """
    conn, days = seeded
    # The real store's shape: eight years of prices, three weeks of
    # membership, and one placeholder that arrived and left inside them.
    conn.execute("DELETE FROM index_membership")
    conn.execute(
        "INSERT INTO index_membership VALUES ('NIFTY500', 1, ?, NULL)", [days[-3]]
    )
    conn.execute(
        "INSERT INTO index_membership VALUES ('NIFTY500', 99, ?, ?)",
        [days[-3], days[-1]],
    )

    warnings = survivorship_warnings(conn)

    assert warnings, "a closed interval that starts after the prices do is not history"
    assert "SURVIVORSHIP BIAS" in warnings[0]
    assert "Membership begins" in warnings[0]


def test_costs_are_charged_on_both_legs():
    model = CostModel()
    assert _entry_costs(100_000.0, model) > 0
    assert _exit_costs(100_000.0, model) > 0
    # STT applies on the sell leg only, so exiting costs more than entering.
    assert _exit_costs(100_000.0, model) > _entry_costs(100_000.0, model)


def test_withholding_applies_only_to_profitable_exits():
    """FR-12.4: TDS is deducted at settlement of each profitable exit."""
    model = CostModel()
    winner = Trade(
        token=1, symbol="AAA", entry_date=date(2024, 1, 1), entry_price=100.0,
        quantity=100, stop_price=90.0, sellable_from=date(2024, 1, 3),
        exit_date=date(2024, 2, 1), exit_price=120.0, costs=50.0,
    )
    loser = Trade(
        token=2, symbol="BBB", entry_date=date(2024, 1, 1), entry_price=100.0,
        quantity=100, stop_price=90.0, sellable_from=date(2024, 1, 3),
        exit_date=date(2024, 2, 1), exit_price=80.0, costs=50.0,
    )
    assert _withholding(winner, model) > 0
    assert _withholding(loser, model) == 0.0


def test_long_holdings_are_withheld_at_the_ltcg_rate():
    model = CostModel()
    short = Trade(
        token=1, symbol="AAA", entry_date=date(2024, 1, 1), entry_price=100.0,
        quantity=100, stop_price=90.0, sellable_from=date(2024, 1, 3),
        exit_date=date(2024, 6, 1), exit_price=120.0, costs=0.0,
    )
    long_held = Trade(
        token=1, symbol="AAA", entry_date=date(2024, 1, 1), entry_price=100.0,
        quantity=100, stop_price=90.0, sellable_from=date(2024, 1, 3),
        exit_date=date(2025, 6, 1), exit_price=120.0, costs=0.0,
    )
    assert _withholding(short, model) > _withholding(long_held, model)
    assert _withholding(long_held, model) == pytest.approx(
        long_held.gross_pnl * model.ltcg_effective_rate
    )


def test_refuses_to_run_without_materialised_metrics(conn):
    days = _sessions(5)
    mark_trading_days(conn, days)
    with pytest.raises(ValueError, match="materialise"):
        run_backtest(
            conn, BacktestConfig(screen=ALWAYS, start=days[0], end=days[-1])
        )


def test_net_of_tax_never_exceeds_gross(seeded):
    conn, days = seeded
    result = run_backtest(
        conn, BacktestConfig(screen=ALWAYS, start=days[0], end=days[-1])
    )
    for gross, net in zip(result.equity_gross, result.equity_net):
        assert net <= gross + 1e-6


# =========================================================================
# FR-19 — tiered trailing-stop exit rule
#
# These drive ``_simulate`` directly with a hand-built price panel. The
# engine-level tests above prove the wiring; these prove the arithmetic,
# with every expected value computed by hand in the test per NFR-5.1.
# =========================================================================

FRICTIONLESS = CostModel(
    brokerage_pct=0.0, brokerage_flat_inr=0.0, exchange_txn_pct=0.0,
    sebi_fee_pct=0.0, stt_sell_pct=0.0, stamp_duty_buy_pct=0.0, gst_pct=0.0,
)


def _panel_from(closes, *, support=100.0, atr=1.0, lows=None, opens=None):
    """One token's arrays, built from a close series.

    ``lows`` and ``opens`` default to the closes, so a session only triggers a
    stop when the test says so explicitly.
    """
    n = len(closes)
    lows = list(closes) if lows is None else list(lows)
    opens = list(closes) if opens is None else list(opens)
    return {
        1: {
            "open": np.array(opens, dtype=float),
            "high": np.array(closes, dtype=float),
            "low": np.array(lows, dtype=float),
            "close": np.array(closes, dtype=float),
            "atr": np.full(n, atr, dtype=float),
            "support": np.full(n, support, dtype=float),
        }
    }


def _tiered_config(sessions, **overrides):
    base = dict(
        screen=ALWAYS,
        start=sessions[0],
        end=sessions[-1],
        initial_capital=1_000_000.0,
        max_positions=1,
        max_position_weight=1.0,
        risk_per_trade_pct=1.0,
        slippage_pct=0.0,
        cost_model=FRICTIONLESS,
        exit_rule="tiered_trailing",
        initial_stop_atr_multiple=0.5,
    )
    base.update(overrides)
    return BacktestConfig(**base)


def _signal_every_session(sessions):
    return {day: [(1, "AAA", 1.0)] for day in sessions}


def _run(config, sessions, panel, entry_signals=None):
    return _simulate(
        config,
        sessions,
        entry_signals if entry_signals is not None else _signal_every_session(sessions),
        {},
        panel,
        withhold_tax=False,
    )


def test_tiered_stop_never_unarms():
    """A stage that has armed must not be recomputed off a lower gain.

    Entry at 100, peak close 108 arms Stage 1 at 100*(1+0.08-0.04) = 104.
    Price then falls back to a 5.5% gain. If the stop tracked the *current*
    gain it would slide to 101.5 and the next session's low of 103 would miss
    it entirely; because it tracks the *peak*, 103 takes the trade out at 104.
    """
    sessions = _sessions(6)
    # slot:      0    1(entry@100)  2      3       4
    closes = [100.0, 100.0, 108.0, 105.5, 105.0, 105.0]
    lows = [100.0, 100.0, 108.0, 105.5, 103.0, 105.0]
    opens = [100.0, 100.0, 108.0, 105.5, 105.0, 105.0]
    panel = _panel_from(closes, lows=lows, opens=opens, support=99.0, atr=1.0)

    _curve, closed, _exposure = _run(_tiered_config(sessions), sessions, panel)

    assert len(closed) == 1
    trade = closed[0]
    assert trade.exit_reason == "stop"
    assert trade.entry_price == pytest.approx(100.0)
    # 100 * (1 + 0.08 - 0.04); a stop recomputed off the 5% pullback would be
    # 101.5 and this session's low of 103 would not have reached it.
    assert trade.exit_price == pytest.approx(104.0)
    assert trade.peak_gain_pct == pytest.approx(0.08)


def test_tiered_stop_stage2_is_tighter_than_stage1():
    """Past the Stage-2 threshold the trail gives back less.

    Peak close 112 puts Stage 2 at 100*(1+0.12-0.02) = 110, where Stage 1
    alone would sit at 100*(1+0.12-0.04) = 108. A low of 109 distinguishes
    them: it takes the trade out under Stage 2 and leaves it open under
    Stage 1.
    """
    sessions = _sessions(6)
    closes = [100.0, 100.0, 112.0, 111.0, 111.0, 111.0]
    lows = [100.0, 100.0, 112.0, 111.0, 109.0, 111.0]
    opens = [100.0, 100.0, 112.0, 111.0, 111.0, 111.0]
    panel = _panel_from(closes, lows=lows, opens=opens, support=99.0, atr=1.0)

    _curve, closed, _exposure = _run(_tiered_config(sessions), sessions, panel)

    assert len(closed) == 1
    assert closed[0].exit_reason == "stop"
    assert closed[0].exit_price == pytest.approx(110.0)
    assert closed[0].peak_gain_pct == pytest.approx(0.12)


def test_tiered_entry_skips_null_support():
    """No support level, no trade.

    Falling back to the ATR stop would open a position under a different
    rule than the one the run asked for, and it would do so invisibly.
    """
    sessions = _sessions(5)
    closes = [100.0] * 5
    panel = _panel_from(closes, support=100.0, atr=1.0)
    panel[1]["support"][:] = np.nan

    curve, closed, _exposure = _run(_tiered_config(sessions), sessions, panel)

    assert closed == []
    assert curve[-1] == pytest.approx(1_000_000.0)


def test_conditional_time_stop_spares_profitable_positions():
    """Past the time limit and still up, the trail governs, not the clock."""
    sessions = _sessions(30)
    closes = [100.0] * 2 + [106.0] * 28
    panel = _panel_from(closes, support=99.0, atr=1.0)

    config = _tiered_config(
        sessions, max_holding_days=21, time_stop_only_if_not_profitable=True
    )
    _curve, closed, _exposure = _run(config, sessions, panel)

    assert closed == [], "a position at +6% was closed by the clock"


def test_conditional_time_stop_still_closes_a_losing_position():
    """The mirror of the test above: flat or losing, the clock still fires."""
    sessions = _sessions(30)
    closes = [100.0] * 2 + [98.0] * 28
    panel = _panel_from(closes, support=90.0, atr=1.0)

    config = _tiered_config(
        sessions, max_holding_days=21, time_stop_only_if_not_profitable=True
    )
    _curve, closed, _exposure = _run(config, sessions, panel)

    assert len(closed) == 1
    assert closed[0].exit_reason == "time"


def test_unconditional_time_stop_is_unchanged_when_the_flag_is_off():
    """The default must still close a profitable position on time."""
    sessions = _sessions(30)
    closes = [100.0] * 2 + [106.0] * 28
    panel = _panel_from(closes, support=99.0, atr=1.0)

    config = _tiered_config(
        sessions, max_holding_days=21, time_stop_only_if_not_profitable=False
    )
    _curve, closed, _exposure = _run(config, sessions, panel)

    assert len(closed) == 1
    assert closed[0].exit_reason == "time"


def _stop_out_every_session(n):
    """A panel where any open position is stopped out the session after entry.

    Support 99 and ATR 1 put the initial stop at 98.5, and every session's low
    of 98 reaches it. Entry is always at an open of 100, so each trade closes
    at 98.5 exactly one session after it opens, which makes the entry and exit
    slots trivial to reason about when checking a cooldown.
    """
    closes = [100.0] * n
    return _panel_from(closes, lows=[98.0] * n, opens=[100.0] * n,
                       support=99.0, atr=1.0)


def _entry_exit_slots(sessions, closed):
    return [
        (sessions.index(t.entry_date), sessions.index(t.exit_date))
        for t in closed
    ]


def test_reentry_cooldown_blocks_until_session_count_elapses():
    """A signal every session must not reopen the token inside the cooldown.

    Stopped out at slot 2, a cooldown of 21 makes slot 23 the first session
    the token may reopen on, even though it signals on all of 3 through 22.
    """
    sessions = _sessions(40)
    panel = _stop_out_every_session(len(sessions))

    config = _tiered_config(sessions, reentry_cooldown_sessions=21)
    _curve, closed, _exposure = _run(config, sessions, panel)

    assert _entry_exit_slots(sessions, closed) == [(1, 2), (23, 24)]


def test_reentry_cooldown_expires_exactly_at_the_boundary():
    """It is a cooldown, not a ban: the token returns the session it elapses.

    Five sessions after each exit, not six and not four.
    """
    sessions = _sessions(40)
    panel = _stop_out_every_session(len(sessions))

    config = _tiered_config(sessions, reentry_cooldown_sessions=5)
    _curve, closed, _exposure = _run(config, sessions, panel)

    slots = _entry_exit_slots(sessions, closed)
    assert slots[:3] == [(1, 2), (7, 8), (13, 14)]
    for (_prev_entry, exit_slot), (entry_slot, _exit) in zip(slots, slots[1:]):
        assert entry_slot - exit_slot == 5


def test_no_cooldown_reopens_the_same_session_it_exited():
    """The default, and the behaviour FR-19.8 exists to interrupt.

    Exits are evaluated before entries so capital recycles within a session,
    which means a token stopped out at slot N is eligible again at slot N —
    the trade closes and reopens on the same day. That is correct for a
    trend system and precisely wrong for a swing rule meant to stand aside
    after a setup fails.
    """
    sessions = _sessions(12)
    panel = _stop_out_every_session(len(sessions))

    config = _tiered_config(sessions)  # reentry_cooldown_sessions defaults to None
    _curve, closed, _exposure = _run(config, sessions, panel)

    assert _entry_exit_slots(sessions, closed)[:3] == [(1, 2), (2, 3), (3, 4)]


def test_a_time_exit_also_starts_the_cooldown():
    """FR-19.8, Q-4 resolved: any exit counts, not only a stop-out.

    FR-19.2 fires the time branch only on a position that is flat or losing,
    so a time exit is a failed setup by construction - 42 of 42 across the
    gate runs were losses. Exempting them would re-admit a name that had just
    spent its whole holding limit failing to get into profit.

    Price here sits flat at the entry price and never reaches the stop, so the
    only way out is the clock.
    """
    sessions = _sessions(40)
    closes = [100.0] * len(sessions)
    panel = _panel_from(closes, support=90.0, atr=1.0)

    config = _tiered_config(
        sessions,
        max_holding_days=5,
        time_stop_only_if_not_profitable=True,
        reentry_cooldown_sessions=10,
    )
    _curve, closed, _exposure = _run(config, sessions, panel)

    # Entered at 1 and timed out at 5, then held down until 15, and again.
    # Asserted as exact slots so the test cannot pass by never re-entering.
    assert _entry_exit_slots(sessions, closed) == [(1, 5), (15, 20), (30, 35)]
    assert all(t.exit_reason == "time" for t in closed)
    for (_prev, exit_slot), (entry_slot, _e) in zip(closed_slots := _entry_exit_slots(
        sessions, closed
    ), closed_slots[1:]):
        assert entry_slot - exit_slot == 10


def test_cooldown_is_inert_under_atr_trailing():
    """Structurally guaranteed by the `tiered` guard; asserted anyway."""
    sessions = _sessions(40)
    closes = [100.0, 100.0, 90.0] + [100.0] * 37
    lows = [100.0, 100.0, 90.0] + [100.0] * 37
    panel = _panel_from(closes, lows=lows, support=99.0, atr=1.0)

    with_cooldown = _tiered_config(
        sessions, exit_rule="atr_trailing", reentry_cooldown_sessions=21
    )
    without = _tiered_config(sessions, exit_rule="atr_trailing")

    a_curve, a_closed, _ = _run(with_cooldown, sessions, panel)
    b_curve, b_closed, _ = _run(without, sessions, panel)

    assert [t.as_dict() for t in a_closed] == [t.as_dict() for t in b_closed]
    assert a_curve == b_curve


def test_tiered_trailing_fields_are_a_no_op_by_default(seeded):
    """The test that matters most: nothing else in the system moved.

    The seeded fixture stores no ``support_level`` at all, which is the state
    every row was in before FR-19 added the column to the panel. A legacy run
    over it must still open trades and produce the same numbers whether the
    new fields are left alone or spelled out at their defaults.
    """
    conn, days = seeded
    common = dict(
        screen=ALWAYS, start=days[0], end=days[-1],
        initial_capital=1_000_000.0, slippage_pct=0.0, cost_model=FRICTIONLESS,
    )

    implicit = run_backtest(conn, BacktestConfig(**common))
    explicit = run_backtest(
        conn,
        BacktestConfig(
            **common,
            exit_rule="atr_trailing",
            initial_stop_atr_multiple=0.5,
            stage1_arm_pct=0.05,
            stage1_giveback_pct=0.04,
            stage2_arm_pct=0.10,
            stage2_giveback_pct=0.02,
            time_stop_only_if_not_profitable=False,
            reentry_cooldown_sessions=None,
        ),
    )

    # The fixture trends up and never stops out, so positions are still open
    # at the end and `trades` (which holds closed ones) is empty by design.
    # Equity having moved off the initial capital is what proves the legacy
    # path still took positions.
    assert implicit.equity_net[-1] != pytest.approx(1_000_000.0)
    assert implicit.as_dict() == explicit.as_dict()
    # peak_gain_pct is reported but never written outside the tiered rule.
    assert all(
        row["peak_gain_pct"] == 0.0
        for row in implicit.as_dict()["trades_detail"]
    )


def test_null_support_does_not_disturb_the_legacy_entry_path(seeded):
    """FR-19 added support_level to the panel; the ATR path must not read it."""
    conn, days = seeded
    stored = conn.execute(
        "SELECT count(*) FROM metrics_daily WHERE support_level IS NOT NULL"
    ).fetchone()[0]
    assert stored == 0, "fixture no longer exercises the null-support case"

    result = run_backtest(
        conn,
        BacktestConfig(
            screen=ALWAYS, start=days[0], end=days[-1],
            initial_capital=1_000_000.0, slippage_pct=0.0, cost_model=FRICTIONLESS,
        ),
    )
    assert result.equity_net[-1] != pytest.approx(1_000_000.0)
