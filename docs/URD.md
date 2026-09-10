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
| FR-17.x | Fibonacci retracement zone | This document, §6 | In use |
| FR-18.x | Sectoral and thematic indices | This document, §6 | In use |
| FR-19.x | Swing trade setup | `SRS-addendum-FR19-swing-trade.md` | In use |
| **FR-20.x** | — | — | **Next free** |

Supporting series: `NFR-1` to `NFR-6` (non-functional), `AR-1` to `AR-4`
(architecture), `D-1` to `D-11` (decisions, in `DECISIONS.md`), `B-1` to `B-11`
(open questions, in `DECISIONS.md`), `R-x` (risks; R-1, R-3, R-5 cited in code).

Next free: **NFR-7**, **D-12**, **B-12**.

---

## 3. What exists today

Verified against the running system on 2026-08-31; the sector-index rows and
the endpoint count on 2026-09-07.

| Capability | State | Evidence |
|---|---|---|
| Provider abstraction (AR-1) | Built | NSE archives, Yahoo, CSV fixtures |
| Universe sync (FR-1.x) | Built | 500 constituents; membership as an SCD |
| Backfill and incremental ingest (FR-2.x) | Built | 841,519 rows, 1,985 sessions |
| Corporate actions (FR-3.x) | Built | Reconciliation gate passes on all 500 |
| Validation gate (FR-4.1) | Built | Nine checks, Block/Warn severities |
| Scheduling (FR-5.1) | Built | In-process APScheduler, 18:45 IST |
| Metric engine (FR-6.x) | Built | **101 metrics**, hand-computed unit tests. FR-18's index metrics are computed outside the registry and are not counted here |
| Screener (FR-7.x) | Built | Filter compiler, **10 screens** + universe browser |
| API (§2.3) | Built | 16 endpoints, loopback only |
| Frontend (FR-8.x) | Built | Dashboard, virtualised grid, stock detail |
| Exports (FR-9.x) | Built | xlsx, csv, html, each with provenance |
| Risk and tax (FR-10, FR-12) | Built | Stops, cash-only sizing, TDS round-trip |
| Backtesting (Phase 3) | Partial | Engine and walk-forward exist; see §7 |
| Swing exit rule (FR-19.1-19.3, 19.8) | Built | Tiered trailing stop, conditional time stop, re-entry cooldown; all opt-in, 13 tests |
| Swing dashboard screen (FR-19.5-19.7) | **Blocked** | FR-19.4's gate failed on all four runs; see `swing-backtest-findings.md` |
| Operability (FR-16.x) | Built | Status command, troubleshooting runbook |
| Sector indices (FR-18.1-18.4) | Partial | 24 tracked, 69,030 sessions; 18 with real OHLC, 6 close-only and reported unavailable |
| Sector view (FR-18.10) | Partial | Range bar per index; no screen hand-off, and the sort awaits FR-18.8 |

**Not built:** watchlist, trade journal, notification digest, and FR-18.5-18.9 (sector breadth, relative strength, breadth thrust, momentum score, concentration).

### Universe as of the 2026-08-28 session

500 constituents — 476 eligible for screens, 24 excluded for thin liquidity,
short history or a restricted series. Size tiers: 50 Nifty 50, 50 Next 50,
150 Midcap 150, 250 Smallcap 250.

### The nine screens

| Screen | Finds | Rows cap |
|---|---|---|
| Momentum Leaders | Strongest volatility-adjusted trends | 20 |
| Trend Template | All eight structural criteria met | 100 |
| 52-Week High Breakout | Cleared the 52w high on volume today | 50 |
| Volatility Contraction | Tight base after an advance | 50 |
| Pullback to Support | Uptrend resting on the 21 EMA or 50 SMA | 50 |
| Pullback + Reversal | At support with reversal confirmation | none |
| Approaching High | Within 3% of the period high, not yet through | 50 |
| Fibonacci Reversal Zone | In the 50-61.8% retracement, turned today | 25 |
| **Momentum Breakdown** | **EXIT signal for held names** | 100 |

Plus **All NIFTY 500**, a universe browser rather than a screen: it is the
only view that does not hide ineligible rows, and exists so "why is this
stock never in my results" is answerable (FR-1.5).

Pullback + Reversal is the one screen with no cap. FR-14.6 asks for a top-10
*dashboard section*, and carrying that limit in the preset truncated the
screener as well — a qualifying setup ranked 18th was silently absent from a
list that read as complete. The dashboard endpoint now takes its own slice of
ten, so the section still meets FR-14.6 while the screen lists every match.
Where a cap does apply, the grid reports it as "top N of M matches".

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

**A second series now sits beside this one**, and it does not share these
properties. FR-18.2 stores 69,030 sessions across 24 sectoral and thematic
indices, reaching back to 2007-09-17 for Nifty Bank and Nifty IT — deeper than
the stock history, and still short of any of their inceptions. Eighteen carry
real OHLC from the vendor; six are close-only projections of a sampled
valuation file and hold 5-12% of the sessions their span implies, which is why
FR-18.3 reports them unavailable rather than computing a 52-week window over
them. So "the data foundation" is now two foundations with different depths,
different bases and different gaps, and a requirement that spans both has to
say which it means.

| Property | Index series |
|---|---|
| Tracked indices | 24 (14 sectoral, 10 thematic) |
| Sessions stored | 69,030 |
| Earliest session | 2007-09-17 (Nifty Bank, Nifty IT) |
| Basis | 18 OHLC, 6 close-only; price return, never total return |
| Reaches inception | None — so every peak is a period high (D-11) |

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

### FR-17 — Fibonacci retracement zone

**FR-17.1 — Impulse leg anchors.** The system MUST identify the most recent
completed impulse leg per symbol and session: confirmed swing low A to
confirmed swing high B, requiring amplitude >= 20%, duration 15-250 sessions,
age <= 60 sessions, no single-session move above 20% inside the leg, and B
still the highest high through today. Up to three swing highs are tried before
reporting NO_VALID_LEG.

A swing MUST NOT be usable before the session its confirming window completes.
Both dates are stored, and all screening and backtesting reference the
confirmed date. Using the extreme date is look-ahead and it is silent — the
screen still returns rows and a backtest still produces a return nobody could
have earned.

FR-17 reuses FR-14's fractal rather than defining a second notion of a swing;
`swing_highs` is its mirror.

*Acceptance:* `test_swing_anchor_is_not_available_before_confirmation` asserts
no leg surfaces before B + reach. On 2026-08-31 INFY shows B printed
2026-08-10 and usable from 2026-08-13.

*Status:* Built (`test_fib_zone.py`, 19 tests)

---

**FR-17.2/17.3 — Levels, ratio and zone.** Levels are `B - r*(B-A)` for r in
{0.382, 0.500, 0.618, 0.786}. The zone runs from level(0.618) up to
level(0.500), inclusive at both ends.

The 61.8% level is the LOWER price. Written the intuitive way round the filter
returns nothing and reads like a data fault. `fib_max_retracement` is stored
separately from the current ratio: a leg wicked to 0.72 and recovered to 0.55
has been tested and held; one that never traded past 0.55 has not.

A deeper retracement is cheaper, NOT stronger, so the ratio MUST carry zero
weight in the ranking and MUST NOT be offered as a sort.

*Acceptance:* A=400, B=560, R=160 gives 498.88 / 480.00 / 461.12 / 434.24;
close 470 gives 0.56250. Closes at 480.00 and 461.12 are inside, 481.00 and
460.00 outside.

*Status:* Built

---

**FR-17.4/17.5 — Volume shape and the reversal bar.** Three ratios, not one
threshold: impulse, dry-up and the turn's own expansion. A single "volume
above average" test MUST NOT be used — in a retracement, elevated volume
selects for distribution as readily as accumulation. Delivery against its
20-session mean is a caution badge only, never a filter (FR-2.7 is
warn-not-block).

The pullback window is `(B, today)`, open at BOTH ends, and the dry-up ratio
and the turn ratio MUST share it. Today is excluded because it is the session
those ratios exist to judge: with today inside the average, a heavy turn lifts
the very number that has to read thin before the turn is examined, so the
better the bar the likelier it fails its own gate. The turn MUST be measured
against that pullback and MUST NOT use `rel_volume`, whose 50-session window
spans the impulse leg this same requirement has just demanded be heavy — that
asks the most volume of the turn exactly where the advance was best confirmed.
A pullback shorter than three sessions leaves the turn ratio null and the bar
unconfirmable; guessing from two sessions is worse than saying nothing.

A symbol MUST NOT be TRIGGERED on zone membership alone. Being in the band is
a location; the reversal bar is the event. Conflating them produces a standing
list of stocks in decline.

*Acceptance:* pre-leg 100000, leg 145000, pullback 98600 gives 1.45 and 0.68.
O 462 H 472 L 460 C 470 gives close position 0.83333 and passes; C 465 gives
0.41667 and fails. With today's volume at 197200 against that 98600 pullback
the dry-up ratio stays 0.68, not 0.816, and the turn ratio reads 2.0.

*Status:* Built

---

**FR-17.6/17.7 — The screen, stop and reward.** Ninth screen, cap 25, ranked by
`fib_setup_score` over winsorised z-scores. Stop is the WIDER of level(0.786)
and the in-zone swing low less half an ATR, because the wider stop survives
noise the tighter one would be shaken out by.

Most sessions return 0-5 rows. An empty grid is the setup being absent.

*Acceptance:* C 470, level(0.786) 434.24, swing 460, ATR 12 gives stop 434.24,
risk 35.76 and R:R 2.51678. On 2026-08-31 the screen returns 0 rows with the
funnel reading 500 → 137 gated → 72 with legs → 0 in zone.

*Status:* Built

---

**FR-17.8/17.9/17.10 — Transparency.** An exclusion reason per constituent, a
funnel with per-stage counts, a per-row working panel showing the arithmetic,
and a chart overlay carrying the leg, the four levels, the shaded band, the
stop and a marker on the session the leg became available.

The word "support" MUST NOT be used for a Fibonacci level anywhere. Support is
where buyers actually appeared (FR-14.2); these are geometry. An empty grid
MUST be distinguishable from a misconfigured threshold — they look identical
otherwise and only one is worth acting on.

*Acceptance:* `/api/fib/funnel` returns seven labelled stages. The working
panel renders A, B, amplitude, R, all four level computations and both volume
ratios with their windows.

*Status:* Built

---

### FR-18 — Sectoral and thematic index dashboard

Full proposal and reasoning in `docs/FR-18-sectoral-index-dashboard.md`.

**FR-18.1 — Index universe.** Approximately 25 NSE indices — all sectoral, plus
thematics whose constituent base is materially distinct — held as a versioned
configuration list, not derived at runtime.

Strategy and factor indices (Alpha, Quality, Low Volatility, Equal Weight) MUST
NOT appear: they measure a factor across sectors, not a sector, and ranking them
alongside sectoral indices invites a rotation conclusion the data does not
support. A thematic overlapping a tracked index by more than a configurable
share of weight (default 70%) MUST be flagged `OVERLAPS:<index>` — two
near-identical indices ranking one and two reads as a confirmed rotation when it
is one move counted twice.

The universe is **24 indices** as at 2026-09-07: those whose NSE constituent
list resolves (B-10 §7.2). Nifty Capital Markets is deferred until its archive
slug is known. Each entry MUST carry a hand-maintained `documented_inception`,
which FR-18.2 reads.

*Acceptance:* 24 ± 3 indices; every entry resolves to a live NSE constituent
list; no strategy or factor index appears; at least one thematic carries an
`OVERLAPS` flag.

*Status:* **Built** (`test_the_tracked_universe_is_the_size_fr_18_1_specifies`,
`test_no_strategy_or_factor_index_is_tracked`,
`test_every_tracked_index_has_a_constituent_list_mapped`) — except the
`OVERLAPS` flag, which needs the weights FR-18.9 derives and is not yet
computed.

**FR-18.2 — Index history, to the depth actually obtainable.** A daily series
per tracked index, each with its actual `first_session` recorded, extending the
existing `index_ohlcv_daily` table rather than adding a second one. A distinct
pipeline stage from constituent ingestion, failing as a Warn not a Block
(FR-4.1) — 500 stock rows remain correct without it.

Ingestion is hybrid and permanently so (B-10, resolved): Yahoo serves OHLC for
18 of the tracked indices, and the already-ingested close-only `ind_close_all`
covers the rest. No new provider is needed — `_INDEX_SYMBOLS` widens from two
entries to eighteen, plus a close-only path.

Two independent facts MUST be recorded and displayed per index. `ohlc_basis`
(`OHLC` | `CLOSE`) decides whether `high_52w` and `low_52w` use real highs and
lows or are computed on close. `reaches_inception` decides the peak's name:
`ath_*` only where `first_session` is on or before the index's documented
inception, `period_*` otherwise. Inception is a hand-maintained field in
FR-18.1's config because no automated source states it, and no index currently
qualifies — Nifty Bank launched in 2003 and its deepest available series starts
in 2007. **`ath_*` therefore appears nowhere today.** This is FR-15.2's rule
reaching its expected answer rather than being argued around.

The series is price return, not total return, and reconstitution means an old
peak was set by a different basket. Both MUST be labelled wherever a peak shows.

*Acceptance:* `first_session`, `ohlc_basis` and `reaches_inception` stored and
shown per index; no
view, export or registry entry uses "all-time" for an index whose
`first_session` postdates its documented inception; a simulated index feed
failure produces a Warn and leaves the stock pipeline Built and current.

*Status:* **Built** (`test_an_index_without_a_ticker_falls_back_to_close_and_stores_no_high`,
`test_a_series_short_of_inception_reports_a_period_high_not_an_ath`,
`test_one_vendor_failure_leaves_the_other_series_intact`,
`test_no_metric_is_ever_named_all_time`). Backfilled live 2026-09-07: 18 series
with real OHLC, 6 close-only. Ingestion is a manual `alpha500 index-series`
command, not yet a nightly pipeline stage.

**FR-18.3 — Range and drawdown.** Per index and session: `high_52w`, `low_52w`,
`range_position_52w`, `pct_from_52w_high`, `peak_value`, `peak_date`,
`pct_from_peak`, `sessions_since_peak`. The current bar MUST be excluded from
`peak_value` per FR-15.2, or an index making a new high today reads as 0% below
its peak and is indistinguishable from one still approaching it.

`drawdown_duration` MUST NOT be added: `peak_value` is the running maximum
excluding today, so every session after `peak_date` is below it by construction
and the count is identical to `sessions_since_peak` on every row.

*Acceptance:* for `low_52w 40,000`, `high_52w 52,000`, `peak_value 55,000`,
close `46,000`: `range_position_52w = 0.500`, `pct_from_52w_high = -11.54%`,
`pct_from_peak = -16.36%`. Named test
`test_index_range_and_drawdown_worked_example`.

*Status:* **Built** (`test_index_range_and_drawdown_worked_example`). Fields are
named `period_high` / `pct_from_period_high`, per FR-18.2 — no index reaches a
documented inception, so `ath_*` is not in use.

**FR-18.4 — Trend state, in three values not two.** `UPTREND` requires close >
SMA200, SMA50 > SMA200 and SMA200 rising over 21 sessions; `DOWNTREND` the
mirror; `TRANSITIONAL` everything else. MUST NOT be reduced to a binary — an
index oscillating around a flat 200 SMA satisfies neither definition, and
collapsing it into "uptrend" because price is a fraction above the line
manufactures conviction the data does not contain. Carries `sessions_in_state`.

*Acceptance:* a synthetic series flat at its 200 SMA with slope inside ±0.1%
over 21 sessions classifies `TRANSITIONAL`. On any live session the three states
sum to the tracked index count with no nulls. Named test
`test_trend_state_returns_transitional_when_neither_definition_holds`.

*Status:* **Built**
(`test_trend_state_returns_transitional_when_neither_definition_holds`,
`test_sessions_in_state_counts_only_the_current_run`). Live on 2026-09-07:
5 UPTREND, 9 TRANSITIONAL, 4 DOWNTREND, summing to the 18 measurable indices.
The nine transitional are the point — a binary would have labelled each of
them.

**FR-18.5 — Sector breadth.** Share of members above their 50 and 200 SMA,
within 2% of a 52-week high, and at `trend_template_score >= 6`, plus
`member_count`. The constituent-to-index mapping MUST be a versioned
configuration table and MUST NOT be derived at runtime from
`instruments.industry` — Financial Services alone feeds Nifty Bank, Nifty PSU
Bank, Nifty Private Bank and Nifty Financial Services, so a runtime derivation
assigns members to the wrong index or to several.

An index in `UPTREND` with breadth below 40% is not a sector in an uptrend, and
the view MUST show the two adjacently. Breadth comes from the NIFTY 500, not
published membership, so a sector holding names outside the 500 is measured on a
subset; below 8 contributing members breadth MUST be suppressed rather than
shown. Measured 2026-09-07 (B-10 §7.4), the limit is narrow: 21 of 24 indices
have every member inside the 500, PSU Bank has 11 of 12, India Defence 11 of 19,
and **only Nifty Media (5 of 10) is suppressed**.

*Acceptance:* 26 of 40 members above their 50 SMA reports 65.0% with
`member_count = 40`; 5 members reports suppressed, not a percentage. Named test
`test_breadth_suppressed_below_member_floor`.

*Status:* Proposed

**FR-18.6/18.7 — Relative strength and breadth thrust.** `rs_ratio_N` for N in
{21, 63, 126, 252} against NIFTY 500, plus the rebased `rs_line`, its 50-session
SMA, `rs_improving` and `rs_new_high_63`. `rs_ratio_63` is the primary rotation
metric: a sector up 6% while the market rose 9% is one to avoid, and absolute
return will not tell you that. `rs_new_high_63` MUST be computed on the ratio
line, not price — a sector at a new relative high while still below its own
52-week high is the earliest reliable rotation signal here, and a price filter
cannot see it.

`breadth_thrust` flags `breadth_above_50dma` crossing from below 30% to above
50% within 10 sessions, thresholds configurable, recording
`breadth_thrust_date` and persisting 20 sessions — its value is that it fired
recently, not that it fires today.

*Acceptance:* index 63-session return `0.18` against `0.06` gives
`rs_ratio_63 = 11.32%`. A breadth series `28, 31, 38, 44, 52` sets the flag on
the fifth session and retains it for 20. Named tests
`test_relative_strength_ratio` and
`test_breadth_thrust_fires_on_crossing_not_on_level`.

*Status:* Proposed

**FR-18.8 — Sector momentum score.** `0.30*z(momentum_score) +
0.25*z(rs_ratio_63) + 0.20*z(breadth_above_50dma) + 0.15*z(breadth_at_52w_high)
+ 0.10*z(rs_ratio_21)`, reusing the existing engine's definitions.

Outliers clipped at ±3 standard deviations. FR-6.8's 1st/99th percentile
winsorisation MUST NOT be reused: written for a 500-symbol cross-section, at
n≈25 the 1st percentile is the minimum, so the clip does nothing and the score
inherits an unguarded tail. Suppressed breadth redistributes its weight
proportionally rather than counting zero, which would rank an unmeasurable
sector as a weak one. The peak-distance metric carries zero weight — a sector
40% off a 2021 high can be the strongest thing in the market today.

*Acceptance:* scores computed for all tracked indices with no nulls; a
suppressed-breadth sector scores from redistributed weights and is marked; a
component at 8 standard deviations moves the score no further than one at 3.
Named tests `test_sector_score_redistributes_suppressed_breadth_weight` and
`test_sector_score_clips_outliers_at_three_sigma`.

*Status:* Proposed

**FR-18.9 — Concentration, dispersion and persistence.** `top3_weight_pct`,
`constituent_dispersion` and `leadership_persistence` qualify the score and MUST
NOT be folded into it — a score that has absorbed them cannot be interrogated.
Above a configurable 45% top-3 weight the row carries a concentration badge: a
trend on a 55%-concentrated index is a view on two companies.

`top3_weight_pct` is **derived** from free-float market cap (B-10, resolved):
NSE's constituent lists carry no weight column, so weight is `floatShares ×
price` normalised across members. It MUST be labelled `DERIVED` and MUST NOT be
presented as the published weight. On Nifty Bank the derived top three reads
69.2% against a published 60–63%: uncapped derivation always overstates
concentration on a capped index, which is the safe direction for a warning and
the wrong direction for anything precise. FR-18.1's 70% overlap test therefore
uses membership overlap by count, not these weights. Where a member's float
figure is missing the metric MUST report unavailable rather than normalise over
a partial basket.

*Acceptance:* members weighing 28%, 14% and 9% report `top3_weight_pct = 51%`
with the badge; an index with no stored membership reports unavailable and no
badge. Named test `test_concentration_badge_fires_above_threshold`.

*Status:* Proposed

**FR-18.10/18.11 — The view, the hand-off, and the restraint.** One row per
index as a horizontal range bar, sorted by `trend_state` then score descending.
The track MUST span `low_52w` to `max(high_52w, peak_value)`, or the peak marker
falls outside the drawn range and disappears on exactly the indices furthest
from their peak. `trend_state` MUST be carried by glyph or label as well as
colour (NFR-6.3).

The view MUST NOT present a buy signal on an index — futures need a custodian
and are out of scope under FR-12. Each row MUST offer a one-click hand-off
applying the sector as a filter to the existing screens; without it the view is
a wall-chart rather than a tool. No forecast, projected return, or predictive
label anywhere, per the restraint FR-17.9 applies to Fibonacci levels.
`leadership_persistence` MUST be shown by default, not behind a toggle: a
ranking showing only the score presents a sector in its fortieth week of
leadership identically to one in its second, and buying the first believing it
is the second is the ranking's most common misuse.

*Acceptance:* an index whose peak exceeds its 52-week high renders with the peak
marker inside the track; the hand-off filters Momentum Leaders to that sector's
constituents only; `UPTREND` sorts above `TRANSITIONAL` above `DOWNTREND`; a
full-text search of the bundle, registry and manual returns zero occurrences of
"forecast", "projected" or "predicted" applied to a sector.

*Status:* **Partly built.** The range-bar view exists on the dashboard with the
track stretched to `max(high_52w, period_high)`, trend carried by glyph and
label as well as colour, and the six unmeasurable indices named with their
reason rather than dropped. Live figure recorded on first run: on 2026-09-07,
5 indices are UPTREND, 9 TRANSITIONAL and 4 DOWNTREND, of 18 measurable.

Not built: the sort is trend state then position in the 52-week range, because
FR-18.8's momentum score does not exist yet; and the one-click hand-off applying
a sector as a filter to the screens is absent, which is the part that makes this
a tool rather than a wall-chart. Both stay Proposed.
---

## 7. Non-functional status

| ID | Requirement | Budget | Measured | State |
|---|---|---|---|---|
| NFR-1.7 | Metric recompute, 500 symbols | 60 s | ~27 s (2026-08-31, with FR-17) | Met |
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
| 2026-08-31 | Fibonacci retracement zone: 26 metrics and the ninth screen | FR-17.1-17.10 |
| 2026-09-07 | Sector/thematic index dashboard: range and drawdown, three-state trend, breadth, rotation metrics | FR-18.1–18.11 |
| 2026-09-07 | B-10 resolved: index history sourced (Yahoo OHLC for 18, close-only for the rest), weights derived, `ath_*` naming withdrawn | FR-18.1, FR-18.2, FR-18.5, FR-18.9 |
| 2026-09-07 | Sector index universe, series ingestion, range and drawdown, three-state trend, and the first view | FR-18.1–18.4, FR-18.10 |
| 2026-09-09 | Screens report their pre-limit match count and the grid shows it; Pullback + Reversal uncapped, its top-10 slice moved into the dashboard section | FR-7.x, FR-14.6 |
| 2026-09-09 | NSE DUMMY placeholder constituents filtered out; `alpha500 universe` now writes to the change log the way the pipeline does | FR-1.2, FR-1.4 |
| 2026-09-09 | Swing-trade tiered trailing-stop exit rule with re-entry cooldown, opt-in on the backtest engine; Phase 2 dashboard screen specified but gated on backtest proof | FR-19.1-19.8 |
| 2026-09-09 | FR-19.4 gate run: all four configurations fail. Phase 2 stays blocked. Survivorship warning repaired after one stray membership interval silenced it | FR-19.4 |
| 2026-09-10 | `materialise` fixed for bulk ranges (index dropped around the rewrite); history re-materialised from 2019 so FR-17 columns span the backtest window | FR-5.4, FR-17 |
| 2026-09-10 | FR-19.4 gate re-run on the complete history: still fails on all four. Fibonacci arm re-diagnosed - one signal in seven years, from the trend gates and the retracement band rarely holding at once | FR-19.4 |

<!-- Append new rows above this line. Take the next free ID from §2. -->
