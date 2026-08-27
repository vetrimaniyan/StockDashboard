"""Point-in-time backtest simulation (SRS Phase 3).

The rules that matter, and why:

* **Entry on the next session's open.** A signal computed from session T's close
  could not have been acted on at that close. Entering at T's close is the most
  common way a backtest invents returns that were never available.
* **Metrics are read as of the signal date only.** ``metrics_daily`` at date T
  is a function of prices up to T, so no row can see its own future.
* **Long only** (FR-12.2), **cash only** (FR-12.3, no margin on NRI accounts),
  and **no exit before settlement** (FR-12.1, delivery-based trading — intraday
  and BTST are not permitted).
* **Friction on both legs**, plus TDS withheld from each profitable exit at
  settlement rather than at filing (FR-12.4).

What this engine cannot fix is stated loudly rather than hidden: see
``survivorship_warnings``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Sequence

import duckdb
import numpy as np

from alpha500.backtest.stats import Summary, summarise
from alpha500.risk import CostModel, earliest_sellable_date
from alpha500.screens.filter_engine import compile_screen


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    screen: dict[str, Any]
    start: date
    end: date
    initial_capital: float = 1_000_000.0
    max_positions: int = 10
    risk_per_trade_pct: float = 0.0075
    max_position_weight: float = 0.10
    stop_atr_multiple: float = 2.0
    trailing_stop: bool = True
    max_holding_days: int | None = None
    slippage_pct: float = 0.0015
    cost_model: CostModel = field(default_factory=CostModel)
    exit_screen: dict[str, Any] | None = None


@dataclass(slots=True)
class Trade:
    token: int
    symbol: str
    entry_date: date
    entry_price: float
    quantity: int
    stop_price: float
    sellable_from: date
    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    costs: float = 0.0
    tds: float = 0.0

    @property
    def holding_days(self) -> int:
        if self.exit_date is None:
            return 0
        return (self.exit_date - self.entry_date).days

    @property
    def gross_pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.quantity

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.costs - self.tds

    @property
    def net_return_pct(self) -> float:
        cost_basis = self.entry_price * self.quantity
        return (self.net_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date.isoformat(),
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "holding_days": self.holding_days,
            "gross_pnl": self.gross_pnl,
            "costs": self.costs,
            "tds": self.tds,
            "net_pnl": self.net_pnl,
            "net_return_pct": self.net_return_pct,
        }


@dataclass(slots=True)
class BacktestResult:
    summary: Summary
    trades: list[Trade]
    equity_gross: list[float]
    equity_net: list[float]
    sessions: list[date]

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.summary.as_dict(),
            "trades_detail": [t.as_dict() for t in self.trades],
            "equity_curve": [
                {"date": d.isoformat(), "gross": g, "net": n}
                for d, g, n in zip(self.sessions, self.equity_gross, self.equity_net)
            ],
        }


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def _sessions(conn: duckdb.DuckDBPyConnection, start: date, end: date) -> list[date]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT trade_date FROM metrics_daily "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [start, end],
        ).fetchall()
    ]


def signals_over_range(
    conn: duckdb.DuckDBPyConnection,
    definition: dict[str, Any],
    start: date,
    end: date,
) -> dict[date, list[tuple[int, str, float | None]]]:
    """Screen matches for every session in one query.

    Running the screen once per session would issue 1 200+ round trips per
    parameter combination, which makes walk-forward evaluation impractical.
    """
    compiled = compile_screen(definition)
    sort_field = definition.get("sort", [{}])[0].get("field") or "momentum_score"

    sql = f"""
        SELECT m.trade_date, m.instrument_token, i.tradingsymbol, m.{sort_field}
          FROM metrics_daily m
          JOIN instruments i ON i.instrument_token = m.instrument_token
         WHERE m.trade_date BETWEEN ? AND ? AND ({compiled.where_sql})
         ORDER BY m.trade_date, m.{sort_field} DESC NULLS LAST
    """
    rows = conn.execute(sql, [start, end, *compiled.params]).fetchall()

    out: dict[date, list[tuple[int, str, float | None]]] = {}
    for trade_date, token, symbol, score in rows:
        out.setdefault(trade_date, []).append((int(token), str(symbol), score))

    limit = definition.get("limit")
    if limit:
        for day, matches in out.items():
            out[day] = matches[: int(limit)]
    return out


def _price_panel(
    conn: duckdb.DuckDBPyConnection, start: date, end: date
) -> tuple[dict[int, dict[str, np.ndarray]], dict[date, int]]:
    """Adjusted OHLC per token, aligned to a shared session index."""
    sessions = _sessions(conn, start, end)
    index = {day: i for i, day in enumerate(sessions)}

    rows = conn.execute(
        """
        SELECT o.instrument_token, o.trade_date,
               o.open * o.adj_factor, o.high * o.adj_factor,
               o.low * o.adj_factor, o.close * o.adj_factor,
               m.atr_14
          FROM ohlcv_daily o
          JOIN metrics_daily m
            ON m.instrument_token = o.instrument_token AND m.trade_date = o.trade_date
         WHERE o.trade_date BETWEEN ? AND ?
         ORDER BY o.instrument_token, o.trade_date
        """,
        [start, end],
    ).fetchall()

    n = len(sessions)
    panel: dict[int, dict[str, np.ndarray]] = {}
    for token, day, op, hi, lo, cl, atr in rows:
        token = int(token)
        slot = index.get(day)
        if slot is None:
            continue
        arrays = panel.get(token)
        if arrays is None:
            arrays = {
                name: np.full(n, np.nan) for name in ("open", "high", "low", "close", "atr")
            }
            panel[token] = arrays
        arrays["open"][slot] = op if op is not None else np.nan
        arrays["high"][slot] = hi if hi is not None else np.nan
        arrays["low"][slot] = lo if lo is not None else np.nan
        arrays["close"][slot] = cl if cl is not None else np.nan
        arrays["atr"][slot] = atr if atr is not None else np.nan
    return panel, index


# --------------------------------------------------------------------------
# Cost model
# --------------------------------------------------------------------------

def _entry_costs(value: float, model: CostModel) -> float:
    brokerage = value * model.brokerage_pct + model.brokerage_flat_inr
    charges = value * (model.exchange_txn_pct + model.sebi_fee_pct)
    stamp = value * model.stamp_duty_buy_pct
    gst = (brokerage + charges) * model.gst_pct
    return brokerage + charges + stamp + gst


def _exit_costs(value: float, model: CostModel) -> float:
    brokerage = value * model.brokerage_pct + model.brokerage_flat_inr
    charges = value * (model.exchange_txn_pct + model.sebi_fee_pct)
    stt = value * model.stt_sell_pct
    gst = (brokerage + charges) * model.gst_pct
    return brokerage + charges + stt + gst


def _withholding(trade: Trade, model: CostModel) -> float:
    """TDS on the realised gain, withheld at settlement (FR-12.4).

    Only profitable exits are withheld from, and the rate depends on whether
    the holding crossed twelve months.
    """
    gain = trade.gross_pnl - trade.costs
    if gain <= 0:
        return 0.0
    rate = (
        model.ltcg_effective_rate
        if trade.holding_days >= 365
        else model.stcg_effective_rate
    )
    return gain * rate


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def survivorship_warnings(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """State plainly what the available data cannot support.

    FR-13 (Phase 3) requires point-in-time universe reconstruction from
    ``index_membership``, because "a backtest run on today's constituent list
    is worthless and worse than no backtest, since it produces confident wrong
    numbers". That warning is aimed squarely at this situation, so the result
    carries it rather than burying it.
    """
    warnings: list[str] = []
    row = conn.execute(
        "SELECT count(DISTINCT valid_from), count(*) FILTER (WHERE valid_to IS NOT NULL) "
        "FROM index_membership"
    ).fetchone()
    distinct_starts, closed = (row or (0, 0))

    if distinct_starts <= 1 and not closed:
        warnings.append(
            "SURVIVORSHIP BIAS: index_membership holds a single snapshot with no "
            "closed intervals, so the universe cannot be reconstructed as it stood "
            "on any past date. Every symbol tested is a *current* NIFTY 500 member; "
            "constituents that were dropped over the period were never ingested at "
            "all. Results are biased upward by an unknown but material amount and "
            "MUST NOT be read as achievable returns."
        )
    return warnings


def run_backtest(
    conn: duckdb.DuckDBPyConnection, config: BacktestConfig
) -> BacktestResult:
    """Simulate the strategy twice: with TDS withheld, and without.

    The two runs cannot be derived from one another. Withholding takes cash out
    at each profitable exit, so the net path compounds on a smaller base and
    subsequently sizes smaller positions — it does not merely lag the gross
    path by the tax paid. Reconstructing one curve by adding cumulative tax
    back to the other understates the untaxed path and, worse, produces a
    drawdown profile that belongs to neither.
    """
    sessions = _sessions(conn, config.start, config.end)
    if len(sessions) < 2:
        raise ValueError(
            f"Need at least two sessions of materialised metrics between "
            f"{config.start} and {config.end}; found {len(sessions)}. "
            "Run 'alpha500 materialise' first."
        )

    entry_signals = signals_over_range(conn, config.screen, config.start, config.end)
    exit_signals = (
        signals_over_range(conn, config.exit_screen, config.start, config.end)
        if config.exit_screen
        else {}
    )
    panel, _index = _price_panel(conn, config.start, config.end)

    net_equity, trades, exposure = _simulate(
        config, sessions, entry_signals, exit_signals, panel, withhold_tax=True
    )
    gross_equity, _gross_trades, _gross_exposure = _simulate(
        config, sessions, entry_signals, exit_signals, panel, withhold_tax=False
    )

    summary = summarise(
        gross_equity=gross_equity,
        net_equity=net_equity,
        sessions=sessions,
        trades=trades,
        exposure_samples=exposure,
        initial=config.initial_capital,
        warnings=survivorship_warnings(conn),
    )
    return BacktestResult(summary, trades, gross_equity, net_equity, sessions)


def _simulate(
    config: BacktestConfig,
    sessions: list[date],
    entry_signals: dict[date, list[tuple[int, str, float | None]]],
    exit_signals: dict[date, list[tuple[int, str, float | None]]],
    panel: dict[int, dict[str, np.ndarray]],
    withhold_tax: bool,
) -> tuple[list[float], list[Trade], list[float]]:
    model = config.cost_model

    cash = config.initial_capital
    tax_paid = 0.0
    open_trades: dict[int, Trade] = {}
    closed: list[Trade] = []
    curve: list[float] = []
    exposure: list[float] = []

    def mark_to_market(slot: int) -> float:
        total = 0.0
        for token, trade in open_trades.items():
            arrays = panel.get(token)
            price = arrays["close"][slot] if arrays is not None else np.nan
            if not np.isfinite(price):
                price = trade.entry_price
            total += price * trade.quantity
        return total

    exit_token_sets = {
        day: {token for token, _symbol, _score in matches}
        for day, matches in exit_signals.items()
    }

    for slot, session in enumerate(sessions):
        previous_session = sessions[slot - 1] if slot > 0 else None
        exit_tokens_prev = (
            exit_token_sets.get(previous_session, frozenset())
            if previous_session is not None
            else frozenset()
        )

        # ---- exits, evaluated before new entries so capital recycles -----
        for token in list(open_trades):
            trade = open_trades[token]
            arrays = panel.get(token)
            if arrays is None:
                continue
            low = arrays["low"][slot]
            open_px = arrays["open"][slot]
            close_px = arrays["close"][slot]
            if not np.isfinite(close_px):
                continue

            # FR-12.1: delivery-based only; nothing may be sold before credit.
            if session < trade.sellable_from:
                continue

            reason: str | None = None
            fill: float | None = None

            if np.isfinite(low) and low <= trade.stop_price:
                # A gap through the stop fills at the open, not at the stop.
                fill = min(open_px, trade.stop_price) if np.isfinite(open_px) else trade.stop_price
                reason = "stop"
            elif previous_session is not None and token in exit_tokens_prev:
                # The exit screen is computed from a session's close, so it can
                # only be acted on at the next open — the same rule that governs
                # entries. Selling at the close that produced the signal would
                # be look-ahead, and it flatters every exit.
                if not np.isfinite(open_px):
                    continue
                fill = open_px
                reason = "exit_signal"
            elif (
                config.max_holding_days is not None
                and (session - trade.entry_date).days >= config.max_holding_days
            ):
                if not np.isfinite(open_px):
                    continue
                fill = open_px
                reason = "time"

            if reason is None:
                if config.trailing_stop and np.isfinite(arrays["atr"][slot]):
                    trailed = close_px - config.stop_atr_multiple * arrays["atr"][slot]
                    trade.stop_price = max(trade.stop_price, trailed)
                continue

            fill_price = fill * (1.0 - config.slippage_pct)
            proceeds = fill_price * trade.quantity
            trade.exit_date = session
            trade.exit_price = fill_price
            trade.exit_reason = reason
            exit_cost = _exit_costs(proceeds, model)
            trade.costs += exit_cost
            trade.tds = _withholding(trade, model) if withhold_tax else 0.0

            # FR-12.4: withholding leaves the account at settlement, so it is
            # deducted from cash here rather than accrued for year-end.
            cash += proceeds - exit_cost - trade.tds
            tax_paid += trade.tds
            closed.append(trade)
            del open_trades[token]

        # ---- entries: yesterday's signal, filled at today's open ---------
        if slot > 0 and len(open_trades) < config.max_positions:
            previous = sessions[slot - 1]
            for token, symbol, _score in entry_signals.get(previous, []):
                if len(open_trades) >= config.max_positions:
                    break
                if token in open_trades:
                    continue
                arrays = panel.get(token)
                if arrays is None:
                    continue
                open_px = arrays["open"][slot]
                atr = arrays["atr"][slot - 1]
                if not np.isfinite(open_px) or open_px <= 0 or not np.isfinite(atr):
                    continue

                fill_price = open_px * (1.0 + config.slippage_pct)
                stop = fill_price - config.stop_atr_multiple * atr
                if stop <= 0 or stop >= fill_price:
                    continue

                equity_now = cash + mark_to_market(slot)
                risk_amount = equity_now * config.risk_per_trade_pct
                quantity = math.floor(risk_amount / (fill_price - stop))
                max_value = equity_now * config.max_position_weight
                if quantity * fill_price > max_value:
                    quantity = math.floor(max_value / fill_price)
                if quantity <= 0:
                    continue

                cost_basis = quantity * fill_price
                entry_cost = _entry_costs(cost_basis, model)
                # FR-12.3: cash only. No position may be funded on margin.
                if cost_basis + entry_cost > cash:
                    quantity = math.floor((cash - entry_cost) / fill_price)
                    if quantity <= 0:
                        continue
                    cost_basis = quantity * fill_price
                    entry_cost = _entry_costs(cost_basis, model)
                    if cost_basis + entry_cost > cash:
                        continue

                cash -= cost_basis + entry_cost
                open_trades[token] = Trade(
                    token=token,
                    symbol=symbol,
                    entry_date=session,
                    entry_price=fill_price,
                    quantity=quantity,
                    stop_price=stop,
                    sellable_from=earliest_sellable_date(session),
                    costs=entry_cost,
                )

        held = mark_to_market(slot)
        equity = cash + held
        curve.append(equity)
        exposure.append(held / equity if equity > 0 else 0.0)

    return curve, closed, exposure
