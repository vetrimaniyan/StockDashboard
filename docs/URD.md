# User Requirement Document — Alpha-500

**Status as built: 2026-08-31.** This document records what the system does
today and is the place to add what you want it to do next.

It is a companion to, not a replacement for, the parent SRS *"NSE Momentum &
Swing-Trading Dashboard (Project Alpha-500)" v1.0*, which defines FR-1 to
FR-12 and is not held in this repository. Requirements added since that
document are specified here in full.

**Decision support only.** The system places no orders, holds no broker
credentials, and contains no code path capable of placing, modifying or
cancelling one. Any requirement that would change this is out of scope by
construction, not by preference.

---

## 1. How to add a requirement

This is the part that matters for day-to-day use. Adding a requirement is
four steps.

1. **Take the next free ID** from the table in §2. Never renumber an existing
   requirement — code comments, tests and commit messages cite these IDs, and
   a renumber silently breaks every one of those references.
2. **Append it to §6**, using the template below.
3. **Add a row to the change log** in §9.
4. **Leave the status as `Proposed`.** Move it to `Built` only when the
   acceptance criterion actually passes, and say which test proves it.

### Template

```markdown
**FR-nn.n — Short imperative title.** The system MUST <the observable
behaviour, in one sentence>.

<Any constraint, boundary or explicit non-goal. State what it MUST NOT do
where that is the part likely to be got wrong.>

*Acceptance:* <a check someone else could run and get the same answer —
a number, a row count, a named test, a specific symbol on a specific date.>

*Status:* Proposed | Built (`test_name`) | Deferred (reason)
```

### What makes a usable requirement here

- **Write the acceptance criterion first.** If you cannot state how you would
  know it works, the requirement is not ready to build. Every FR below has
  one, and each is either a number or a named test.
- **Prefer MUST NOT where the risk is overreach.** "The exit screen MUST NOT
  read as a short-candidate list" (FR-12.2) has prevented more harm than any
  positive requirement in this document.
- **Say what the number means, not just how to compute it.** A formula
  without an interpretation gets misread under time pressure.
- **Name the honest limit.** Where the data cannot support the obvious
  reading, the requirement says so — see FR-15.2, which is why the period
  high is not called an all-time high.

---

## 2. Requirement ID allocation

| Range | Area | Defined in | State |
|---|---|---|---|
| FR-1.x | Universe and eligibility | Parent SRS | In use |
| FR-2.x | Ingestion and providers | Parent SRS | In use |
| FR-3.x | Corporate actions | Parent SRS | In use |
| FR-4.x | Validation gate | Parent SRS | In use |
| FR-5.x | Scheduling | Parent SRS | In use |
| FR-6.x | Metric engine | Parent SRS | In use |
| FR-7.x | Screener | Parent SRS | In use |
| FR-8.x | UI | Parent SRS | In use |
| FR-9.x | Exports | Parent SRS | In use |
| FR-10.x | Risk and sizing | Parent SRS | In use |
| FR-11.x | Alerts and run logging | Parent SRS | In use |
| FR-12.x | Account constraints (NRI) | Parent SRS | In use |
| FR-13.x | Additional return metrics | `SRS-addendum-screener.md` | In use |
| FR-14.x | Pullback and reversal | `SRS-addendum-screener.md` | In use |
| FR-15.x | Size tier and period high | This document, §6 | In use |
| FR-16.x | Operability | This document, §6 | In use |
| **FR-17.x** | — | — | **Next free** |

Supporting series: `NFR-1` to `NFR-6` (non-functional), `AR-1` to `AR-4`
(architecture), `D-1` to `D-10` (decisions, in `DECISIONS.md`), `B-1` to `B-9`
(open questions, in `DECISIONS.md`), `R-x` (risks; R-1, R-3, R-5 cited in code).

Next free: **NFR-7**, **D-11**, **B-10**.

---

## 3. What exists today

Verified against the running system on 2026-08-31.

| Capability | State | Evidence |
|---|---|---|
| Provider abstraction (AR-1) | Built | NSE archives, Yahoo, CSV fixtures |
| Universe sync (FR-1.x) | Built | 500 constituents; membership as an SCD |
| Backfill and incremental ingest (FR-2.x) | Built | 841,519 rows, 1,985 sessions |
| Corporate actions (FR-3.x) | Built | Reconciliation gate passes on all 500 |
| Validation gate (FR-4.1) | Built | Nine checks, Block/Warn severities |
| Scheduling (FR-5.1) | Built | In-process APScheduler, 18:45 IST |
| Metric engine (FR-6.x) | Built | **74 metrics**, hand-computed unit tests |
| Screener (FR-7.x) | Built | Filter compiler, **8 screens** + universe browser |
| API (§2.3) | Built | 11 endpoints, loopback only |
| Frontend (FR-8.x) | Built | Dashboard, virtualised grid, stock detail |
| Exports (FR-9.x) | Built | xlsx, csv, html, each with provenance |
| Risk and tax (FR-10, FR-12) | Built | Stops, cash-only sizing, TDS round-trip |
| Backtesting (Phase 3) | Partial | Engine and walk-forward exist; see §7 |
| Operability (FR-16.x) | Built | Status command, troubleshooting runbook |

**Not built:** watchlist, trade journal, notification digest.

### Universe as of the 2026-08-28 session

500 constituents — 476 eligible for screens, 24 excluded for thin liquidity,
short history or a restricted series. Size tiers: 50 Nifty 50, 50 Next 50,
150 Midcap 150, 250 Smallcap 250.

### The eight screens

| Screen | Finds | Rows cap |
|---|---|---|
| Momentum Leaders | Strongest volatility-adjusted trends | 20 |
| Trend Template | All eight structural criteria met | 100 |
| 52-Week High Breakout | Cleared the 52w high on volume today | 50 |
| Volatility Contraction | Tight base after an advance | 50 |
| Pullback to Support | Uptrend resting on the 21 EMA or 50 SMA | 50 |
| Pullback + Reversal | At support with reversal confirmation | 10 |
| Approaching High | Within 3% of the period high, not yet through | 50 |
| **Momentum Breakdown** | **EXIT signal for held names** | 100 |

Plus **All NIFTY 500**, a universe browser rather than a screen: it is the
only view that does not hide ineligible rows, and exists so "why is this
stock never in my results" is answerable (FR-1.5).

### Command surface

`init`, `universe`, `backfill`, `pipeline`, `rebuild`, `reconcile`,
`materialise`, `backtest`, `marketcap`, `indices`, `serve`, plus
`scripts/scheduler_status.py` (FR-16.1).

---

## 4. Users and operating context

Single operator, single machine, no multi-user requirement. The deployment
model follows from DuckDB allowing one writer or many readers (D-6): the
scheduler runs **in-process with the API**, so `serve --with-scheduler` is
the normal way to run, and the CLI pipeline must not run concurrently with it.

The operator holds an **NRI account**, which is why FR-12 exists: no
shorting, cash-only position sizing, and a round-trip cost model that
includes TDS. Requirements that assume intraday leverage or short exposure do
not apply and should be rejected rather than adapted.

Market data is licensed for personal use and not for redistribution, which is
why the API binds to loopback (NFR-4.1). A requirement to expose it beyond
localhost needs a licensing answer before a technical one.

---

## 5. Data foundation and its limits

Worth stating plainly, because two requirements below depend on it and future
ones will too.

| Property | Value |
|---|---|
| Earliest session stored | 2018-08-17 |
| Sessions | 1,985 |
| History depth, per symbol | 174 to 1,985 sessions |
| Price basis | Split/bonus adjusted, never dividend adjusted (FR-3.3, FR-3.4) |
| Periods | Trading sessions, never calendar days (FR-6.1) |

**Depth varies enormously by symbol** — recent listings have months, not
years. Any requirement phrased as "all-time" or "since listing" must either
accept that limit or fund a deeper backfill first.

The eight-year depth is deliberate, not incidental: five years started the
usable window at an unrepresentative point and excluded the only bear phase in
range. The same screen tested over eight years moved from 2.43% to 14.46% net
CAGR (D-9). A plain `backfill` still fetches five — pass `--years 8`.

---

## 6. Requirements added in this document

### FR-15 — Size tier and period high

**FR-15.1 — Size tier visibility.** The NIFTY 500 view MUST show which size
tier each constituent belongs to, using the index's published name — Nifty 50,
Next 50, Midcap 150, Smallcap 250.

The tier MUST be stored as the provider's own constituent-file key, so a
screen filter matches what NSE publishes; the friendly name is display only.
String-valued columns MUST render as text — a string passed through the
numeric formatter renders `NaN`, which is how this field and
`ineligible_reason` both displayed before 2026-08-31.

*Acceptance:* the All NIFTY 500 grid shows 50 / 50 / 150 / 250 across the four
tiers, totalling 500, with no cell reading `NaN`.

*Status:* Built (verified in-browser, 2026-08-31)

---

**FR-15.2 — Period high.** The system MUST compute, per symbol and session:

```
high_period           = max(High) over all stored sessions strictly before today
pct_from_period_high  = C_0 / high_period - 1
```

The current bar MUST be excluded. Were it included, a stock making a new high
today would read as 0% away and become indistinguishable from one still
approaching — which is the entire distinction the metric exists to draw.

This MUST NOT be presented as an all-time high. The lookback is however much
history has been backfilled (§5), so for a long-listed symbol it is a
multi-year high. The UI, the metric registry and the operator manual MUST each
say so, and `history_days` MUST be available alongside it so the real depth is
visible per row.

*Acceptance:* for highs `10, 12, 11, 15, 13`, `high_period` is
`NaN, 10, 12, 12, 15`. On 2026-08-28 REDINGTON has `high_period` 370.80 against
an intraday high of 378.50 and a close of 366.00 — it set a new all-history
intraday high and closed back under the prior one.

*Status:* Built (`test_prior_expanding_max_excludes_the_current_bar`)

---

**FR-15.3 — Approaching High screen.** A screen MUST list names within 3% of
their period high that have not yet cleared it, with the trend intact and
volume not dried up.

Names at or above the period high MUST be excluded — that is the 52-Week High
Breakout screen's job, and including them would make the two screens
indistinguishable.

*Acceptance:* on 2026-08-28 the screen returns 7 names; 9 constituents that had
already cleared their high are absent; every row satisfies
`-0.03 <= pct_from_period_high < 0`.

*Status:* Built (`test_approaching_high_excludes_names_that_already_broke_out`)

---

**FR-15.4 — Honest lookback labelling.** Where a metric's window depends on
how much history happens to be stored, the UI MUST expose that depth rather
than implying a fixed window.

*Acceptance:* the Approaching High results show `History (sessions)` beside
`% from period high`; on 2026-08-28 those range from 727 to 1,985 within a
single seven-row result.

*Status:* Built

---

### FR-16 — Operability

**FR-16.1 — Pipeline and scheduler state on demand.** The operator MUST be
able to determine, without the API running, whether a scheduler is armed, what
the last pipeline run did stage by stage, and how old the data is.

"API is up" MUST NOT be reported as "scheduler is armed": plain `serve`
answers on the port while nothing is scheduled to fire, and conflating the two
hides the failure this check exists to catch.

*Acceptance:* `scripts/scheduler_status.py` exits 0 current, 1 unknown, 2
stale, and reports the two facts on separate lines.

*Status:* Built

---

**FR-16.2 — One freshness rule.** Every component reporting data freshness
MUST use a single shared implementation of "the latest session whose data
could plausibly be published", including the 18:45 IST publish cutoff.

Before the cutoff, today's data is not late — it is not due. A staleness
warning that fires every trading morning by design is one the operator learns
to ignore, which defeats FR-8.9.

*Acceptance:* `mktcal.calendar.expected_session` is the only implementation;
the API delegates to it. At 11:51 IST on a trading day with data through the
prior session, the verdict is `current`, not `stale`.

*Status:* Built (`test_status.py`, 5 tests)

---

**FR-16.3 — Failure diagnosis is written down.** A runbook MUST exist that
separates incidents by layer (dev server / API / pipeline) with the symptom
identifying each, and MUST record known failure modes as they occur.

*Acceptance:* `docs/TROUBLESHOOTING.md` exists and covers all three layers.

*Status:* Built

---

## 7. Non-functional status

| ID | Requirement | Budget | Measured | State |
|---|---|---|---|---|
| NFR-1.7 | Metric recompute, 500 symbols | 60 s | ~24 s (2026-08-31) | Met |
| NFR-1.8 | Full incremental EOD pipeline | 15 min | 7 min 16 s (2026-08-29, six-session catch-up) | Met |
| NFR-4.1 | API binds loopback only | — | Enforced, warns otherwise | Met |
| NFR-5.1 | Hand-computed metric tests | — | 172 tests passing | Met |
| NFR-5.6 | Docs generated, not written | — | METRICS.md, operator manual | Met |

> **NFR-1.7 was breaching at ~116 s and is now met at ~24 s.** The cause was
> not the larger store: two FR-14 support kernels were per-bar Python loops,
> and `np.delete` alone ran once per price row. Vectorising them left output
> bit-identical across all 500 symbols. See D-10; resolved as **B-9**.

**Backtesting (Phase 3)** is partially built: the engine, walk-forward harness
and CLI exist, and §5's history depth governs what can be asked of them. The
eight-year window carries six testable corrections including the 2020 crash at
−38.3%; the first session holding any eligible stock is 2019-08-30 (D-9).
`docs/backtest-findings.md` is the revised eight-year version and carries its
own caveat that every figure is survivorship-biased upward. The five-year
results it replaced were materially wrong, not merely noisier — the same screen
read 2.43% then and 14.46% now — so a backtest number quoted from anywhere
other than that revised document should be treated as suspect.

---

## 8. Open questions

The B-series lives in `DECISIONS.md`; B-2, B-3, B-5, B-6 and B-7 remain open
there. The two raised by this document:

| # | Question | State |
|---|---|---|
| B-8 | Records stated five years; the store holds eight | **Resolved 2026-08-31** — see below |
| B-9 | NFR-1.7 recompute breaching at ~116 s against a 60 s budget | **Resolved 2026-08-31** — vectorised to ~24 s, see D-10 |

**B-8, as resolved.** The original entry overstated the problem: it claimed
D-9 said five years. D-9 did not. D-9 recorded the extension to eight years on
2026-08-27, with measurements — it was only its heading that named the problem
rather than the resolution, which is how a skim of the titles produced the
wrong conclusion here.

What was genuinely stale was `README.md` (backfill depth, session counts,
`--years 6` guidance, and a performance table measured on 562k rows) and D-7,
whose depth decision D-9 had superseded without D-7 saying so. Both are now
corrected, D-9's heading names its resolution, and the `--years 5` CLI default
is called out wherever depth is discussed, since that default is the one thing
that did not change.

**B-9, as resolved.** Profiling contradicted the assumption recorded when it
was filed. The breach was not the store growing 50% — it was `swing_lows` and
`nearest_support` scanning bar by bar, costing 38.9 s of 58.7 s. Both are
sliding-window problems that numpy expresses directly. Vectorised, the recompute
runs in ~24 s with bit-identical output, verified against verbatim copies of the
previous implementations across all 500 symbols and seven edge cases.

Roughly 60% of the remaining 24 s is Wilder smoothing, a sequential recurrence
that would need scipy to vectorise exactly. Adding a dependency to reclaim time
already inside budget was rejected; see D-10.

---

## 9. Change log

| Date | Change | Requirements |
|---|---|---|
| 2026-08-31 | Document created from as-built status | — |
| 2026-08-31 | Size tier shown as text; period high and Approaching High screen added | FR-15.1–15.4 |
| 2026-08-31 | Scheduler status command, shared freshness rule, runbook | FR-16.1–16.3 |
| 2026-08-31 | B-8 resolved: README and D-7 corrected to eight years, D-9 heading fixed | — |
| 2026-08-31 | B-9 resolved: support kernels vectorised, NFR-1.7 back inside budget | NFR-1.7 |

<!-- Append new rows above this line. Take the next free ID from §2. -->
