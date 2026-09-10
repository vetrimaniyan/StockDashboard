# Alpha-500

End-of-day momentum and swing-trading screener for the NIFTY 500, built to
`momentum-dashboard-srs.md`.

**Decision support only.** This application places no orders, holds no broker
credentials, and contains no code path capable of placing, modifying or
cancelling one.

---

## What runs today

| Area | State |
|---|---|
| Provider abstraction (AR-1) | NSE archives, Yahoo, CSV fixtures |
| Universe sync (FR-1.x) | 500 NIFTY constituents, membership as an SCD |
| Backfill and incremental ingest | 8-year history; nightly bhavcopy + delivery |
| Corporate actions (FR-3.x) | Splits/bonuses, per-source adjustment, reconciliation gate |
| Validation gate (FR-4.1) | All nine checks, Block/Warn severities |
| Metric engine (§5) | **101 metrics**, expected values computed by hand in the tests |
| Screener (§6) | Filter compiler, **nine screens** plus a universe browser, breadth, market regime |
| Scheduling (FR-5.1) | In-process APScheduler, 18:45 IST, started at logon by a Windows task |
| API (§2.3) | 16 endpoints — dashboard, screens, stock detail, exports, index valuations, sectors |
| Frontend (§7) | Dashboard, virtualised grid, stock detail with charts, sector view |
| Exports (§8) | xlsx, csv, html, all with provenance; refreshed nightly |
| Risk and tax (§9, §11.2) | Stops, cash-only sizing, round-trip cost with TDS |
| Backtesting (Phase 3) | Engine, walk-forward, two exit rules; survivorship-limited — see below |
| Index valuations & sector indices (FR-18) | P/E against own history; 24 tracked indices, range and trend |
| Backups | Both stores snapshotted nightly, verified before they are kept |

**Not yet built:** watchlist, trade journal, notification digest, and
FR-18.5–18.9 (sector breadth, relative strength, breadth thrust, concentration).
FR-19.5–19.7 — the swing-trade dashboard screen — is specified and deliberately
blocked; see [docs/swing-backtest-findings.md](docs/swing-backtest-findings.md).

Data sources deviate from the SRS — Kite Connect is a paid subscription this
deployment does not hold. See [DECISIONS.md](DECISIONS.md), D-1.

**Backtest results are survivorship-biased and say so.** `index_membership`
cannot reconstruct the past universe, so every absolute figure the backtest
produces is inflated by an unknown amount. Only relative comparisons over the
same window are trustworthy, and the engine prints that warning above its
results rather than below them.

---

## Setup

Requires Python 3.11+ and Node 18+.

```bash
py -3.13 -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

```bash
cd frontend && npm install
```

## First run

Create the databases and seed the trading calendar:

```bash
.venv/Scripts/python -m alpha500.cli init
```

Sync the NIFTY 500 constituent list:

```bash
.venv/Scripts/python -m alpha500.cli universe
```

Load price history. This is deliberately never automatic (FR-2.5) and takes
roughly 9 minutes for the full universe at the configured rate limit:

```bash
.venv/Scripts/python -m alpha500.cli backfill --years 8
```

**Pass `--years 8`.** The flag still defaults to 5, which is what the original
operator decision chose (D-7), but eight is what this deployment actually runs
on and what the current store holds. Five years starts the usable window at an
unrepresentative point: eligibility needs 252 sessions, so the first session
carrying any eligible stock lands a year in, and the only bear phase in range
falls outside it. Re-running the same screen over eight years moved its net
CAGR from 2.43% to 14.46% — the five-year conclusion was not conservative, it
was wrong. See DECISIONS.md, D-9.

Note that FR-2.2's 1 260-session floor is unachievable at any depth, because a
current-constituent universe always contains recent IPOs. That is a property of
the universe, not a shortfall in the backfill; D-9 names the affected symbols.

Verify the corporate-action reconciliation gate passes (a release gate,
NFR-5.4):

```bash
.venv/Scripts/python -m alpha500.cli reconcile
```

Compute metrics:

```bash
.venv/Scripts/python -m alpha500.cli rebuild
```

## Daily use

Run the incremental EOD pipeline:

```bash
.venv/Scripts/python -m alpha500.cli pipeline
```

Start the API (binds to 127.0.0.1 only, per NFR-4.1):

```bash
.venv/Scripts/python -m alpha500.cli serve
```

Or serve *and* run the nightly pipeline unattended in the same process, which
is what §2.1 means by in-process APScheduler and what makes the DuckDB
single-writer constraint tractable (DECISIONS.md, D-6):

```bash
.venv/Scripts/python -m alpha500.cli serve --with-scheduler
```

The default slot is 18:45 IST — NSE finalises the bhavcopy after post-close
processing, and running earlier risks ingesting provisional data (FR-5.1).
Override with `--at HH:MM`, always in IST regardless of the host's timezone.
The next fire time is printed at startup, so an armed schedule is verifiable
rather than assumed.

In normal operation you should not start it by hand at all. A Windows
Scheduled Task named **Alpha500 API** runs it at logon, and that is the
supported way to bring it back up:

```bash
powershell -Command "Start-ScheduledTask -TaskName 'Alpha500 API'"
```

A server started from a terminal that later closes dies with it — silently,
possibly hours later, leaving nothing to run that night. Confirm either way:

```bash
.venv/Scripts/python scripts/scheduler_status.py
```

That prints whether the API is up and whether the scheduler is armed as two
separate facts, because a process answering on the port proves only the first.

Note for a host outside India: `TZ=Asia/Kolkata date` under Git Bash on Windows
does not apply the timezone and silently reports UTC. Use Python's `zoneinfo`
to check IST — that is what the scheduler itself uses.

Start the UI in a second terminal, then open http://localhost:5173:

```bash
cd frontend && npm run dev
```

## Tests

```bash
.venv/Scripts/python -m pytest backend/tests -q
```

334 tests. Every formula in SRS section 5 has one whose expected value was
computed by hand and documented in the test (NFR-5.1). Recording current output
instead would let a metric bug pass through unchanged — risk R-5, rated
Critical.

---

## Measured against the NFR-1 budgets

Full NIFTY 500 universe, 842k price rows, eight years of history (1 985
sessions from 2018-08-17), on the development machine:

| Requirement | Budget | Measured | On |
|---|---|---|---|
| NFR-1.7 metric recomputation, 500 symbols | 60 s | **~24 s** | 2026-08-31 |
| NFR-1.8 full incremental EOD pipeline | 15 min | 7 min 16 s | 2026-08-29 |
| Cold backfill, 500 symbols, 8 years | — | 8 min 39 s (rate-limited) | 2026-08-27 |

NFR-1.7 breached at ~116 s once the store reached eight years, and was fixed by
vectorising the two support kernels rather than by trimming what is loaded —
`swing_lows` and `nearest_support` were Python loops over every bar, and
`np.delete` alone was being called once per price row. Output is bit-identical
across all 500 symbols; see DECISIONS.md, D-10. Roughly 60% of what remains is
Wilder smoothing, which is a sequential recurrence and would need a new
dependency to vectorise — not worth it at 40% of budget.

The NFR-1.8 figure is a six-session catch-up run, not a single session; a
normal one-session run has not been re-timed since the deeper backfill, so
treat it as an upper bound.

Corporate-action reconciliation passes across all 500 symbols. On the
2026-08-28 session, 476 of 500 constituents are eligible; the 24 excluded are
held out for insufficient history, thin liquidity or a restricted series.

## Layout

```
backend/alpha500/
  providers/    AR-1 boundary. The only package that talks to a data vendor.
  db/           DuckDB (analytical) and SQLite (user data) schemas, stores, backups.
  metrics/      kernels -> series -> cross_section -> engine, plus the registry.
  pipeline/     Ingestion, corporate-action adjustment, validation, runner.
  screens/      Filter compiler and preset definitions.
  backtest/     Point-in-time simulation, statistics, walk-forward.
  mktcal/       Trading calendar.
  tools/        Generators for METRICS.md and the operator manual.
  api/          FastAPI service layer.
frontend/src/   React SPA.
scripts/        Start the API at logon; check the scheduler; ad-hoc backtests.
docs/           Requirements, operator manual, runbook, backtest findings.
data/           Databases and backups. Gitignored.
```

Two databases, deliberately separate: a full price rebuild must never put
watchlists or the journal at risk.

## Notes on operation

- **Staleness is loud.** Every data-bearing response carries a `DataStatus`
  with a reason, and the UI renders a stale state in a warning treatment.
  Silently serving yesterday's data as today's is the most dangerous failure
  mode in this class of tool (FR-8.9).
- **Exits outrank entries.** The Momentum Breakdown screen renders above the
  entry candidates on the dashboard. This is required (FR-7.6), not stylistic —
  momentum tools bias heavily toward finding entries.
- **The exit screen is not a short list.** NRI accounts cannot short (FR-12.2).
- **DuckDB allows one writer or many readers.** Do not run the CLI pipeline,
  a backfill, `materialise`, or a backtest while the API is serving; stop it
  first. See DECISIONS.md, D-6.
- **A capped screen says so.** Where a screen returns fewer rows than it
  matched, the grid reads "top 100 of 277 matches". Without that line, the list
  in front of you is the whole answer rather than a slice of one.
- **Served metrics are stamped with the engine build that produced them.**
  Editing the metric engine without recomputing leaves numbers no version of
  the code would now produce, which nothing else notices. `/api/status` reports
  it and `alpha500 rebuild` clears it.
- **Nothing here is tax advice.** The section 11 calculators use configurable
  placeholder rates that must be confirmed with a cross-border CA and a French
  *conseiller fiscal* before being relied on (open items B-5, B-6).

---

## Documentation

| Document | For |
|---|---|
| [docs/OPERATOR-MANUAL.html](docs/OPERATOR-MANUAL.html) | Using the dashboard. Generated from the registry and presets, so it cannot drift from the code. |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | When something is down or stale. Layered, and ends with a recovery checklist. |
| [docs/URD.md](docs/URD.md) | Requirement ledger, what exists today, change log. |
| [METRICS.md](METRICS.md) | Every formula, generated from the registry. |
| [DECISIONS.md](DECISIONS.md) | Why the build deviates where it does, and what is still open. |
| [docs/backtest-findings.md](docs/backtest-findings.md) | Momentum Leaders vs Pullback + Reversal. |
| [docs/swing-backtest-findings.md](docs/swing-backtest-findings.md) | The FR-19 swing exit rule, and why its gate failed. |
