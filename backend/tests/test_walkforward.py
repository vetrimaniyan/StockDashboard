"""Walk-forward and overfitting detection.

A parameter sweep always produces a winner. These tests are about telling the
difference between a winner worth trusting and one that is an artefact of the
history it was fitted to.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from alpha500.backtest.walkforward import (
    SweepPoint,
    assess_peak,
    build_windows,
)


def _points(values: list[float]) -> list[SweepPoint]:
    return [SweepPoint(value=i, metric=v) for i, v in enumerate(values)]


def test_isolated_spike_is_flagged():
    """The signature of a parameter fitted to one particular history."""
    verdict = assess_peak(_points([2.0, 2.0, 2.0, 20.0, 2.0, 2.0, 2.0]))
    assert verdict.is_narrow_peak
    assert verdict.plateau_width == 1
    assert verdict.warning and "OVERFITTING RISK" in verdict.warning


def test_broad_plateau_is_not_flagged():
    """Neighbours that also work suggest a real effect, not a fitted one."""
    verdict = assess_peak(_points([2.0, 9.0, 9.5, 10.0, 9.6, 9.1, 2.0]))
    assert not verdict.is_narrow_peak
    assert verdict.plateau_width >= 3
    assert verdict.warning is None


def test_a_peak_at_the_edge_still_counts_its_one_side():
    verdict = assess_peak(_points([10.0, 9.5, 9.0, 1.0]))
    assert verdict.best_value == 0
    assert verdict.plateau_width == 3
    assert not verdict.is_narrow_peak


def test_all_negative_results_are_not_worth_optimising():
    verdict = assess_peak(_points([-5.0, -3.0, -8.0]))
    assert not verdict.is_narrow_peak
    assert verdict.warning and "non-positive" in verdict.warning


def test_plateau_threshold_is_relative_to_the_best():
    """A neighbour just under the tolerance drops out of the plateau.

    Real sweeps land near this boundary — an observed run had the best value at
    18.40% with both neighbours at ~13.6%, against a 13.80% threshold. The
    classification is deliberately strict: a 35% jump at a single setting is
    the thing worth warning about.
    """
    verdict = assess_peak(_points([13.59, 18.40, 13.60]), tolerance=0.25)
    assert verdict.is_narrow_peak
    assert verdict.plateau_width == 1

    # Widen the tolerance and the same shape reads as a plateau.
    relaxed = assess_peak(_points([13.59, 18.40, 13.60]), tolerance=0.35)
    assert not relaxed.is_narrow_peak


def test_empty_sweep_does_not_crash():
    verdict = assess_peak([])
    assert verdict.best_value is None
    assert verdict.warning


def _sessions(n: int) -> list[date]:
    out: list[date] = []
    day = date(2021, 1, 4)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def test_windows_never_overlap_their_own_train_and_test():
    """Testing on data the parameter was chosen from measures nothing."""
    sessions = _sessions(600)
    windows = build_windows(sessions, train_sessions=252, test_sessions=126)
    assert windows
    for window in windows:
        assert window.train_end < window.test_start


def test_windows_roll_forward():
    sessions = _sessions(1000)
    windows = build_windows(sessions, train_sessions=252, test_sessions=126)
    assert len(windows) > 1
    for earlier, later in zip(windows, windows[1:]):
        assert later.train_start > earlier.train_start
        assert later.test_start > earlier.test_start


def test_insufficient_history_yields_no_windows():
    sessions = _sessions(100)
    assert build_windows(sessions, train_sessions=252, test_sessions=126) == []
