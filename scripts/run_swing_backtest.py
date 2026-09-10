"""FR-19.4 — the four runs Phase 2 is gated on.

Runs the tiered trailing-stop exit rule over both candidate entry screens at
two position counts, and collects everything §3's acceptance criteria ask a
human to read: returns, trade counts with and without the cooldown, the
survivorship warning, the walk-forward verdict on the swept parameter, and
the index over the same window to compare against.

The window is fixed at 2019-08-30 to 2026-08-27 because FR-19.4 names it —
it is the window ``backtest-findings.md`` already reports, and the whole
point is to be comparable with it. Every other date in this project is
resolved at run time; this one is a stated requirement, not a default.

Writes ``docs/swing-backtest-findings.md``. Stop the API before running: the
analytical store takes one writer or many readers, never both.

    .venv/Scripts/python scripts/run_swing_backtest.py
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import duckdb  # noqa: E402

from alpha500.backtest.engine import (  # noqa: E402
    BacktestConfig,
    run_backtest,
    survivorship_warnings,
)
from alpha500.backtest.walkforward import walk_forward  # noqa: E402
from alpha500.screens.presets import get_preset  # noqa: E402

DB_PATH = REPO_ROOT / "data" / "alpha500.duckdb"
OUT_DIR = REPO_ROOT / "exports"
FINDINGS = REPO_ROOT / "docs" / "swing-backtest-findings.md"

START = date(2019, 8, 30)
END = date(2026, 8, 27)

SCREENS = ("Pullback + Reversal", "Fibonacci Reversal Zone")
POSITION_COUNTS = (2, 3)
GIVEBACK_SWEEP = [0.02, 0.03, 0.04, 0.05, 0.06]


def make_config(screen_name: str, max_positions: int, *, cooldown: int | None) -> BacktestConfig:
    return BacktestConfig(
        screen=get_preset(screen_name),
        start=START,
        end=END,
        max_positions=max_positions,
        max_holding_days=21,
        exit_rule="tiered_trailing",
        initial_stop_atr_multiple=0.5,
        stage1_arm_pct=0.05,
        stage1_giveback_pct=0.04,
        stage2_arm_pct=0.10,
        stage2_giveback_pct=0.02,
        time_stop_only_if_not_profitable=True,
        reentry_cooldown_sessions=cooldown,
        exit_screen=None,  # Decision 3: the tiered stop is the only exit.
    )


def benchmark(conn: duckdb.DuckDBPyConnection) -> dict[str, float] | None:
    """NIFTY 500 buy-and-hold over the same window, for comparison."""
    row = conn.execute(
        """
        SELECT first(close ORDER BY trade_date), last(close ORDER BY trade_date),
               count(*)
          FROM index_ohlcv_daily
         WHERE index_name = 'NIFTY500' AND trade_date BETWEEN ? AND ?
        """,
        [START, END],
    ).fetchone()
    if not row or row[0] is None or row[2] < 2:
        return None
    opening, closing, sessions = float(row[0]), float(row[1]), int(row[2])
    total = (closing / opening - 1.0) * 100.0
    years = sessions / 252.0
    cagr = ((closing / opening) ** (1.0 / years) - 1.0) * 100.0
    return {"total_return_pct": total, "cagr_pct": cagr, "sessions": sessions}


def collect(conn: duckdb.DuckDBPyConnection) -> dict:
    out: dict = {
        "window": {"start": START.isoformat(), "end": END.isoformat()},
        "benchmark": benchmark(conn),
        "survivorship": survivorship_warnings(conn),
        "runs": [],
    }

    for screen_name in SCREENS:
        for max_pos in POSITION_COUNTS:
            label = f"{screen_name} @ max_positions={max_pos}"
            print(f"--- {label}", flush=True)

            cooled = make_config(screen_name, max_pos, cooldown=21)
            result = run_backtest(conn, cooled)
            s = result.summary

            print("    uncooled comparison", flush=True)
            uncooled = run_backtest(
                conn, make_config(screen_name, max_pos, cooldown=None)
            )

            print("    walk-forward over stage1_giveback_pct", flush=True)
            wf = walk_forward(
                conn, cooled, GIVEBACK_SWEEP,
                lambda cfg, value: dataclasses.replace(cfg, stage1_giveback_pct=value),
            )

            record = {
                "screen": screen_name,
                "max_positions": max_pos,
                "net": {
                    "cagr_pct": s.net.cagr_pct,
                    "total_return_pct": s.net.total_return_pct,
                    "max_drawdown_pct": s.net.max_drawdown_pct,
                    "sharpe": s.net.sharpe,
                },
                "gross": {
                    "cagr_pct": s.gross.cagr_pct,
                    "total_return_pct": s.gross.total_return_pct,
                },
                "trades": {
                    "count": s.trades.trades,
                    "count_without_cooldown": uncooled.summary.trades.trades,
                    "hit_rate_pct": s.trades.hit_rate_pct,
                    "avg_win_pct": s.trades.avg_win_pct,
                    "avg_loss_pct": s.trades.avg_loss_pct,
                    "avg_holding_days": s.trades.avg_holding_days,
                    "exposure_pct": s.trades.exposure_pct,
                },
                "walk_forward": {
                    "in_sample_cagr": wf.in_sample_cagr,
                    "out_of_sample_cagr": wf.out_of_sample_cagr,
                    "warning": wf.warning,
                    "windows": len(wf.windows),
                    "chosen": [w.get("chosen_value") for w in wf.windows],
                },
            }
            out["runs"].append(record)

            path = OUT_DIR / (
                f"swing_backtest_{screen_name.split()[0].lower()}_{max_pos}.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result.as_dict(), indent=2, default=str))
            print(f"    trade log: {path}", flush=True)

    return out


def main() -> int:
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        data = collect(conn)
    finally:
        conn.close()

    raw = OUT_DIR / "swing_backtest_summary.json"
    raw.write_text(json.dumps(data, indent=2, default=str))
    print(f"\nSummary: {raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
