"""Performance statistics for a backtest run.

Two sets of every figure are produced: gross of tax (after brokerage, STT,
exchange charges, stamp duty, GST and slippage) and net of tax (additionally
after the TDS an NRI's broker withholds at settlement of each profitable exit,
FR-12.4). Frictions are costs and belong in both; withholding is the thing the
operator is trying to see the size of, so it gets its own column.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, Sequence

import numpy as np

from alpha500.metrics import periods as p


class ClosedTrade(Protocol):
    """What the statistics need from a trade record.

    A structural type rather than an import of ``Trade``, so the engine can
    depend on this module without the dependency running back the other way.
    """

    @property
    def exit_date(self) -> date | None: ...
    @property
    def holding_days(self) -> int: ...
    @property
    def net_return_pct(self) -> float: ...
    @property
    def costs(self) -> float: ...
    @property
    def tds(self) -> float: ...


@dataclass(frozen=True, slots=True)
class Performance:
    """Headline figures for one equity curve."""

    final_equity: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    max_drawdown_days: int
    sharpe: float | None
    sortino: float | None
    volatility_pct: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "final_equity": self.final_equity,
            "total_return_pct": self.total_return_pct,
            "cagr_pct": self.cagr_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_drawdown_days": self.max_drawdown_days,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "volatility_pct": self.volatility_pct,
        }


@dataclass(frozen=True, slots=True)
class TradeStats:
    """Trade-level figures, independent of which equity curve is used."""

    trades: int
    winners: int
    losers: int
    hit_rate_pct: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    win_loss_ratio: float | None
    avg_holding_days: float | None
    median_holding_days: float | None
    exposure_pct: float | None
    total_costs: float
    total_tds: float

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "trades": self.trades,
            "winners": self.winners,
            "losers": self.losers,
            "hit_rate_pct": self.hit_rate_pct,
            "avg_win_pct": self.avg_win_pct,
            "avg_loss_pct": self.avg_loss_pct,
            "win_loss_ratio": self.win_loss_ratio,
            "avg_holding_days": self.avg_holding_days,
            "median_holding_days": self.median_holding_days,
            "exposure_pct": self.exposure_pct,
            "total_costs": self.total_costs,
            "total_tds": self.total_tds,
        }


def _drawdown(equity: np.ndarray) -> tuple[float, int]:
    """Deepest peak-to-trough fall, and the longest time spent below a peak."""
    if equity.size == 0:
        return 0.0, 0
    peaks = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = np.where(peaks > 0, equity / peaks - 1.0, 0.0)
    worst = float(np.nanmin(drawdowns)) if drawdowns.size else 0.0

    longest = current = 0
    for value in drawdowns:
        current = current + 1 if value < 0 else 0
        longest = max(longest, current)
    return worst * 100.0, longest


def performance(
    equity: Sequence[float], sessions: Sequence[date], initial: float
) -> Performance:
    curve = np.asarray(equity, dtype=np.float64)
    if curve.size == 0 or initial <= 0:
        return Performance(initial, 0.0, 0.0, 0.0, 0, None, None, None)

    final = float(curve[-1])
    total_return = (final / initial - 1.0) * 100.0

    # Annualise on trading sessions, matching the rest of the engine's
    # convention (FR-6.1) rather than calendar days.
    years = curve.size / p.YEAR
    cagr = ((final / initial) ** (1.0 / years) - 1.0) * 100.0 if years > 0 and final > 0 else 0.0

    daily = np.diff(curve) / curve[:-1] if curve.size > 1 else np.array([])
    daily = daily[np.isfinite(daily)]

    sharpe = sortino = volatility = None
    if daily.size > 1:
        sd = float(daily.std(ddof=1))
        volatility = sd * math.sqrt(p.YEAR) * 100.0
        if sd > 0:
            sharpe = float(daily.mean()) / sd * math.sqrt(p.YEAR)
        downside = daily[daily < 0]
        if downside.size > 1:
            dsd = float(downside.std(ddof=1))
            if dsd > 0:
                sortino = float(daily.mean()) / dsd * math.sqrt(p.YEAR)

    worst_dd, dd_days = _drawdown(curve)
    return Performance(
        final_equity=final,
        total_return_pct=total_return,
        cagr_pct=cagr,
        max_drawdown_pct=worst_dd,
        max_drawdown_days=dd_days,
        sharpe=sharpe,
        sortino=sortino,
        volatility_pct=volatility,
    )


def trade_stats(
    trades: Sequence[ClosedTrade],
    exposure_samples: Sequence[float],
) -> TradeStats:
    """Aggregate closed trades. ``trades`` are ``Trade`` records from the engine."""
    closed = [t for t in trades if t.exit_date is not None]
    if not closed:
        return TradeStats(
            trades=0, winners=0, losers=0, hit_rate_pct=None,
            avg_win_pct=None, avg_loss_pct=None, win_loss_ratio=None,
            avg_holding_days=None, median_holding_days=None, exposure_pct=None,
            total_costs=0.0, total_tds=0.0,
        )

    returns = np.array([t.net_return_pct for t in closed], dtype=np.float64)
    holding = np.array([t.holding_days for t in closed], dtype=np.float64)

    wins = returns[returns > 0]
    losses = returns[returns <= 0]

    avg_win = float(wins.mean()) if wins.size else None
    avg_loss = float(losses.mean()) if losses.size else None
    ratio = (
        abs(avg_win / avg_loss)
        if avg_win is not None and avg_loss not in (None, 0.0)
        else None
    )

    exposure = (
        float(np.mean(exposure_samples)) * 100.0 if len(exposure_samples) else None
    )

    return TradeStats(
        trades=len(closed),
        winners=int(wins.size),
        losers=int(losses.size),
        hit_rate_pct=float(wins.size) / len(closed) * 100.0,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        win_loss_ratio=ratio,
        avg_holding_days=float(holding.mean()),
        median_holding_days=float(np.median(holding)),
        exposure_pct=exposure,
        total_costs=float(sum(t.costs for t in closed)),
        total_tds=float(sum(t.tds for t in closed)),
    )


@dataclass(frozen=True, slots=True)
class Summary:
    gross: Performance
    net: Performance
    trades: TradeStats
    sessions: int
    start: date | None
    end: date | None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "gross_of_tax": self.gross.as_dict(),
            "net_of_tax": self.net.as_dict(),
            "trades": self.trades.as_dict(),
            "sessions": self.sessions,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "warnings": list(self.warnings),
        }


def summarise(
    gross_equity: Sequence[float],
    net_equity: Sequence[float],
    sessions: Sequence[date],
    trades: Sequence[ClosedTrade],
    exposure_samples: Sequence[float],
    initial: float,
    warnings: Sequence[str] = (),
) -> Summary:
    return Summary(
        gross=performance(gross_equity, sessions, initial),
        net=performance(net_equity, sessions, initial),
        trades=trade_stats(trades, exposure_samples),
        sessions=len(sessions),
        start=sessions[0] if len(sessions) else None,
        end=sessions[-1] if len(sessions) else None,
        warnings=list(warnings),
    )
