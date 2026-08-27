# SRS Addendum — Screener Enhancements

Extends "NSE Momentum & Swing-Trading Dashboard (Project Alpha-500)" v1.0.
Notation follows the parent SRS: `C_0` is the adjusted close of the latest
session, `C_N` the adjusted close N sessions before it. Periods are trading
sessions, never calendar days (FR-6.1).

## Decisions

| # | Decision | Resolution | Why |
|---|---|---|---|
| 1 | Meaning of "2 to 3-month return" | Both readings implemented as **separate, named** metrics: `ret_2m` (a point lookback) and `ret_3m_2m` (the lagged window) | They answer different questions and conflating them silently would pick one for the operator. `ret_2m` completes the 1m/2m/3m ladder so `between` filters work; `ret_3m_2m` measures the return earned *during* the window three-to-two months ago, which is what the phrase says literally. |
| 2 | Session counts | 2w = 10, 3w = 15, 2m = 42 | Multiples of the existing WEEK=5 and MONTH=21 constants. |
| 3 | Price basis | Adjusted close throughout | FR-3.3: adjusted for splits and bonuses, never for ordinary cash dividends (FR-3.4). Identical to every existing return. |
| 4 | Support level | Nearest **swing low** at or below price, from a 7-bar fractal over the last 63 sessions; `sma_50` and `ema_21` are additional candidates | A swing low is where buyers previously appeared, which is what "support" means operationally. Moving averages are included because they are the levels this operator's other screens already reference (FR-6.15). |
| 5 | Reversal signal | Five independent binary checks, scored 0–5; **≥ 2 required** | A single indicator turning up is noise at this frequency. Requiring agreement across independent families (momentum, trend, price action, participation) is the same logic that makes `momentum_score` multiply slope by R². |
| 6 | Ordering of the top 10 | Lexicographic: `reversal_score` desc → `rs_rating` desc → `support_distance_pct` asc → `instrument_token` asc | Deterministic including ties (AR-4), and explainable in one line in the UI. A weighted composite would need cross-sectional z-scores and would hide which factor drove a given rank. |
| 7 | Relation to FR-6.15 | **Added beside** `is_pullback`, not replacing it | They are different setups: FR-6.15 is a *continuation* filter requiring a perfect 8/8 trend template and a neutral RSI, with no reversal confirmation at all. This is a *timing* signal requiring an identified support level and active evidence that the pullback has stopped. A stock can satisfy either without the other. |
| 8 | Eligibility | Inherits all existing exclusions unchanged | FR-1.5 (series, ASM/GSM/T2T/suspended, <252 sessions) and FR-1.6 (₹5 crore 20-day median turnover floor). |

---

## Section A — Additional return filters

**FR-13.1 — New return metrics.** The system MUST compute and store:

```
ret_2w     = C_0  / C_10 - 1
ret_3w     = C_0  / C_15 - 1
ret_2m     = C_0  / C_42 - 1
ret_3m_2m  = C_42 / C_63 - 1
```

*Acceptance:* for a series rising exactly 1% per session, `ret_2w` = 1.01¹⁰−1 =
0.104622, `ret_3w` = 1.01¹⁵−1 = 0.160969, `ret_2m` = 1.01⁴²−1 = 0.518790, and
`ret_3m_2m` = 1.01²¹−1 = 0.232392. Each MUST match to 1e-12.

**FR-13.2 — Null on insufficient history.** Each metric MUST be null where the
symbol has fewer sessions than the window requires — never zero, never
partially computed (FR-6.1).

*Acceptance:* a symbol with 12 sessions has a non-null `ret_2w` and a null
`ret_3w`, `ret_2m` and `ret_3m_2m`.

**FR-13.3 — Screener availability.** All four MUST be filterable with the full
operator set (FR-7.2) and MUST appear in the results grid, the metric glossary
on export (FR-9.3) and the hover formula affordance (FR-8.10), **without any
change to the API layer or the grid component** (NFR-3.2).

*Acceptance:* a screen filtering `ret_2w >= 0.05 AND ret_3m_2m <= 0` returns
rows, and the exported `.xlsx` glossary sheet contains all four formulas.

**FR-13.4 — Range filtering.** The operator MUST be able to express a
"2-to-3-month" band as `ret_2m` and `ret_3m` conditions combined with `AND`.
The UI MUST NOT present `ret_2m`/`ret_3m` and `ret_3m_2m` as interchangeable;
the glossary text MUST state that one is a lookback to a point and the other is
the return earned across an interval.

---

## Section B — Pullback and reversal

**FR-14.1 — Swing low.** Session `t` is a swing low when its adjusted `Low` is
the strict minimum of the 7-session window centred on it (three sessions each
side). The three most recent sessions can never qualify, since their right-hand
window is incomplete — this is deliberate and prevents a low being confirmed
before the market has confirmed it.

**FR-14.2 — Support level.** `support_level` is the **highest** candidate at or
below `C_0`, where candidates are every swing low (FR-14.1) in the last 63
sessions plus `sma_50` and `ema_21`. Null when no candidate sits at or below
`C_0` — a stock at a new high has no support beneath it by this definition and
MUST be excluded rather than assigned one.

```
support_distance_pct = C_0 / support_level - 1        # >= 0
is_at_support        = support_distance_pct <= 0.03   # configurable
```

**FR-14.3 — Pullback.** Measured against the recent high, so a stock that never
rose is not treated as having pulled back:

```
pullback_from_high_pct = C_0 / max(High over last 21 sessions) - 1   # <= 0
```

A pullback qualifies when it is between **3% and 25%** — shallower is noise,
deeper is a broken trend rather than a pullback. Both bounds configurable.

**FR-14.4 — Reversal score.** Five independent checks, each contributing 1:

| # | Check | Rule |
|---|---|---|
| R1 | Momentum turning | `rsi_14` today > yesterday, **and** `rsi_14` ≤ 45 at some point in the last 5 sessions |
| R2 | MACD improving | `macd_hist` today > yesterday **and** yesterday > the day before |
| R3 | Reclaiming trend | `C_0 > ema_21` and `C_1 ≤ ema_21` one session ago |
| R4 | Reversal bar | `C_0 > O_0` and the close sits in the top third of the session range: `(C_0 − L_0) / (H_0 − L_0) ≥ 0.66` |
| R5 | Participation | `C_0 > C_1` and `rel_volume ≥ 1.2` |

```
reversal_score = R1 + R2 + R3 + R4 + R5          # 0..5
is_reversal    = reversal_score >= 2             # configurable
```

The partial score MUST be displayed, not just the flag — the same reasoning as
FR-6.12's 0–8 trend template, where a stock one criterion short is an
actionable watchlist item that a binary flag hides.

**FR-14.5 — Combined signal.**

```
is_pullback_reversal = is_eligible
                       AND is_at_support
                       AND pullback qualifies (FR-14.3)
                       AND is_reversal
                       AND C_0 > sma_200        # long-only, uptrend intact
```

The `sma_200` condition keeps this a pullback within an uptrend rather than a
bounce in a downtrend, consistent with the long-only constraint (FR-12.2).

**FR-14.6 — Top 10 section.** The dashboard MUST show a dedicated section
listing the top 10 by:

```
ORDER BY reversal_score DESC,
         rs_rating DESC,
         support_distance_pct ASC,
         instrument_token ASC      -- deterministic tie-break (AR-4)
```

Each row MUST show the support level, the distance to it, the pullback depth,
the reversal score with its component breakdown, and `rs_rating`. Fewer than 10
matches MUST render as however many exist with a plain statement of the count —
never padded with lower-quality rows.

*Acceptance:* running the section twice against the same stored data returns
byte-identical rows in identical order.

**FR-14.7 — Distinct from FR-6.15.** The UI MUST label this section and the
"Pullback to Support" preset so they cannot be confused, stating that the
preset finds continuation setups inside a perfect trend template while this
section finds pullbacks to support with active reversal confirmation.

**FR-14.8 — No implied intraday round trip.** Signals are computed from a
session's close and are actionable at the next session's open at the earliest,
consistent with FR-12.1 (delivery-based only; no intraday, no BTST).

---

## Schema delta

```sql
ALTER TABLE metrics_daily ADD COLUMN ret_2w                 DOUBLE;
ALTER TABLE metrics_daily ADD COLUMN ret_3w                 DOUBLE;
ALTER TABLE metrics_daily ADD COLUMN ret_2m                 DOUBLE;
ALTER TABLE metrics_daily ADD COLUMN ret_3m_2m              DOUBLE;
ALTER TABLE metrics_daily ADD COLUMN support_level          DOUBLE;
ALTER TABLE metrics_daily ADD COLUMN support_distance_pct   DOUBLE;
ALTER TABLE metrics_daily ADD COLUMN is_at_support          BOOLEAN;
ALTER TABLE metrics_daily ADD COLUMN pullback_from_high_pct DOUBLE;
ALTER TABLE metrics_daily ADD COLUMN reversal_score         INTEGER;
ALTER TABLE metrics_daily ADD COLUMN is_reversal            BOOLEAN;
ALTER TABLE metrics_daily ADD COLUMN is_pullback_reversal   BOOLEAN;
```

## Test plan

1. Hand-computed expected values for all four returns (FR-13.1) on a 1%/session
   series.
2. Null-handling for each new metric on a short history (FR-13.2).
3. Swing low: a synthetic V finds the trough; the last three sessions never
   qualify.
4. `support_level` picks the *nearest* candidate below price, not the lowest.
5. A stock at a 52-week high has a null `support_level` and is excluded.
6. Each reversal check R1–R5 fires independently on a fixture built for it.
7. A downtrending stock below `sma_200` is excluded however strong the bounce.
8. Determinism: the top-10 list is identical across two consecutive runs,
   including a constructed three-way tie.

## Open questions

| # | Question | Owner | Needed by |
|---|---|---|---|
| Q-1 | Is the 3%-to-25% pullback band right for this operator's holding period, or should it track ATR instead of fixed percentages? | Operator | Before live use |
| Q-2 | Should `reversal_score ≥ 2` be raised once there is backtest evidence across a full drawdown regime? | Operator, after Phase 3 evidence | Before live use |
