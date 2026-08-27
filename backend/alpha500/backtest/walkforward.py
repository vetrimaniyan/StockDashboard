"""Walk-forward evaluation and overfitting detection (SRS Phase 3).

A parameter sweep always produces a winner. The question that matters is
whether that winner is a *plateau* — surrounded by neighbours that also work,
suggesting a real effect — or a *narrow peak*, which is the signature of a
value that fits this particular history and nothing else.

The SRS requires the warning to be surfaced explicitly rather than left for the
operator to infer, so ``sweep`` returns a verdict alongside the numbers.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Sequence

import duckdb
import numpy as np

from alpha500.backtest.engine import BacktestConfig, run_backtest
from alpha500.metrics import periods as p


@dataclass(frozen=True, slots=True)
class Window:
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def as_dict(self) -> dict[str, str]:
        return {
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
        }


def build_windows(
    sessions: Sequence[date], train_sessions: int, test_sessions: int, step: int | None = None
) -> list[Window]:
    """Rolling train/test splits with no overlap between a split's own halves."""
    step = step or test_sessions
    windows: list[Window] = []
    start = 0
    while start + train_sessions + test_sessions <= len(sessions):
        train = sessions[start : start + train_sessions]
        test = sessions[start + train_sessions : start + train_sessions + test_sessions]
        windows.append(Window(train[0], train[-1], test[0], test[-1]))
        start += step
    return windows


@dataclass(frozen=True, slots=True)
class SweepPoint:
    value: Any
    metric: float
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SweepVerdict:
    best_value: Any
    best_metric: float
    is_narrow_peak: bool
    plateau_width: int
    warning: str | None
    points: list[SweepPoint]

    def as_dict(self) -> dict[str, Any]:
        return {
            "best_value": self.best_value,
            "best_metric": self.best_metric,
            "is_narrow_peak": self.is_narrow_peak,
            "plateau_width": self.plateau_width,
            "warning": self.warning,
            "points": [
                {"value": pt.value, "metric": pt.metric, **pt.detail} for pt in self.points
            ],
        }


def assess_peak(points: Sequence[SweepPoint], tolerance: float = 0.25) -> SweepVerdict:
    """Is the sweep's best result a plateau or an isolated spike?

    ``tolerance`` is the fraction of the best score a neighbour must reach to
    count as part of the same plateau. A best value that stands alone — whose
    immediate neighbours fall away sharply — is flagged.
    """
    usable = [pt for pt in points if np.isfinite(pt.metric)]
    if not usable:
        return SweepVerdict(None, float("nan"), False, 0, "no usable results", list(points))

    best_index = max(range(len(usable)), key=lambda i: usable[i].metric)
    best = usable[best_index]

    if best.metric <= 0:
        return SweepVerdict(
            best.value, best.metric, False, 0,
            "Best parameter produced a non-positive result; nothing here is worth "
            "optimising toward.",
            list(points),
        )

    threshold = best.metric * (1.0 - tolerance)
    width = 1
    for i in range(best_index - 1, -1, -1):
        if usable[i].metric >= threshold:
            width += 1
        else:
            break
    for i in range(best_index + 1, len(usable)):
        if usable[i].metric >= threshold:
            width += 1
        else:
            break

    narrow = width < 3 and len(usable) >= 3
    warning = None
    if narrow:
        warning = (
            f"OVERFITTING RISK: the best value ({best.value!r}) is a narrow peak — "
            f"only {width} of {len(usable)} tested values come within "
            f"{int(tolerance * 100)}% of it. A parameter that works at one setting "
            "and fails on either side is usually fitted to this particular history "
            "rather than to a real effect. Prefer a value from a plateau."
        )
    return SweepVerdict(best.value, best.metric, narrow, width, warning, list(points))


def sweep(
    conn: duckdb.DuckDBPyConnection,
    base: BacktestConfig,
    values: Sequence[Any],
    apply_value: Callable[[BacktestConfig, Any], BacktestConfig],
    objective: Callable[[Any], float] | None = None,
) -> SweepVerdict:
    """Run the backtest once per parameter value and judge the resulting curve."""
    score = objective or (lambda result: result.summary.net.cagr_pct)
    points: list[SweepPoint] = []
    for value in values:
        config = apply_value(base, value)
        result = run_backtest(conn, config)
        points.append(
            SweepPoint(
                value=value,
                metric=float(score(result)),
                detail={
                    "trades": result.summary.trades.trades,
                    "max_drawdown_pct": result.summary.net.max_drawdown_pct,
                    "sharpe": result.summary.net.sharpe,
                },
            )
        )
    return assess_peak(points)


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    windows: list[dict[str, Any]]
    in_sample_cagr: float | None
    out_of_sample_cagr: float | None
    degradation_pct: float | None
    warning: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "windows": self.windows,
            "in_sample_cagr": self.in_sample_cagr,
            "out_of_sample_cagr": self.out_of_sample_cagr,
            "degradation_pct": self.degradation_pct,
            "warning": self.warning,
        }


def walk_forward(
    conn: duckdb.DuckDBPyConnection,
    base: BacktestConfig,
    values: Sequence[Any],
    apply_value: Callable[[BacktestConfig, Any], BacktestConfig],
    train_sessions: int = p.YEAR * 2,
    test_sessions: int = p.HALF_YEAR,
) -> WalkForwardResult:
    """Pick the best parameter in-sample, then measure it out-of-sample.

    The gap between the two is the honest estimate of how much of the
    in-sample result was fitting rather than signal.
    """
    sessions = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT trade_date FROM metrics_daily "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [base.start, base.end],
        ).fetchall()
    ]
    windows = build_windows(sessions, train_sessions, test_sessions)
    if not windows:
        return WalkForwardResult(
            [], None, None, None,
            f"Not enough history: {len(sessions)} sessions cannot supply a "
            f"{train_sessions}-session training window plus a "
            f"{test_sessions}-session test window.",
        )

    rows: list[dict[str, Any]] = []
    in_sample: list[float] = []
    out_sample: list[float] = []

    for window in windows:
        train_base = _retime(base, window.train_start, window.train_end)
        verdict = sweep(conn, train_base, values, apply_value)
        if verdict.best_value is None:
            continue

        chosen = apply_value(_retime(base, window.test_start, window.test_end), verdict.best_value)
        tested = run_backtest(conn, chosen)

        rows.append({
            **window.as_dict(),
            "chosen_value": verdict.best_value,
            "in_sample_cagr": verdict.best_metric,
            "out_of_sample_cagr": tested.summary.net.cagr_pct,
            "out_of_sample_trades": tested.summary.trades.trades,
            "narrow_peak": verdict.is_narrow_peak,
        })
        in_sample.append(verdict.best_metric)
        out_sample.append(tested.summary.net.cagr_pct)

    if not rows:
        return WalkForwardResult([], None, None, None, "No window produced a result.")

    mean_in = float(np.mean(in_sample))
    mean_out = float(np.mean(out_sample))
    degradation = mean_in - mean_out

    warning = None
    if mean_out <= 0 < mean_in:
        warning = (
            f"The strategy earns {mean_in:.1f}% CAGR on data it was tuned against "
            f"and {mean_out:.1f}% on data it was not. That is the difference "
            "between fitting and forecasting."
        )
    elif mean_in > 0 and degradation > mean_in * 0.5:
        warning = (
            f"Out-of-sample CAGR ({mean_out:.1f}%) is less than half the in-sample "
            f"figure ({mean_in:.1f}%). Expect the live result to resemble the "
            "out-of-sample number, not the backtest headline."
        )

    return WalkForwardResult(rows, mean_in, mean_out, degradation, warning)


def _retime(config: BacktestConfig, start: date, end: date) -> BacktestConfig:
    return dataclasses.replace(config, start=start, end=end)
