# Troubleshooting: "the dashboard doesn't work"

The dashboard has three independent moving parts. Almost every incident is
one of them, and they fail in visibly different ways. Identify which before
changing anything.

| What you see | Layer at fault |
|---|---|
| Browser can't connect / `ERR_CONNECTION_REFUSED` on :5173 | Vite dev server down |
| Page renders, panels empty or spinning, console shows failed `/api/*` calls | API down |
| Page renders with data and an amber **"Data is stale"** banner | API fine, pipeline failed |

The third case is not a malfunction. It is FR-8.9 working: the app is
refusing to pass yesterday's numbers off as today's. The data on screen is
real, just old.

---

## First command, always

```bash
.venv/Scripts/python scripts/scheduler_status.py
```

Read-only and safe to run at any time, including while the API is serving.
It works when the API is down, which is when you need it most. Exit code is
`0` current, `1` unknown / never run, `2` stale.

It answers, in order: is the API up, is a scheduler actually armed, what did
the last run do stage by stage, and how old is the data.

Two details worth knowing, because both mislead:

- **"API up" and "scheduler armed" are separate lines and separate facts.**
  Plain `serve` answers on the port while nothing is scheduled to fire. The
  script inspects process command lines for `--with-scheduler` rather than
  inferring it from the port.
- **Freshness may be reported "via API".** `serve --with-scheduler` holds
  DuckDB read-write, and DuckDB refuses even a read-only opener against a
  live writer. The script falls back to `/api/status`, since a store locked
  by the server implies the server is up. If you instead see
  `Freshness: UNKNOWN`, something holds the store but is *not* serving —
  look for a stray `pipeline` or `backfill` process.

---

## Layer 1 — Vite dev server

```bash
netstat -ano | findstr :5173
```

Nothing listening? Start it:

```bash
cd frontend && npm run dev
```

## Layer 2 — the API

```bash
curl -s http://127.0.0.1:8000/api/status
```

Vite proxies `/api` to `127.0.0.1:8000` (`frontend/vite.config.ts`). The API
binds loopback only, by NFR-4.1 — that is deliberate, not a bug to route
around.

If it does not answer, nothing is serving. Start it:

```bash
.venv/Scripts/python -m alpha500.cli serve --with-scheduler
```

**Prefer `--with-scheduler` as the normal way to run.** Plain `serve` answers
on the port and looks healthy while nothing is scheduled to fire — the status
script reports these two facts separately for exactly this reason.

Note that `serve` prints its "Scheduler started / Next run" banner on stdout,
which is block-buffered when redirected to a file. Its absence from a log is
not evidence the scheduler failed to arm; confirm with the status script
instead of reading the log.

### The API starts, then exits immediately

Almost always the DuckDB single-writer rule (DECISIONS.md, D-6). A CLI
pipeline, a backfill, or a second `serve --with-scheduler` already holds the
store read-write. Find and stop the other writer:

```bash
Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Select-Object ProcessId, CommandLine
```

Never run the CLI pipeline while the API serves with the scheduler attached.

## Layer 3 — the nightly pipeline

The scheduler is **in-process with the API** (SRS §2.1). It is not a Windows
service and not a cron job. If the API process is not running at 18:45 IST,
the run does not happen and nothing anywhere records that it didn't. A host
that was asleep runs late instead, once, within a 6-hour misfire grace.

Read the last run:

```bash
.venv/Scripts/python scripts/scheduler_status.py
```

Full stage history when you need more than the last run:

```bash
.venv/Scripts/python -c "import sqlite3;c=sqlite3.connect('data/app.sqlite');c.row_factory=sqlite3.Row;[print(dict(r)) for r in c.execute('SELECT run_id,stage,status,ended_at,message FROM job_runs ORDER BY id DESC LIMIT 30')]"
```

Stage statuses are `RUNNING` / `OK` / `FAILED` / `SKIPPED`. A stage stuck at
`RUNNING` with no terminal row means the process died mid-stage — look for a
crash or a machine that slept, not for a logic error.

### The API starts itself at logon

A Windows Scheduled Task named **Alpha500 API** runs `scripts/start_api.ps1`
when you log in, which starts `serve --with-scheduler` if it is not already up.

The task starts the *server*, not the pipeline, and that is the point. The EOD
run is scheduled inside the API process (SRS 2.1, D-6), so what has to survive
a reboot is the server. A task running `alpha500 pipeline` directly would
instead collide with the serving API over DuckDB's single-writer lock, and
duplicate the run when the in-process scheduler fired anyway.

```bash
powershell -ExecutionPolicy Bypass -File scripts/register_api_task.ps1
```

Manage it:

```bash
powershell -Command "Get-ScheduledTaskInfo -TaskName 'Alpha500 API'"
```

`LastTaskResult` of `0` is success; `267009` means it is still running, which
is normal for up to 20 seconds while the launcher waits for the port.

Remove it with `register_api_task.ps1 -Remove`.

The launcher declines to start a second instance if the port is already
listening, or if a CLI writer (`pipeline`, `backfill`, `rebuild`,
`materialise`, `indices`, `marketcap`) holds the store. A double-start is not
a harmless duplicate: the second process would try to open the store
read-write while the first holds it. It logs to `data/start_api.log`,
deliberately separate from `data/api.log`, which the running server keeps an
exclusive handle on.

**What this fixes and what it does not.** The pipeline now survives a reboot
and a closed terminal. It does not survive the machine being off at 18:45 IST
- but the scheduler's six-hour misfire grace means a PC that wakes by roughly
00:45 IST still runs that session, once.

---

### Re-running after a failure

Stop the API first (single writer), then:

```bash
.venv/Scripts/python -m alpha500.cli pipeline
```

Target a specific missed session:

```bash
.venv/Scripts/python -m alpha500.cli pipeline --date 2026-08-28
```

If prices landed but metrics look wrong, recompute without re-ingesting:

```bash
.venv/Scripts/python -m alpha500.cli rebuild
```

Then restart the API.

---

## Known failure modes

### `_inst_stage has N columns but 15 values were supplied` — fixed

Seen on the 2026-08-28 run. `sync_instruments` failed, the run aborted, and
data froze at the previous session.

`upsert_instruments` in `backend/alpha500/db/store.py` built its staging
table with `SELECT * FROM instruments LIMIT 0`, so the stage always had as
many columns as `instruments` — but the `INSERT ... VALUES` beneath it was
positional with a hardcoded 15 placeholders. `float_shares`,
`float_shares_as_of` and `index_tier` took the table to 18 and broke it.

Now fixed: both the stage load and the tail `INSERT INTO instruments` name
their columns from `_INSTRUMENT_STAGE_COLUMNS`, so the statement no longer
depends on the table's width.

**If you add a column to `instruments`, decide who owns it.** Columns the
universe sync populates belong in `_INSTRUMENT_STAGE_COLUMNS`. Columns owned
by another command — as `float_shares` is owned by `marketcap` and
`index_tier` by `indices` — must stay out of it, or a nightly sync will
overwrite them with nulls. This path has no test coverage, which is why the
original regression shipped.

### `FATAL Error: Failed to delete all rows from index`

Seen 2026-09-07 on `compute_metrics`:

```
_duckdb.FatalException: FATAL Error: Invalid Input Error:
Failed to delete all rows from index. Only deleted 47 out of 500 rows.
```

`_write_metrics` clears the day before rewriting it, and that `DELETE` failed
against `idx_metrics_date_rank`, the secondary index on
`metrics_daily (trade_date, momentum_rank)`. The table itself was sound — 500
rows for the date, 500 distinct tokens, no duplicate `(token, date)` pairs —
so the inconsistency was in the index, not the data.

**It stops the nightly run.** `compute_metrics` performs exactly this delete,
so once it appears every subsequent pipeline run fails at that stage until the
index is rebuilt. The error is FATAL in DuckDB's sense: it invalidates the
connection, so the process must be restarted afterwards.

The index is derived and rebuildable, so the repair is local. With the API
stopped, so nothing else holds the store:

```python
import duckdb
c = duckdb.connect(r"C:\StockDashboard\data\alpha500.duckdb")
c.execute("DROP INDEX IF EXISTS idx_metrics_date_rank")
c.execute(
    "CREATE INDEX idx_metrics_date_rank "
    "ON metrics_daily (trade_date, momentum_rank)"
)
c.execute("CHECKPOINT")
c.close()
```

Then re-run the metrics for the affected date. Nothing is lost: the failed
transaction rolls back, and the row counts are unchanged by the repair.

Take a copy of the `.duckdb` file before the repair. It is a single file and
the copy is the whole backup — `backup_app_db` covers `app.sqlite` only, so
the analytical store has no nightly snapshot behind it.

### Stale banner on a non-trading day

Not a fault. `is_trading_day` gates the run; weekends and NSE holidays are
skipped by design and the data legitimately stays at the last session.

### `engine_stale` true in `/api/status`

Served metrics were computed by a code version no longer in the tree. Not a
crash — the numbers are stale in a way a date cannot show. Fix:

```bash
.venv/Scripts/python -m alpha500.cli rebuild
```

### Checking IST on a Windows host

`TZ=Asia/Kolkata date` under Git Bash silently reports UTC. It will make a
correctly-scheduled job look wrong. Use the same source the scheduler uses:

```bash
.venv/Scripts/python -c "from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo('Asia/Kolkata')))"
```

---

## Sharing the dashboard with someone else

### Exports, refreshed nightly

The pipeline's `export_screens` stage rewrites `exports/latest/` on every run —
one self-contained HTML file per screen that had rows, under a stable name:

```
exports/latest/momentum_leaders.html
exports/latest/momentum_breakdown.html
...
```

Send them as-is. They load nothing remotely, so they render on a machine that
has never seen this project, and each carries a provenance block naming the
screen, its filters, the data-as-of date and the row count.

**An absent file means that screen found nothing.** The directory is cleared
at the start of each run, deliberately: a screen that had rows yesterday and
none today must not leave yesterday's file sitting there reading as current.
Say so when sharing, or a missing screen looks like a fault rather than a
setup being absent.

The timestamped exports from the UI's Export buttons land in `exports/` and
are never touched by this stage.

### Live access

The API has authentication (NFR-4.5), off by default. With no token configured
it is loopback-only and behaves exactly as it always did.

Mint a token per reviewer so any one of them can be withdrawn alone:

```bash
.venv/Scripts/python -m alpha500.cli token
```

Put them in `.env` as `ALPHA500_API_TOKENS=alice:<token>,bob:<token>`, restart,
and every `/api/*` route needs a credential. Reviewers paste the token into
the sign-in screen once; it is exchanged for an httpOnly cookie so no script
on the page can read it back.

**Binding beyond loopback without a token refuses to start.** That is
deliberate — the previous behaviour was a printed warning, and a warning is
advice rather than a control.

```bash
.venv/Scripts/python -m alpha500.cli serve --with-scheduler --host 0.0.0.0
```

Two things authentication does not solve. It does not make the data
redistributable — market data is licensed for personal use, so check the terms
before granting access. And it does not encrypt anything: over a LAN or the
open internet the token and the responses travel in clear text unless you put
https in front of it. For a handful of named reviewers, a private network
(Tailscale or similar) is a better answer than opening a port.

To withdraw one reviewer, delete their entry and restart. To withdraw
everyone, remove the variables entirely — which also returns the API to
loopback-only.

---

## Restoring the user store

`data/alpha500.duckdb` is rebuildable from a backfill. `data/app.sqlite` is
not — the watchlist, journal, saved screens and weight profiles exist nowhere
else, which is why the two databases are separate in the first place.

The pipeline snapshots it as its last stage, and you can take one any time:

```bash
.venv/Scripts/python -m alpha500.cli backup
```

Snapshots land in `data/backups/` as `app-YYYYmmdd-HHMMSS-NN.sqlite`, newest
last. An unchanged store produces no new file, so a quiet week leaves one
snapshot rather than seven identical ones. Thirty are retained.

To restore, stop the API first — it holds the file open — then swap:

```bash
cp data/app.sqlite data/app.sqlite.before-restore
```

```bash
cp data/backups/app-YYYYmmdd-HHMMSS-NN.sqlite data/app.sqlite
```

Check what you are restoring *before* overwriting, since job history is the
quickest way to tell one snapshot from another:

```bash
.venv/Scripts/python -c "import sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(c.execute('PRAGMA integrity_check').fetchone()[0]); print(c.execute('SELECT max(ended_at) FROM job_runs').fetchone()[0])" data/backups/app-YYYYmmdd-HHMMSS-NN.sqlite
```

**These snapshots sit on the same disk as the original.** That covers
corruption and accidental deletion, not drive failure. For off-machine, point
the destination at a synced folder — no code change needed:

```bash
ALPHA500_BACKUP_DIR=C:/Users/gokul/OneDrive/alpha500-backups
```

They are gitignored on purpose: the store holds your own trading data, and the
GitHub remote is for code.

---

## Recovery, in order

1. `scripts/scheduler_status.py` — decide which layer is at fault.
2. API down → start `serve --with-scheduler`. Dashboard returns immediately,
   serving the last good session with a stale banner. **This restores the UI
   without touching data.**
3. Data stale → stop the API, run `pipeline`, restart.
4. Pipeline fails again → read the `message` on the `FAILED` stage. That
   column carries the actual exception; it is the fastest route to a cause.
