# FR-18 — Sectoral and thematic index dashboard

Drafted 2026-09-07. Revised 2026-09-07 after review against the codebase,
then again the same day when B-10 was resolved against the live sources — 
see §7, which supersedes the sourcing assumptions in §1, FR-18.2 and FR-18.9.
Status: **Proposed**. Written to the §1 template of `URD.md`, taking the next
free ID from §2 (FR-18.x, FR-17 having been allocated).

This file is the full proposal and its reasoning. The condensed requirement
text lives in `URD.md` §6, per §1 step 2; §5 below lists every line that
changed on filing.

Source one-liners:

1. "graphical representation of each sectoral/thematic index — current range,
   ATH value, % decline from ATH, whether it's in uptrend or downtrend."
2. "suggest the metrics to trace index performance that are useful to take a
   momentum entry on that sector."

---

## 0. What the review changed

The first draft was checked against the store, the schema and the provider
package. Eight things did not survive contact:

| # | Claim in the first draft | What is actually true |
|---|---|---|
| 1 | Allocates `B-11` | `URD.md` §2 says next free is **B-10**. Allocating B-11 orphans B-10. |
| 2 | `index_ohlcv_daily` is new storage | It **already exists** (`schema.sql:164`), keyed `(index_name, trade_date)`, and is already read by the metric engine, the screens, the history materialiser and the API. |
| 3 | Index history to inception is "cheap" | Nothing in the tree served it: `YahooProvider._INDEX_SYMBOLS` mapped two tickers. *Partly overturned by §7* — Yahoo does serve OHLC for 18 indices, but none to inception. |
| 4 | 29 metrics | `drawdown_duration` and `sessions_since_ath` are the same number by construction. 28. |
| 5 | `top3_weight_pct` is a stored snapshot | Needs per-index membership and free-float weights, neither in the store. *Resolved by §7.5* — both are obtainable, and the weight is derived rather than published. |
| 6 | Breadth maps constituents "to that index's sector" | The `industry` label is not 1:1 with the sectoral indices. A mapping table is required and was not specified. |
| 7 | Winsorise at 1st/99th per FR-6.8 | Inert at n≈25: the 1st percentile of 25 points is the minimum. |
| 8 | §5 lists the URD edits | It omitted the §6 append, which `URD.md` §1 step 2 requires. |

Items 3 and 5 are sourcing gaps rather than drafting errors, and they are the
reason FR-18.2 and FR-18.9 below now carry explicit fallbacks instead of an
unstated assumption. Item 3 in particular would have reproduced the exact
mistake FR-15.2 exists to prevent: §1 of the URD cites it as the reason "the
period high is not called an all-time high", and a first draft that computes
`ath_value` from a series with no proven depth is that mistake with a new name.

The arithmetic in every worked example was checked and is correct.

---

## 1. What the one-liners leave unsaid

**"ATH" is not available from your store today, and may not be available at
all.** §5 of the URD starts at 2018-08-17. Most NSE sectoral indices have
history to 2005–2011. An "ATH" computed from 2018 would understate the
drawdown on any index that peaked earlier.

The first draft answered this by backfilling to inception and calling the
problem solved. That answer assumed a data source that did not exist. §7 went
and measured: the deepest series obtainable are Nifty Bank and Nifty IT at
2007-09-17, against launch dates of 2003 and earlier, and most other indices
start in 2011. **No index reaches inception, so nothing here is called an ATH.**
The requirement below names the metric after the depth actually achieved, which
is the FR-15.2 rule applied honestly rather than quoted.

**"Uptrend or downtrend" is a false binary.** Forcing two states means every
index chopping sideways around its 200 SMA receives a confident directional
label it has not earned, and the label is acted on. FR-18.4 defines three
states, with `TRANSITIONAL` as an honest answer rather than a hedge.

**An index in an uptrend is not the same as a sector in an uptrend.** Nifty
Bank is roughly half two constituents. An index can print a clean trend while
most of its members go nowhere. This is the single most common misreading of a
sector chart, and FR-18.5 (breadth) and FR-18.9 (concentration) exist to make
it visible rather than to be discovered after entry.

**The second one-liner asks the more valuable question.** Range, ATH and
drawdown describe where an index has been. Deciding whether to take a momentum
entry needs relative strength against the market, breadth, and persistence.
FR-18.6 to FR-18.9 are that set, and they, not the range chart, are what the
entry decision should rest on.

**What you can actually trade, given the account.** Delivery-based sector ETF
purchase is compatible with FR-12; index futures require a custodian and are
out of scope by construction. So the primary use of this view is as a filter
that narrows which stock screens to read, not as a signal to buy an index.
FR-18.10 makes that the built path.

---

## 2. Part one — range, drawdown, trend

**FR-18.1 — Index universe.** The system MUST track a defined set of
approximately 25 NSE indices — all sectoral indices, plus thematic indices
whose constituent base is materially distinct — and MUST store the set as a
versioned configuration list rather than deriving it at runtime.

Strategy and factor indices (Alpha, Quality, Low Volatility, Equal Weight)
MUST NOT be included. They measure a factor applied across sectors, not a
sector, and ranking them alongside sectoral indices invites a rotation
conclusion the data does not support.

Thematic indices that overlap another tracked index by more than a
configurable share of free-float weight (default 70%) MUST be flagged as
`OVERLAPS:<index>` in the view. Two near-identical indices ranking one and two
reads as a confirmed rotation when it is one move counted twice. Where
constituent weights are unavailable (FR-18.9), the overlap flag MUST be
derived from published membership overlap by count, and labelled as such.

The universe is **24 indices** as at 2026-09-07 — those whose NSE constituent
list resolves (§7.2). Nifty Capital Markets is deferred until its archive slug
is known. Each entry MUST carry a hand-maintained `documented_inception`, which
FR-18.2 reads; no automated source states it.

*Acceptance:* the configuration lists 24 ± 3 indices; every entry resolves to a
live NSE constituent list; no strategy or factor index appears; at least one
thematic carries an `OVERLAPS` flag against its sectoral parent.

*Status:* Proposed

---

**FR-18.2 — Index price history, to the greatest depth actually obtainable.**
The system MUST ingest a daily series for every tracked index, MUST record each
index's actual first available session alongside its series, and MUST NOT
describe any metric as all-time until that index's series demonstrably reaches
its documented inception.

Storage MUST extend the existing `index_ohlcv_daily` table rather than
introduce a second one. That table already holds the NIFTY 500 series and is
read by the metric engine, the screens, the history materialiser and the API,
all of which currently assume a single series; widening it to many indices is a
change to those consumers and MUST be treated as such.

Index ingestion MUST be a distinct pipeline stage from constituent ingestion,
and MUST NOT gate the stock pipeline: an index feed failure is a Warn, not a
Block (FR-4.1), because 500 stock rows remain correct without it.

**Ingestion is hybrid, and permanently so** (§7.1–7.3). Yahoo serves full OHLC
for 18 of the tracked indices; the four launched after 2020 have no Yahoo ticker
and fall back to the close-only `ind_close_all` this project already ingests.
NSE's own `indicesHistory` JSON endpoint is bot-blocked and unavailable, so
there is no third option. No new provider is required: `_INDEX_SYMBOLS` widens
from two entries to eighteen, plus a close-only path for the remainder.

The first draft's Tier A/B pair conflated two independent facts. They are
recorded separately per index, and both MUST be displayed:

- **`ohlc_basis`** (`OHLC` | `CLOSE`) — whether `high_52w` and `low_52w` use
  real highs and lows or are computed on close. Known automatically from which
  source served the index.
- **`reaches_inception`** — whether `first_session` is on or before the index's
  `documented_inception` from FR-18.1's config. This governs the peak's name:
  `ath_value` / `pct_from_ath` only where it holds, `period_high` /
  `pct_from_period_high` otherwise, with `first_session` shown beside it.

**No index currently qualifies**, so `ath_*` appears nowhere. That is FR-15.2's
rule arriving at its expected answer, not being argued around.

Two limits MUST be recorded with the series and surfaced wherever the peak is
shown:

- The tracked series is price return, not total return. For high-payout sectors
  a price-return peak understates the true peak, and a drawdown measured
  against it is correspondingly overstated. The UI MUST label the basis.
- Index reconstitution means a 2007 peak was set by a different basket from
  today's. The series is continuous; the thing it measures is not. The peak's
  date MUST be displayed beside its value so the operator can judge how
  comparable it is rather than treating a number from two cycles ago as
  equivalent.

*Acceptance:* every tracked index has a stored series with `first_session`,
`ohlc_basis` and `reaches_inception` recorded and displayed; no view, export or registry entry uses the string "all-time" for an index
whose `first_session` postdates its documented inception; a simulated index feed
failure produces a Warn and leaves the stock pipeline Built and current.

*Status:* Proposed — B-10 resolved (§7.6); tiers re-cut as `ohlc_basis` and
`reaches_inception`, and every index starts at `period_*` naming

---

**FR-18.3 — Range and drawdown metrics.** The system MUST compute, per index
and session:

```
high_52w             = max(High) over 252 sessions   # ohlc_basis CLOSE: max(Close)
low_52w              = min(Low)  over 252 sessions   # ohlc_basis CLOSE: min(Close)
range_position_52w   = (C_0 - low_52w) / (high_52w - low_52w)     # 0..1
pct_from_52w_high    = C_0 / high_52w - 1
peak_value           = max(High) over all stored sessions strictly before today
peak_date            = session on which peak_value was set
pct_from_peak        = C_0 / peak_value - 1
sessions_since_peak  = sessions elapsed since peak_date
```

`peak_value` / `pct_from_peak` are renamed `ath_*` only for an index whose
`reaches_inception` holds (FR-18.2). None does today, so the `ath_*` names
are not in use.

`pct_from_peak` is the number the one-liner asked for: how far below its own
best level the sector still trades. Read with `sessions_since_peak`, it
separates a sector 16% off a peak set last month from one 16% off a peak set in
2021 — the same number describing two different situations.

The current bar MUST be excluded from `peak_value`, per the FR-15.2 rule. Were
it included, an index making a new high today would read as 0% below its peak
and become indistinguishable from one still approaching it.

The first draft also specified `drawdown_duration` as "consecutive sessions
with `C_0 < peak_value`". That metric MUST NOT be added: because `peak_value`
is the running maximum excluding today, every session after `peak_date` is
below it by construction, so the count is identical to `sessions_since_peak` on
every row. Two names for one number invites the reading that they differ.

*Acceptance:* for `low_52w 40,000`, `high_52w 52,000`, `peak_value 55,000` and a
close of `46,000`: `range_position_52w = 0.500`, `pct_from_52w_high = -11.54%`,
`pct_from_peak = -16.36%`. Named test
`test_index_range_and_drawdown_worked_example`.

*Status:* Proposed

---

**FR-18.4 — Trend state, in three values not two.** The system MUST classify
each index into exactly one of three states:

```
UPTREND       C_0 > SMA200  AND SMA50 > SMA200  AND SMA200 rising over 21 sessions
DOWNTREND     C_0 < SMA200  AND SMA50 < SMA200  AND SMA200 falling over 21 sessions
TRANSITIONAL  anything else
```

The classification MUST NOT be reduced to a binary. An index oscillating around
a flat 200 SMA satisfies neither definition, and `TRANSITIONAL` is the accurate
answer; collapsing it into "uptrend" because price is a fraction above the line
manufactures conviction the data does not contain. Expect a material share of
the 25 to sit in `TRANSITIONAL` on any given session — that is the state
describing the market correctly, not the classifier failing.

`trend_state` MUST also carry `sessions_in_state`, so a sector three sessions
into an uptrend is distinguishable from one eleven months into it.

*Acceptance:* a synthetic series flat at its 200 SMA with a 200 SMA slope inside
±0.1% over 21 sessions classifies `TRANSITIONAL`, not `UPTREND`. On any live
session the three states sum to the tracked index count with no nulls. Named
test `test_trend_state_returns_transitional_when_neither_definition_holds`.

*Status:* Proposed

---

**FR-18.5 — Sector breadth from the existing store.** The system MUST compute,
per tracked sectoral index, breadth aggregated from NIFTY 500 constituents
mapped to that index:

```
breadth_above_50dma    = share of members with Close > SMA50
breadth_above_200dma   = share of members with Close > SMA200
breadth_at_52w_high    = share of members within 2% of their 52-week high
breadth_trend_template = share of members with trend_template_score >= 6
member_count           = members contributing to the calculation
```

The mapping from constituent to index MUST be a versioned configuration table,
on the same footing as FR-18.1's index list and for the same reason. It MUST
NOT be derived at runtime from `instruments.industry`: that label is not 1:1
with the sectoral indices — Financial Services alone feeds Nifty Bank, Nifty
PSU Bank, Nifty Private Bank and Nifty Financial Services — so a runtime
derivation silently assigns one member to the wrong index or to several.

Breadth is what separates a sector genuinely turning from an index dragged by
two heavyweight constituents. An index in `UPTREND` with `breadth_above_50dma`
below 40% is not a sector in an uptrend, and the view MUST show the two facts
adjacently so that reading one without the other takes deliberate effort.

The honest limit MUST be stated in the UI: breadth is derived from the NIFTY
500 universe, not from the index's published membership, so a sector index
holding names outside the 500 is measured on a subset. `member_count` MUST be
displayed per row, and any sector with fewer than 8 contributing members MUST
have its breadth suppressed rather than shown — a percentage over five names is
noise wearing a decimal point.

Thematic indices whose membership does not map cleanly to a sector label MUST
show breadth as unavailable rather than approximated.

*Acceptance:* a sector with 40 contributing members of which 26 close above
their 50 SMA reports `breadth_above_50dma = 65.0%` and `member_count = 40`. A
sector with 5 contributing members reports breadth suppressed, not a
percentage. Named test `test_breadth_suppressed_below_member_floor`.

*Status:* Proposed

---

## 3. Part two — metrics for a sector momentum entry

**FR-18.6 — Relative strength against the market.** The system MUST compute
each index's strength relative to NIFTY 500, and the trend of that strength:

```
rs_ratio_N     = (1 + index_ret_N) / (1 + nifty500_ret_N) - 1   for N in {21, 63, 126, 252}
rs_line        = index_close / nifty500_close                    (rebased to 100 at series start)
rs_line_sma50  = 50-session SMA of rs_line
rs_improving   = rs_line > rs_line_sma50
rs_new_high_63 = rs_line at a 63-session high
```

`rs_ratio_63` is the primary rotation metric: how much the sector out- or
under-performed the market over the last quarter, independent of whether the
market itself rose. A sector up 6% while the market rose 9% is a sector to
avoid, and absolute return alone will not tell you that.

`rs_new_high_63` MUST be computed on the ratio line, not on price. A sector
making a new relative high while its price is still below its own 52-week high
is the earliest reliable rotation signal in this metric set, and a price-based
filter cannot see it.

*Acceptance:* index 63-session return `0.18` against NIFTY 500 `0.06` gives
`rs_ratio_63 = 11.32%`. Named test `test_relative_strength_ratio`.

*Status:* Proposed

---

**FR-18.7 — Breadth thrust.** The system MUST flag the transition of
`breadth_above_50dma` from below a low threshold to above a high threshold
within a bounded window:

```
breadth_thrust = breadth_above_50dma crossed from < 30% to > 50%
                 within the last 10 sessions
```

Thresholds and window configurable. A thrust marks participation broadening
rapidly — many members reclaiming their 50 SMA together — which is what the
early phase of a sector rotation looks like from inside, and it typically fires
before the index itself satisfies FR-18.4's `UPTREND` definition.

The flag MUST record `breadth_thrust_date` and persist for 20 sessions, because
its value is that it fired recently, not that it is firing today.

*Acceptance:* a synthetic breadth series `28, 31, 38, 44, 52` over five sessions
sets the flag on the fifth and retains it for 20 sessions. Named test
`test_breadth_thrust_fires_on_crossing_not_on_level`.

*Status:* Proposed

---

**FR-18.8 — Sector momentum score.** The system MUST rank tracked indices by a
composite score reusing the existing engine's definitions rather than
introducing index-specific ones:

```
sector_momentum_score = 0.30 * z(momentum_score)        # (exp(b x 252) - 1) x R^2, on the index series
                      + 0.25 * z(rs_ratio_63)
                      + 0.20 * z(breadth_above_50dma)
                      + 0.15 * z(breadth_at_52w_high)
                      + 0.10 * z(rs_ratio_21)
```

Outliers MUST be clipped at ±3 standard deviations before weighting.
FR-6.8's 1st/99th percentile winsorisation MUST NOT be reused here: it was
written for a 500-symbol cross-section, and at n≈25 the 1st percentile is the
minimum, so the clip does nothing and the score inherits an unguarded tail.

Where breadth is suppressed (FR-18.5), its weight MUST be redistributed
proportionally across the remaining components rather than treated as zero —
zero would rank an unmeasurable sector as a weak one.

The peak-distance metric MUST carry zero weight. Distance from an old peak
describes history, not current momentum, and a sector 40% off a 2021 high can
be the strongest thing in the market today.

*Acceptance:* the score is computed for all tracked indices with no nulls; a
sector with breadth suppressed receives a score from redistributed weights and
is marked as such; a synthetic component at 8 standard deviations moves the
score no further than one at 3. Named tests
`test_sector_score_redistributes_suppressed_breadth_weight` and
`test_sector_score_clips_outliers_at_three_sigma`.

*Status:* Proposed

---

**FR-18.9 — Concentration, dispersion and persistence.** The system MUST expose
three metrics that qualify the momentum score rather than feed it:

```
top3_weight_pct        = combined free-float weight of the three largest members
constituent_dispersion = standard deviation of member 63-session returns
leadership_persistence = consecutive sessions in the top 5 by sector_momentum_score
```

Each answers a question the score cannot:

- `top3_weight_pct` — whether the index is a sector or a handful of stocks.
  Above a configurable 45%, the row MUST carry a concentration badge. A trend
  on a 55%-concentrated index is a view on two companies.
- `constituent_dispersion` — whether the move is broad or a few names. Low
  dispersion with a high score is a sector move; high dispersion is a
  stock-picking situation inside a sector, and the sector view is the wrong
  tool for it.
- `leadership_persistence` — how long the sector has already led. This is the
  metric most likely to be ignored and most likely to matter: entering a sector
  in its fortieth session of leadership is a different trade from entering in
  its fifth, at the same score. The view MUST show it beside the rank.

`top3_weight_pct` is **derived, not published** (§7.5). NSE's constituent lists
carry no weight column, so weight is `floatShares × price` normalised across the
index's members — membership from the NSE list, float from the same Yahoo field
`sync_float_shares` already uses, price from the bhavcopy this project ingests
for every NSE symbol.

It MUST be labelled `DERIVED` and MUST NOT be presented as the published weight.
On Nifty Bank the derived top three reads 69.2% against a published 60–63%:
uncapped derivation always overstates concentration on a capped index, because
NSE's single-stock cap and investable weight factors are not applied. That error
is one-directional, so it is safe for a warning badge — it warns early rather
than late — and unsafe for anything precise, which is why FR-18.1's 70% overlap
test uses membership overlap by count instead.

Where a member's float figure is missing, the metric MUST report unavailable
rather than normalise over a partial basket. It MUST NOT be computed over only
the members that happen to be in the NIFTY 500: that would understate
concentration precisely on the indices most likely to be concentrated.

These MUST NOT be folded into `sector_momentum_score`. Their purpose is to make
a high score interpretable, and a score that has already absorbed them cannot
be interrogated.

*Acceptance:* an index whose three largest members weigh 28%, 14% and 9%
reports `top3_weight_pct = 51%` and carries the concentration badge; an index
with no stored membership reports it unavailable and carries no badge. Named
test `test_concentration_badge_fires_above_threshold`.

*Status:* Proposed — unblocked by B-10 (§7.5). `top3_weight_pct` is derived
from free-float market cap, labelled `DERIVED`, and overstates concentration
on capped indices by roughly 7 points — one-directional, and safe for a
warning badge.

---

**FR-18.10 — The sector view, and what it hands off to.** A view MUST present
one row per tracked index as a horizontal range bar, sorted by `trend_state`
then `sector_momentum_score` descending, and each row MUST link through to the
stock screens filtered to that sector.

Each row's chart MUST show:

- a track spanning `low_52w` to `max(high_52w, peak_value)` — the track must
  extend to the peak when the peak sits above the 52-week high, or the peak
  marker falls outside the drawn range and silently disappears on exactly the
  indices furthest from their peak
- markers for current close, `low_52w`, `high_52w` and `peak_value`
- the drawdown from `peak_value` to current close as a shaded span
- `trend_state` indicated by glyph or label as well as colour (NFR-6.3)

Accompanying numeric columns MUST include, at minimum: `pct_from_peak`,
`peak_date`, `range_position_52w`, `trend_state`, `sessions_in_state`,
`rs_ratio_63`, `breadth_above_50dma`, `member_count`, `leadership_persistence`
and `top3_weight_pct`.

The view MUST NOT present a buy signal on an index. Index futures require a
custodian and are out of scope under FR-12; the supported expressions are a
delivery-based sector ETF or, more usefully, narrowing which stock screens to
read. Each row MUST therefore offer a one-click hand-off that applies the
sector as a filter to the existing screens — this is the built path from "which
sector" to "which stock", and without it the view is a wall-chart rather than a
tool.

*Acceptance:* an index whose peak exceeds its 52-week high renders with the peak
marker inside the drawn track; the sector hand-off applies a sector filter to
Momentum Leaders and returns only constituents of that sector; the view sorts
`UPTREND` rows above `TRANSITIONAL` above `DOWNTREND`. Live figure recorded on
first run: on 2026-09-07, 5 indices are UPTREND, 9 TRANSITIONAL and 4 DOWNTREND,
of the 18 measurable.

*Status:* Proposed

---

**FR-18.11 — Sector rotation is not sector timing.** The view, the metric
registry and the operator manual MUST each state that these metrics identify
where strength currently sits, not where it will sit next.

The product MUST NOT rank sectors by forecast, projected return, or any label
implying a prediction. Neutral naming — "current leadership", "relative
strength" — is required, and the same restraint FR-17.9 applies to Fibonacci
levels applies here.

`leadership_persistence` MUST be displayed on any view that ranks sectors, not
held behind a toggle. A ranking that shows only the score presents a sector in
its fortieth week of leadership identically to one in its second, and the
ranking's most common misuse is to buy the first believing it is the second.

*Acceptance:* the sector ranking view exposes `leadership_persistence` by
default; a full-text search of the frontend bundle, registry and manual returns
zero occurrences of "forecast", "projected" or "predicted" applied to a sector.

*Status:* Proposed

---

## 4. New metrics and storage

**Index series.** `index_ohlcv_daily` **already exists** (`schema.sql:164`),
keyed `(index_name, trade_date)` and currently holding the NIFTY 500 series
alone. FR-18.2 widens it to many series. Its existing readers —
`metrics/engine.py`, `metrics/history.py`, `screens/presets.py`,
`db/store.py`, `api/main.py` — all assume one series today and MUST be audited
as part of that change.

**New table.** `indices`, holding code, display name, category (`SECTORAL` |
`THEMATIC`), `first_session`, `documented_inception`, `ohlc_basis`
(`OHLC` | `CLOSE`) and `reaches_inception` (per FR-18.2),
`return_basis` (`PRICE`), and overlap flags.

**New table.** `index_sector_map`, the versioned constituent-to-index mapping
FR-18.5 requires. Not derived from `instruments.industry` at runtime.

**Derived, not stored raw.** `top3_weight_pct` is computed from index
membership, Yahoo float shares and bhavcopy prices (§7.5), and stored with a
`DERIVED` marker. The published weights it approximates are not obtainable.

**28 new index-level metrics:** `high_52w`, `low_52w`, `range_position_52w`,
`pct_from_52w_high`, `peak_value`, `peak_date`, `pct_from_peak`,
`sessions_since_peak`, `trend_state`, `sessions_in_state`,
`breadth_above_50dma`, `breadth_above_200dma`, `breadth_at_52w_high`,
`breadth_trend_template`, `member_count`, `breadth_thrust`,
`breadth_thrust_date`, `rs_ratio_21`, `rs_ratio_63`, `rs_ratio_126`,
`rs_ratio_252`, `rs_line`, `rs_improving`, `rs_new_high_63`,
`sector_momentum_score`, `top3_weight_pct`, `constituent_dispersion`,
`leadership_persistence`.

(`drawdown_duration` was dropped — see FR-18.3.)

`trend_state`, `peak_date`, `breadth_thrust_date`, `ohlc_basis` and the
overlap flag are string- or date-valued and MUST route through the text
formatter, not the numeric one — the FR-15.1 `NaN` failure.

**Cost.** ~25 series against 500 symbols is immaterial for daily incremental
ingestion under NFR-1.8's 15-minute budget (currently 7 min 16 s), and index
metrics plus a grouped breadth aggregation over the existing 500-stock frame are
well inside NFR-1.7's headroom (currently ~27 s of 60 s). No new NFR is
proposed. Any inception backfill is a one-off command, not a pipeline stage —
but its cost cannot be estimated until B-10 settles what the source is.

---

## 5. URD edits applied on filing

§2, the FR allocation table — replace the `Next free` row with:

```markdown
| FR-18.x | Sectoral and thematic indices | This document, §6 | In use |
| **FR-19.x** | — | — | **Next free** |
```

§2, supporting-series paragraph — `D-11` and `B-10`/`B-11` are consumed below,
so the ranges and the next-free line both move:

```markdown
(architecture), `D-1` to `D-11` (decisions, in `DECISIONS.md`), `B-1` to `B-11`
...
Next free: **NFR-7**, **D-12**, **B-12**.
```

§6 — append the condensed FR-18.1–18.11 text, per §1 step 2. The first draft's
edit list omitted this; without it the §2 row's "This document, §6" reference
dangles.

§9, append above the marker comment:

```markdown
| 2026-09-07 | Sector/thematic index dashboard: range and drawdown, three-state trend, breadth, rotation metrics | FR-18.1–18.11 |
```

Applied 2026-09-07 when FR-18.1-18.4 were built: §3's capability table gained
rows for the index series and the sector view (both Partial), its API and screen
counts were refreshed, and its metric count was corrected to the 101 the registry
actually serves - FR-18's index metrics sit outside the registry and are not
counted there. §5 gained a second data-foundation table, because index history
is deeper than the stock history, has a different basis, and reaches no
inception; "the data foundation" is now two foundations and a requirement
spanning both has to say which it means.

---

## 6. Decision and open questions

**D-11 — Index history depth is set by what a source can serve, not by a
target.** Indices are ~25 series against 500 symbols, so depth would cost
almost nothing *if a source existed*. None does (B-10). Rather than specify a
depth the system cannot reach and name metrics after it, FR-18.2 records the
depth achieved per index and names the peak metric accordingly — `ath_*` only
where inception is genuinely reached, `period_*` otherwise. This is FR-15.2's
rule, and the asymmetry with stock history is deliberate and should not be read
as a decision to deepen the stock backfill, which remains governed by D-9.

*State:* Proposed

**B-10 — What index history can actually be obtained, and at what depth?**
Blocking for FR-18.2 and for `top3_weight_pct` in FR-18.9. Three things need
establishing: which of the ~25 tracked indices Yahoo serves and how far back;
whether NSE publishes a sectoral index OHLC archive rather than the close-only
`ind_close_all` already ingested; and whether per-index constituent membership
with free-float weights is obtainable at all. The answer decides how
FR-18.2 sources each index, and whether FR-18.9's concentration badge can
exist. Until then, no metric may be labelled all-time.

*State:* **Resolved 2026-09-07** — see §7.

**B-11 — Does sector selection improve the stock screens, or just add a step?**
The premise of FR-18 is that filtering stock screens by leading sectors improves
results. That is an assumption, not a finding, and it is testable: run the
existing screens over the eight-year window unfiltered, then filtered to the top
5 sectors by `sector_momentum_score` as at each entry date, on the point-in-time
universe, net of the FR-12.5 cost model including TDS. Compare CAGR, maximum
drawdown, hit rate and, specifically, trade count — a sector filter that
improves hit rate while cutting opportunities in half may not improve the
portfolio.

§7's caution applies: only figures from the revised `docs/backtest-findings.md`
should be quoted, and every result there is survivorship-biased upward.

There is a plausible negative result worth naming in advance. Momentum screens
already cluster by sector without being told to — a top-20 momentum list in a
hot sector is frequently one bet expressed twenty ways. If that clustering is
already doing the work, an explicit sector filter adds a step and a false sense
of process without adding return. If so, keep the view as context and drop the
hand-off filter, rather than tuning the score.

*State:* Open

---

## 7. B-10 resolved — what index history can actually be obtained

Probed 2026-09-07 against the live sources, from `NseSession` and `yfinance`.
Every figure below is measured, not assumed.

### 7.1 NSE programmatic index history — not available

`GET /api/historical/indicesHistory?indexType=NIFTY%20BANK&...` returns **HTTP
200 with an HTML interstitial** carrying `<meta name="robots"
content="noindex, nofollow">`, not JSON. `GET /api/equity-stockIndices` returns
**404**. NSE's JSON endpoints for index history and live index composition are
not reachable from a programmatic client, and defeating that block is not a
supported approach. Treat both as unavailable.

What *is* reachable on the archive host is what the project already uses:
`ind_close_all_DDMMYYYY.csv`, **close only, no OHLC**, ~165 indices per session.

### 7.2 NSE constituent lists — available, 24 of 25

Every list carries the same header as the NIFTY 500 list — `Company Name,
Industry, Symbol, Series, ISIN Code` — so `list_instruments`' existing parser
and its `_require_columns` guard work unchanged. **No list carries a weight
column.**

Two slugs differ from the obvious pattern and cost a request each to find:
`ind_niftyindiadefence_list.csv` and `ind_niftyindiamanufacturing_list.csv`
(underscore before `list`). Nifty Capital Markets did not resolve against any
candidate slug tried and is dropped from the initial universe.

### 7.3 Yahoo index OHLC — 18 of 22, depth 2007–2016

| Depth | Indices |
|---|---|
| 2007-09-17 | Nifty Bank (`^NSEBANK`), Nifty IT (`^CNXIT`) |
| 2010-07-19 | Nifty Realty (`^CNXREALTY`), Nifty Infra (`^CNXINFRA`) |
| 2011-01-31 | Pharma, FMCG, Energy, PSU Bank, PSE, MNC, Services |
| 2011-07-12 | Auto, Metal, Consumption |
| 2011-08-04 | Media |
| 2011-09-07 | Financial Services, Commodities |
| 2016-03-14 | Nifty Private Bank |

All 18 return full OHLC. **Four have no resolvable Yahoo ticker**: Healthcare,
Consumer Durables, Oil & Gas, India Defence — all launched 2020 or later.

**No index is proven to reach its inception.** Nifty Bank launched in 2003 and
Nifty IT earlier still, yet both start at 2007 here. The 2011 cluster is close
to the launch date for several of those indices, but "close to" is not a fact
this system can check, and asserting launch dates from memory is the error this
document exists to avoid.

### 7.4 Breadth coverage — much better than the caveat implied

Members of each index that are also in the NIFTY 500, measured today:

- **21 of 24 indices: 100% coverage.** Bank, IT, Auto, Pharma, FMCG, Metal,
  Realty, Energy, Infra, Private Bank, Financial Services, Healthcare, Consumer
  Durables, Oil & Gas, Commodities, Consumption, CPSE, PSE, MNC, Services,
  Manufacturing (76 members, all inside).
- Nifty PSU Bank: 11 of 12.
- Nifty India Defence: 11 of 19.
- **Nifty Media: 5 of 10** — the only index that falls below FR-18.5's
  eight-member floor and would have its breadth suppressed.

FR-18.5's "measured on a subset" limit is real but narrow. It should still be
stated, and `member_count` still shown, but it disqualifies exactly one index.

### 7.5 Free-float weights — derivable, with a known and one-sided error

Yahoo's `floatShares` resolved for **14 of 14** Nifty Bank members. Deriving
weight as `floatShares × price`, normalised:

```
HDFCBANK  29.94%   ICICIBANK 27.88%   SBIN 11.34%   AXISBANK 9.81%
KOTAKBANK  8.53%   PNB        3.69%   ... 14 members, none missing
derived top3_weight_pct = 69.2%
```

Published Nifty Bank weights put the top three nearer 60–63%. The derived
figure **overstates by roughly 7 percentage points**, because NSE applies a
single-stock cap and its own investable weight factors and this calculation
applies neither.

That error is systematic and one-directional: uncapped derivation always
overstates concentration on a capped index. For a *risk badge* that is the safe
direction — it warns early rather than late — so `top3_weight_pct` is usable at
FR-18.9's 45% threshold provided it is labelled `DERIVED` and never presented
as the published weight. It must not be used anywhere a precise weight matters,
which includes FR-18.1's 70% overlap test; that test falls back to membership
overlap by count.

### 7.6 Resolution

**B-10 is resolved.** The answers change three requirements:

1. **FR-18.2's tiers are re-cut.** The original Tier A/B pair conflated two
   independent facts. They are now recorded separately per index:
   - `ohlc_basis` — `OHLC` where Yahoo serves the index (18), `CLOSE` where only
     `ind_close_all` does (4+). This decides whether `high_52w` / `low_52w` use
     real highs and lows or are computed on close. It is automatable and known.
   - `reaches_inception` — whether `first_session` is on or before the index's
     documented inception, which is a **hand-maintained field in FR-18.1's
     config**, because no automated source states it. Until it is filled for an
     index, that index is treated as not reaching inception.

   Since nothing currently proves inception for any index, **every index starts
   at `period_*` naming and `ath_*` appears nowhere**. That is the FR-15.2 rule
   arriving at its expected answer rather than being argued around.

2. **Ingestion is hybrid, and that is a permanent shape, not a stopgap.** Yahoo
   supplies OHLC for the 18; the already-ingested `ind_close_all` supplies close
   for the rest. Both already exist in the provider package, so FR-18.2 needs no
   new provider — it needs `_INDEX_SYMBOLS` widened from two entries to
   eighteen, and a close-only path for the remainder.

3. **FR-18.9's concentration badge is buildable now**, from derived weights,
   labelled `DERIVED`, with the one-directional error stated in the UI. It is no
   longer blocked.

The universe (FR-18.1) is therefore **24 indices**, not 25 ± 3: the 24 whose
constituent lists resolve. Capital Markets is deferred until its slug is known.
