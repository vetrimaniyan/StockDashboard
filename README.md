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
| Backfill and incremental ingest | 5-year history; nightly bhavcopy + delivery |
| Corporate actions (FR-3.x) | Splits/bonuses, per-source adjustment, reconciliation gate |
| Validation gate (FR-4.1) | All nine checks, Block/Warn severities |
| Metric engine (§5) | Full metric set, 34 hand-computed unit tests |
| Screener (§6) | Filter compiler, six presets, breadth, market regime |
| API (§2.3) | Dashboard, screens, stock detail, metric definitions, exports |
| Frontend (§7) | Dashboard, virtualised grid, stock detail with charts |
| Exports (§8) | xlsx, csv, html, all with provenance |
| Risk and tax (§9, §11.2) | Stops, cash-only sizing, round-trip cost with TDS |

Not yet built: watchlist, trade journal, notification digest, scheduler
wiring, backtesting (Phase 3).

Data sources deviate from the SRS — Kite Connect is a paid subscription this
deployment does not hold. See [DECISIONS.md](DECISIONS.md), D-1.

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
roughly 45 minutes for the full universe at the configured rate limit:

```bash
.venv/Scripts/python -m alpha500.cli backfill
```

The default is six years, not five. FR-2.2 asks for at least 1 260 trading
sessions and describes that as "approximately 5 calendar years", but NSE trades
around 247 days a year, so five years yields roughly 1 236 sessions and misses
the floor — and with it acceptance criterion 1.

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

Start the UI in a second terminal, then open http://localhost:5173:

```bash
cd frontend && npm run dev
```

## Tests

```bash
.venv/Scripts/python -m pytest backend/tests -q
```

Every formula in SRS section 5 has a test whose expected value was computed by
hand and documented in the test (NFR-5.1). Recording current output instead
would let a metric bug pass through unchanged — risk R-5, rated Critical.

---

## Measured against the NFR-1 budgets

Full NIFTY 500 universe, 562k price rows, five years of history, on the
development machine:

| Requirement | Budget | Measured |
|---|---|---|
| NFR-1.7 metric recomputation, 500 symbols | 60 s | **42.4 s** |
| NFR-1.8 full incremental EOD pipeline | 15 min | **61 s** |
| Cold backfill, 500 symbols | — | ~6 min (rate-limited) |

Corporate-action reconciliation passes across all 500 symbols. Of 500
constituents, 475 are eligible; 15 are excluded for insufficient history and
30 for a gap disqualifier.

## Layout

```
backend/alpha500/
  providers/    AR-1 boundary. The only package that talks to a data vendor.
  db/           DuckDB (analytical) and SQLite (user data) schemas and stores.
  metrics/      kernels -> series -> cross_section -> engine, plus the registry.
  pipeline/     Ingestion, corporate-action adjustment, validation, runner.
  screens/      Filter compiler and preset definitions.
  api/          FastAPI service layer.
frontend/src/   React SPA.
data/           Databases. Rebuildable, gitignored.
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
- **DuckDB allows one writer or many readers.** Do not run the CLI pipeline
  while the API is serving; see DECISIONS.md, D-6.
- **Nothing here is tax advice.** The section 11 calculators use configurable
  placeholder rates that must be confirmed with a cross-border CA and a French
  *conseiller fiscal* before being relied on (open items B-5, B-6).
