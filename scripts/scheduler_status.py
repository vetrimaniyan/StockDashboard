"""Report whether the nightly pipeline actually ran, and how it ended.

Deliberately standalone and read-only: it must work when the API is down,
which is exactly when you need it. Never takes a write lock, so it is safe to
run at any time (DECISIONS.md, D-6).

Exit codes: 0 current, 1 unknown / never run, 2 stale.
"""

from __future__ import annotations

import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

IST = ZoneInfo("Asia/Kolkata")


def _ist(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def _scheduler_armed() -> bool | None:
    """True if some process is running `serve --with-scheduler`.

    The API answering on its port is necessary but not sufficient: plain
    `serve` looks identical from the outside while nothing is scheduled.
    """
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\""
             " | Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:  # noqa: BLE001 - a probe must never be the failure
        return None
    return "--with-scheduler" in out


def main() -> int:
    from alpha500.config import settings

    now = datetime.now(IST)
    print(f"Now: {now:%Y-%m-%d %H:%M:%S IST}")
    print(f"Scheduled slot: {settings.pipeline_hour:02d}:"
          f"{settings.pipeline_minute:02d} IST, Mon-Fri on trading days\n")

    with socket.socket() as sock:
        sock.settimeout(0.5)
        api_up = sock.connect_ex(("127.0.0.1", settings.api_port)) == 0
    print(f"API on port {settings.api_port}: {'UP' if api_up else 'DOWN'}")

    armed = _scheduler_armed()
    if armed is None:
        print("Scheduler armed: unknown (could not inspect processes)")
    elif armed:
        print("Scheduler armed: YES")
    else:
        print("Scheduler armed: NO - no process running with --with-scheduler;")
        print("                 nothing will fire at the slot above.")

    # --- Last run, stage by stage ---------------------------------------
    db = settings.data_dir / "app.sqlite"
    if not db.exists():
        print(f"\nNo job log at {db} - the pipeline has never run.")
        return 1

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    last = conn.execute("SELECT run_id FROM job_runs ORDER BY id DESC LIMIT 1").fetchone()
    if last is None:
        print("\nJob log is empty - the pipeline has never run.")
        return 1

    run_id = last["run_id"]
    # One row per stage: the terminal row wins. A RUNNING row is the opening
    # bookend and only survives here if nothing ever closed it.
    stages = conn.execute(
        """
        SELECT stage, status, ended_at, row_count, message
          FROM job_runs
         WHERE run_id = ?
      GROUP BY stage
        HAVING id = max(id)
      ORDER BY id
        """,
        [run_id],
    ).fetchall()

    print(f"\nLast run {run_id} - {len(stages)} stage(s)")
    worst = "OK"
    for st in stages:
        mark = {"OK": "ok  ", "FAILED": "FAIL", "SKIPPED": "skip",
                "RUNNING": "HUNG"}.get(st["status"], "?   ")
        if st["status"] in {"FAILED", "RUNNING"}:
            worst = st["status"]
        rows = f"{st['row_count']:>6} rows" if st["row_count"] else " " * 11
        print(f"  [{mark}] {st['stage']:<22} {rows}  {_ist(st['ended_at'])}")
        if st["message"]:
            print(f"         -> {st['message']}")

    # --- Freshness, which is what the operator actually cares about ------
    # `serve --with-scheduler` holds DuckDB read-write, and DuckDB refuses
    # even a read-only opener against a live writer. That is precisely when
    # this script matters, so fall back to the API: if the server holds the
    # store, the server is by definition up and can answer for it.
    data_as_of = expected = None
    source = "duckdb"
    try:
        from alpha500.db.connection import analytical
        from alpha500.mktcal import calendar as cal

        with analytical(read_only=True) as duck:
            data_as_of = duck.execute(
                "SELECT max(trade_date) FROM metrics_daily"
            ).fetchone()[0]
            expected = cal.previous_trading_day(duck, now.date() + timedelta(days=1))
    except Exception:  # noqa: BLE001 - a locked store is expected, not exceptional
        source = "api"
        try:
            import json
            import urllib.request

            url = f"http://127.0.0.1:{settings.api_port}/api/status"
            with urllib.request.urlopen(url, timeout=5) as resp:
                status = json.load(resp)
            data_as_of = status.get("data_as_of")
            expected = status.get("latest_session")
        except Exception:  # noqa: BLE001
            source = "unavailable"

    if source == "unavailable":
        print("\nFreshness: UNKNOWN - the store is locked and the API did not")
        print("  answer. Something holds the store but is not serving; look")
        print("  for a stray pipeline or backfill process.")
        return 1

    via = "" if source == "duckdb" else "   (via API; store held by the server)"
    print(f"\nMetrics as of:   {data_as_of}{via}")
    print(f"Latest session:  {expected}")

    if str(data_as_of) == str(expected):
        print("\nVERDICT: current.")
        return 0
    print(f"\nVERDICT: STALE - last completed stage was {worst}.")
    print("  See docs/TROUBLESHOOTING.md")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
