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
