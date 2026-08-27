"""Backtesting engine (SRS Phase 3).

The phase that determines whether the preceding two were worth building.
"""

from alpha500.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from alpha500.backtest.stats import Performance, summarise

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "Performance",
    "run_backtest",
    "summarise",
]
