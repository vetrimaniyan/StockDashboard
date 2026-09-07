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

> **Superseded in part by D-9 (2026-08-27).** The depth decision below no
> longer describes this deployment: it runs on **eight years**, 1 985 sessions
> from 2018-08-17. The `--years 5` CLI default is unchanged, so a plain
> `backfill` still fetches five — pass `--years 8`. The closing advice to
> "pass `--years 6` when Phase 3 begins" is obsolete; six was never run and
> eight superseded it.
>
> The waiver of acceptance criterion 1 **stands**, but not for the reason
> given here. D-9 found the 1 260-session floor structurally unachievable at
> any depth, because a current-constituent universe always contains recent
> IPOs. The reasoning below — that the shortfall is an artefact of NSE trading
> 247 days a year — is true but incidental.

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

## D-9 — Five years was too short; history extended to eight

> **Resolved 2026-08-27.** This deployment runs on eight years, 1 985 sessions
> from 2018-08-17. The heading previously stated only the problem, which read
> as though five years were still the operating depth. Supersedes D-7 on
> depth; see the Actioned block below for the measured effect.

**Context.** D-7 waived the 1 260-session floor and kept the backfill at five
years. Phase 3 has now made the cost of that visible: eligibility needs 252
sessions of history, so with data starting 2021-08-16 the first session
carrying any eligible stock is **2022-08-19**. Backtests over the nominal
five-year range trade nothing for their first year, and the February–July 2022
correction — the only proper bear phase in the window — cannot be tested at all.

**Consequence.** Every regime conclusion in `docs/backtest-findings.md` rests
on two corrections rather than three, and neither is a full bear market. That
is thin evidence on which to judge a screen designed for corrective regimes.

**Actioned 2026-08-27.** `alpha500 backfill --years 8` ran in 518.7s and the
re-materialise in 566.2s, giving 1,984 sessions and 841,019 metric rows from
2018-08-17. The first eligible session moved from 2022-08-19 to 2019-08-30, and
testable corrections went from two to six — including the 2020 COVID crash at
−38.3%, the deepest drawdown in the record.

It was worth the 18 minutes. The same screen, unchanged, moved from 2.43% to
14.46% net CAGR: the five-year window had been too short and started at an
unrepresentative point, and the earlier conclusion drawn from it was wrong.
See `docs/backtest-findings.md`.

**Follow-on finding.** Acceptance criterion 1 is structurally unachievable, not
merely unmet. 398 of 500 symbols now carry ≥1 260 sessions; the 102 that do not
are genuine recent listings (ICICIAMC 2025-12-19, MEESHO 2025-12-10, PINELABS
2025-11-14 and others). A current-constituent universe necessarily contains
recent IPOs, so no backfill depth satisfies it. The SRS's own clause — "with
the shortfall symbols named and explained" — is the resolution, and this is
that explanation. D-7's waiver stands, for a better reason than the one it
originally gave.

---

## D-10 — B-9 resolved: the support kernels were the cost, not the data volume

**Context.** NFR-1.7 budgets 60 s for a full metric recompute. It was measured
at ~116 s on 2026-08-31, against 42.4 s recorded when the store held five years
and 562k rows. The obvious reading — eight years of history is simply more work
— was wrong, and profiling rather than assuming is what showed it.

**Finding.** `_support_and_reversal` accounted for 38.9 s of 58.7 s. Two FR-14
kernels were Python loops over every bar:

* `swing_lows` allocated a fresh array per bar via `np.delete`, called **838 519
  times** — once per price row in the store.
* `nearest_support` scanned back 63 bars for every bar, ~62 M inner iterations
  across the universe.

Both are pure sliding-window problems that numpy expresses directly.

**Decision.** Vectorise both with `sliding_window_view`. Rejected alternatives:

* *Load less history.* Would have worked for most metrics — nothing needs more
  than 252 sessions except `history_days` and `high_period` — but it trades a
  real correctness surface for speed that was not the bottleneck anyway.
* *Vectorise `_recursive_smooth` too.* It is now ~60% of the remaining 24 s, but
  Wilder smoothing is a sequential first-order recurrence. Doing it exactly needs
  `scipy.signal.lfilter`, and scipy is not a dependency. Adding one to reclaim
  time already inside budget is a poor trade.

**Result.** ~116 s to **~24 s**, against a 60 s budget. Output is bit-identical:
both kernels were differential-tested against verbatim copies of the previous
implementations across all 500 symbols and seven synthetic edge cases (flat
runs, embedded NaNs, series shorter than the window). The 172-test suite passes,
and the Pullback + Reversal, Pullback to Support and Approaching High screens
return the same names in the same order.

**What this says about the earlier number.** 42.4 s was never a healthy figure
for this code — the FR-14 kernels landed after it was taken, and their cost grew
linearly with a store that then grew 50%. The budget caught a design problem
that a faster machine would only have hidden.

---

## D-11 — Index history depth is set by what a source can serve, not by a target

**Context.** FR-18 wants each sectoral and thematic index shown against its
all-time high. The first draft proposed backfilling ~25 index series to
inception and called the cost immaterial — true of the storage, and beside the
point. Nothing in the provider package can serve it. `YahooProvider` maps two
index tickers (`^CRSLDX`, `^NSEI`); the NSE archive file already ingested into
`index_valuation_daily` covers ~165 indices but carries close only, no OHLC, and
this store holds it from 2016.

**Decision.** Depth is recorded per index rather than assumed, and the peak
metric is named after the depth actually achieved: `ath_value` / `pct_from_ath`
only where an index's series demonstrably reaches its documented inception,
`period_high` / `pct_from_period_high` otherwise, with `first_session` shown
beside it.

**What the probe returned (B-10, 2026-09-07).** No index reaches inception from
any available source. The deepest series obtainable are Nifty Bank and Nifty IT
at 2007-09-17, against launch dates of 2003 and earlier; most others start in
2011 and Private Bank in 2016. So the rule resolves, for now, to `period_*`
everywhere and `ath_*` nowhere. Inception dates are a hand-maintained config
field rather than a derived one, because no source this system can reach states
them, and asserting them from memory is the failure this decision exists to
prevent.

FR-18.2 separately records `ohlc_basis` (`OHLC` for the 18 indices Yahoo serves,
`CLOSE` for the rest), which is an independent fact from depth and decides only
whether high/low metrics use real highs and lows.

**Why this and not a target depth.** `docs/URD.md` section 1 cites FR-15.2 as
the reason "the period high is not called an all-time high" for stocks.
Computing `ath_value` for an index from a series starting in 2016 and labelling
it all-time is that same error with a new name, and it fails in the same
direction: an index that peaked in 2007 reads as near its high when it is far
below it. Naming the metric after the data is the rule the document already
applies, and the one it would break here.

The asymmetry with stock history is deliberate and should not be read as a
decision to deepen the stock backfill, which remains governed by D-9.

**State.** Proposed. Sourcing is B-10.

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
| B-8 | Records stated five years of history; the store holds eight | **Resolved 2026-08-31** — README and D-7 corrected, D-9 heading now names its resolution. Detail in `docs/URD.md` §8. |
| B-9 | NFR-1.7 recompute breaching at ~116 s against a 60 s budget | **Resolved 2026-08-31** — see D-10. Two FR-14 support kernels were per-bar Python loops; vectorised to ~24 s with bit-identical output. |
| B-10 | What index history can actually be obtained, and at what depth? | **Resolved 2026-09-07** — probed against the live sources; findings in `docs/FR-18-sectoral-index-dashboard.md` §7. NSE's `indicesHistory` and `equity-stockIndices` JSON endpoints are bot-blocked and unavailable. Yahoo serves full OHLC for 18 of 22 sectoral/thematic indices, deepest 2007-09-17 (Bank, IT), most 2011, Private Bank 2016; the four launched after 2020 have no ticker and fall back to the close-only `ind_close_all` already ingested. 24 of 25 NSE constituent lists resolve, on the same schema as the NIFTY 500 list and with no weight column. **No index reaches inception**, so `ath_*` naming is withdrawn and every index reports `period_*` — see D-11. Free-float weights are derivable from `floatShares × price` but overstate concentration on capped indices by ~7 points (Nifty Bank top-3: 69.2% derived vs 60-63% published). |
| B-11 | Does sector selection improve the stock screens, or just add a step? | Open. The premise of FR-18, and an assumption rather than a finding. Testable: run the existing screens over the eight-year window unfiltered, then filtered to the top 5 sectors by `sector_momentum_score` as at each entry date, on the point-in-time universe, net of the FR-12.5 cost model including TDS. Compare CAGR, max drawdown, hit rate and trade count — a filter that improves hit rate while halving opportunities may not improve the portfolio. Plausible negative result worth naming now: momentum screens already cluster by sector unprompted, so an explicit filter may add process without adding return. If so, keep the view as context and drop the hand-off rather than tuning the score. |
