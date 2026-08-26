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

**Intended resolution.** The SRS specifies APScheduler **in-process**
(§2.1), which resolves this: one process holds the connection and serves the
API. The CLI's separate-process pipeline is a development convenience and
should not run concurrently with a served API in production.

---

## D-7 — Backfill defaults to six years, not five

**Decision.** `alpha500 backfill` defaults to `--years 6`.

**Rationale.** FR-2.2 requires a minimum of 1 260 trading sessions and glosses
that as "≈5 calendar years". NSE trades roughly 247 days a year, so five
calendar years delivers about 1 236 sessions — just under the floor, and short
of acceptance criterion 1 ("≥ 1 260 sessions for ≥ 495 of 500 constituents").
Measured on the 2026-08-26 backfill: five years produced 1 236 index sessions
and no symbol reached 1 260.

Six years is the smallest whole number of years that clears the requirement.
The SRS's session count is the binding constraint; its calendar-year gloss is
approximate.

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
