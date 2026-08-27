# Decision Record

SRS section 2.1 specifies the stack rather than suggesting it, and requires a
written rationale for any deviation. This file carries those rationales, plus
resolutions to the Appendix B open items as they are settled.

---

## D-1 — Kite Connect replaced by free sources (deviates from §2.1, FR-2.3)

**Decision.** Market data comes from NSE public archives and Yahoo Finance.
`KiteProvider` is not implemented.

**Rationale.** Kite Connect historical data requires a paid subscription
(₹2,000/month) that this deployment does not hold. The SRS already names NSE
public archives as the fallback source (FR-2.6), and that source is free,
authoritative and sufficient. What changes is which provider is primary, not
the architecture: AR-1's `MarketDataProvider` boundary is exactly what makes
this a contained change.

**Consequences.**

- FR-2.3 (Kite historical endpoint) and FR-2.4 (3 req/s Kite rate limit) do not
  apply. Rate limiting still exists, tuned per provider.
- FR-11.5 (daily access-token expiry) does not apply — neither free source
  authenticates. This removes risk R-3, which the SRS rated "Certain".
- R-1 (NSE changes archive URLs or schema) rises in importance, since NSE is no
  longer only the fallback. Mitigated by schema validation that fails loudly
  (`SchemaDriftError`) rather than emitting nulls.
- NFR-4.4 (broker keys scoped read-only) is satisfied vacuously: there are no
  broker credentials and no code path capable of placing an order.

---

## D-2 — Split roles between the two free providers

**Decision.** `YahooProvider` performs bulk backfill and supplies the index
series and corporate actions. `NseArchiveProvider` performs the nightly
incremental fetch, delivery data, and the universe list.

**Rationale.** The two sources have opposite shapes. Yahoo returns a decade of
daily candles for one symbol per request, so a 500-symbol cold start costs ~500
requests. The bhavcopy is a per-session file covering every symbol, so the same
backfill would cost ~1 250 downloads, but a *daily* update costs exactly one.
Each source is used where its shape is an advantage.

It also satisfies NFR-2.2 — no single provider failure causes data loss — and
gives validation check V9 (cross-source close agreement) two genuinely
independent sources to compare. Spot check on 2026-08-25: RELIANCE closed at
1317.00 on both.

---

## D-3 — Instrument tokens are derived, not vendor-supplied

**Decision.** `instrument_token` is a deterministic 63-bit hash of the ISIN,
falling back to the trading symbol.

**Rationale.** The schema is keyed on an integer token because it was designed
against Kite, which supplies one. Free sources do not. ISIN is preferred over
symbol because symbols get renamed and ISINs do not — and a rename must not
orphan a decade of price history. The hash is stable across runs, which AR-4
requires.

---

## D-4 — B-1 resolved: Yahoo history is already split-adjusted

**Decision.** `YahooProvider.prices_are_adjusted = True`;
`NseArchiveProvider.prices_are_adjusted = False`. The adjustment layer tracks
how current each row's source already is.

**Evidence.** This was not assumed either way, per FR-3.2. On the first
reconciliation run, 360ONE showed a **+98.97%** adjusted return on its
2023-03-02 ex-date — the signature of double adjustment, since applying a 0.5
factor to an already-halved history doubles the apparent gap. After the fix,
`adj_factor` is 1.0 throughout and the series is continuous across the ex-date
(443.33 → 441.05). Reconciliation reports zero violations.

**Consequence.** Because the two sources have opposite adjustment semantics,
the factor cannot be a pure function of `trade_date`. A Yahoo row only takes
splits later than its *fetch* date; a raw bhavcopy row takes every split after
its own session. Getting this wrong in either direction corrupts every
downstream metric, which is why FR-3.2 makes the reconciliation a release gate.

**Still open.** Yahoo reports bonus issues as splits, so the two are not
distinguishable here. They adjust price identically, so metrics are unaffected;
only the display label differs. Item B-2 remains open.

---

## D-5 — TanStack Table pinned to v8

**Decision.** `@tanstack/react-table@^8.21.3` rather than the current v9.

**Rationale.** v9 ships a substantially reworked, feature-based API. Building
against it from type definitions alone would be guesswork. v8 is the same
library the SRS specifies, is stable and well documented, and supports React 19.
Revisit once v9's documentation matures.

---

## D-6 — DuckDB concurrency shapes the deployment model

**Observation, not a choice.** DuckDB permits one read-write process *or* many
read-only ones, never both simultaneously. The nightly pipeline is a writer and
the API is a reader, so they cannot both hold the file.

**Current handling.** A read attempted during a pipeline run raises
`DatabaseBusyError`, which the API surfaces as HTTP 503 with
`reason: "pipeline_running"` — visible and explicable rather than a generic
server error.

**Resolved 2026-08-27.** The SRS specifies APScheduler **in-process** (§2.1),
and that is now implemented — but it needed more than just co-locating them.

DuckDB refuses to mix access modes *within* a process too, not only across
processes: opening read-write while any read-only connection is alive raises
`ConnectionException`. So `serve --with-scheduler` would have started cleanly,
served all day, and then failed at 18:45 on the first night — silently, unless
someone read the log. Verified by direct experiment before it could happen.

Every caller now takes a cursor off one shared per-process connection.
`configure_process_connection(read_only=...)` fixes the mode at startup:
`serve --with-scheduler` holds it read-write so the pipeline can write; a plain
`serve` holds it read-only, leaving the file available to other readers. A read
attempted while a *separate* process writes still surfaces as HTTP 503 with
`reason: "pipeline_running"`.

The CLI's separate-process pipeline remains a development convenience and
should not run concurrently with a served API.

---

## D-7 — Backfill stays at five years; acceptance criterion 1 is waived

**Decision.** `alpha500 backfill` defaults to `--years 5`, by operator
decision on 2026-08-26.

**Context.** FR-2.2 requires a minimum of 1 260 trading sessions and glosses
that as "≈5 calendar years". NSE actually trades roughly 247 days a year, so
five calendar years delivers about 1 236 sessions. Measured on the 2026-08-26
backfill: five years produced exactly 1 236 index sessions, and no symbol
reached 1 260.

**Consequence, accepted.** Acceptance criterion 1 ("≥ 1 260 sessions for ≥ 495
of 500 constituents") does not pass as literally written. Nothing else is
affected: every metric in section 5 needs at most 252 sessions, so the full
metric set computes correctly on this history. The shortfall matters only for
Phase 3 backtesting depth, which the SRS itself would rather see at 2 520
sessions anyway.

Pass `--years 6` to clear the criterion when Phase 3 begins.

---

## D-8 — Base detection amended: FR-6.14 as written cannot fire

**Decision.** Two changes to `_detect_base`, keeping every constant the SRS
specifies (0.75, 15%, 25%, 63 sessions, W=15):

1. The ATR contraction reference is the **peak ATR of the preceding quarter**,
   not "ATR at the start of the window".
2. The prior advance is measured **directionally** — price entering the
   consolidation versus the quarter's trough — not as the window's max over
   its min.

**Why change 1.** The literal test compares ATR today against ATR one window
ago. Once a base is a full window old that reference sits inside the quiet
period itself, the ratio drifts toward 1, and the condition extinguishes
itself. Measured across 142 RS≥70 symbols, the literal form never held for
more than **7 consecutive sessions**, which makes the Volatility Contraction
preset's `base_length_days >= 10` (FR-7.5) unsatisfiable. The screen returned
nothing, and always would have.

Anchoring the reference at the start of each tight-range episode was tried and
rejected: a steady advance is only ~8% deep over 15 sessions, so it already
counts as "tight", episodes begin during the rally rather than after it, and
the test degrades into "ATR is lower than it was a year ago". That produced
331-session "bases".

**Why change 2.** `max/min - 1` over the lookback is symmetric — it cannot
distinguish a rally from a crash. A stock that fell 25% and went quiet near
its low scored identically to one that rose 25% and paused near its high. On
real data this filled the base list with dead stocks: RS ratings of 1 to 53,
sitting at 1–45% of their 52-week range. This bug predates the amendment.

**Measured outcome.** Longest base observed across 475 symbols over five
years: 61 sessions, p90 episode length 17. Over the last 250 sessions the
`base_length_days >= 10` condition is met on 126 of them, median 2 symbols,
maximum 14. A screen for a genuinely rare setup that returns zero or one
candidate on a given day is behaving correctly; one that never returns
anything is broken.

---

## Open items still outstanding

| # | Item | Status |
|---|---|---|
| B-1 | Is vendor history split/bonus adjusted? | **Resolved** — see D-4 |
| B-2 | Corporate-action history source | Open. Yahoo covers splits and dividends; bonus/rights are not distinguished. |
| B-3 | Market-cap band source | Open. Not required for Phase 1 metrics. |
| B-4 | Confirm NSE URLs | **Verified 2026-08-26** — constituent list, UDiFF bhavcopy and MTO delivery file all live. |
| B-5 | NRI TDS mechanics and rates | Open. Defaults are configurable placeholders and must be confirmed with a cross-border CA before Phase 2 release. |
| B-6 | French declaration and foreign tax credit | Open. Not yet implemented. |
| B-7 | Portfolio value source for sizing | Open. Currently a manual input to the sizing endpoint. |
