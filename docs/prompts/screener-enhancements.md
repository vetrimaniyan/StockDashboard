# Prompt — generate requirements for the Alpha-500 screener enhancements

Paste everything below the line into the model or hand it to the author.

---

You are writing a requirements addendum to an existing, build-ready Software
Requirements Specification: **"NSE Momentum & Swing-Trading Dashboard (Project
Alpha-500)", version 1.0**. Phases 1–3 of that SRS are already implemented and
running. You are extending a live system, not designing a new one.

Your output is a specification an implementer can build from without asking a
follow-up question. It will be reviewed against the existing SRS for
consistency, so match its conventions exactly.

## System context you must design within

**Data and metric engine**

- Daily OHLCV for the NIFTY 500 lives in DuckDB (`ohlcv_daily`); derived
  metrics live in `metrics_daily`, keyed `(instrument_token, trade_date)`.
- Metrics are computed from **split/bonus-adjusted** prices
  (`adjusted = raw × adj_factor`), never adjusted for ordinary cash dividends.
- Periods are **trading sessions, not calendar days**. The existing constants
  are `WEEK = 5`, `MONTH = 21`, `QUARTER = 63`, `HALF_YEAR = 126`,
  `NINE_MONTHS = 189`, `YEAR = 252`.
- Existing return metrics, with their exact formulas:

  | Metric | Formula |
  |---|---|
  | `ret_1d` | `C_0 / C_1 − 1` |
  | `ret_1w` | `C_0 / C_5 − 1` |
  | `ret_1m` | `C_0 / C_21 − 1` |
  | `ret_3m` | `C_0 / C_63 − 1` |
  | `ret_6m` | `C_0 / C_126 − 1` |
  | `ret_9m` | `C_0 / C_189 − 1` |
  | `ret_12m` | `C_0 / C_252 − 1` |
  | `ret_12m_1m` | `C_21 / C_252 − 1` |

  **There is no `ret_2m`.** Any two-month anchor is new work.
- Per-symbol metrics and **cross-sectional** metrics are computed in separate
  passes. Anything requiring a percentile, rank, or z-score across the universe
  (for example `rs_rating`, `momentum_rank`) is cross-sectional and must be
  recomputed for the whole eligible universe every session.
- A metric registry (name, formula, dependencies, display metadata) drives the
  API, the results grid, the on-hover formula affordance, the export glossary,
  and a generated `METRICS.md`. Adding a metric must require **no change** to
  the API layer or the grid component.

**Screening**

- The screener filters on any column in `metrics_daily` plus `sector`,
  `industry`, `market_cap_band` and `index_membership`, using
  `> >= < <= = != between in "not in" "is null" "is not null" "top N"
  "bottom N" "top N%"`, combined with `AND`/`OR` and one level of nesting.
- Screen definitions serialise to JSON and persist by name and version.
- Seven preset screens ship built-in. **Two of them already overlap this
  work and you must reconcile with them rather than duplicate them:**
  - `FR-6.15 is_pullback` = `ma_alignment AND is_trend_template AND (C_0 within
    ±3% of ema_21 OR sma_50) AND ret_1w < 0 AND rsi_14 between 40 and 55`
  - Preset **"Pullback to Support"** = `is_pullback = TRUE`, sorted by
    `momentum_score` desc.

**Available inputs already computed per symbol per session**

`sma_20/50/100/150/200`, `ema_21`, `ema_50`, `sma_200_slope_1m`,
`ma_alignment`, `high_52w`, `low_52w`, `range_position_52w`,
`days_since_52w_high`, `atr_14`, `atr_pct_14`, `adr_pct_20`, `stdev_21/63`,
`rsi_14`, `adx_14`, `macd`, `macd_signal`, `macd_hist`, `rel_volume`,
`vol_sma_20/50`, `turnover_20d_median`, `delivery_pct_sma_20`,
`is_in_base`, `base_depth_pct`, `base_length_days`, `is_trend_template`,
`trend_template_score`, `rs_rating`, `momentum_score`, `momentum_rank`,
`is_eligible`.

**Hard constraints that change what is buildable**

- The operator is a **non-resident Indian resident in France**, trading through
  an NRO non-PIS account. All screens are **long-only**. Intraday and BTST are
  not permitted, so no signal may imply a holding period shorter than one full
  settlement cycle (T+1 credit, earliest exit the session after credit).
- Metric output MUST be **deterministic** — bit-identical across runs given the
  same price history. No wall-clock or random input anywhere in the metric
  layer. Any "top N" therefore needs a fully specified, deterministic
  tie-break.
- Where a symbol has fewer sessions than a window requires, the metric MUST be
  **null — never zero, never partially computed.**
- A backtest engine replays screens over history and requires every signal to
  be computable from `metrics_daily` alone, as of the signal date, using no
  data after it. Signals are acted on at the **next session's open**, never the
  signal-day close.

## Scope — specify exactly these two items

### Item 1 — additional return filters

Add return metrics for **2 weeks**, **3 weeks**, and **2-to-3 months**, usable
as screener filter conditions alongside the existing 1-week and 1-month
returns.

### Item 2 — pullback-and-reversal section

A dedicated section identifying the **top 10 stocks** that have **pulled back
to a support level** and are **showing signs of a trend reversal** (that is,
resuming the prior uptrend after a corrective move — not reversing downward).

## Decisions you must make explicitly, not paper over

State each decision, give the rule you chose, and give the one-line reason. Do
not leave any of these to the implementer.

1. **What "2 to 3-month return" means.** At least three readings are defensible
   and they produce different numbers:
   - a *lagged window* return measuring the month before last, by analogy with
     `ret_12m_1m` — for example `C_42 / C_63 − 1`;
   - a *range filter* over two separate metrics (`ret_2m` and `ret_3m`);
   - a *conjunction* requiring both the 2-month and 3-month return to satisfy a
     condition.
   Pick one, name it, and say why. If it needs `ret_2m` (42 sessions), specify
   that metric too.
2. **Session counts** for the 2-week and 3-week windows, consistent with the
   existing 5/21/63 convention.
3. **Price basis** — adjusted or raw close, and why. State the treatment of
   splits, bonuses and cash dividends explicitly.
4. **Support level**, defined as a computable rule, not a concept. Say which of
   these you are using and with what parameters: prior swing lows (and how a
   swing low is identified — fractal width, minimum retracement), a moving
   average, the low of a prior consolidation base, a prior breakout level now
   retested, a round-number or volume-weighted level. State the tolerance band
   for "at" support.
5. **Reversal signal**, defined as computable rules. Candidates: RSI turning up
   from a defined threshold, MACD histogram crossing, price reclaiming a named
   moving average, a bullish engulfing or hammer bar defined in OHLC terms,
   volume expansion on the up day against `vol_sma_50`, delivery percentage
   above its 20-day average. Specify how many must fire, and whether they are
   weighted or a simple count.
6. **Ordering of the top 10** — by strength of reversal signal, by depth of
   pullback, by relative strength, or by a composite. If composite, give the
   formula and the weights. Give the deterministic tie-break.
7. **Relationship to the existing pullback screen.** Choose one and justify it:
   extend `FR-6.15`, supersede it, or add a genuinely distinct signal beside
   it. If two pullback screens coexist, state how the operator is meant to tell
   them apart.
8. **Eligibility** — confirm the new section inherits the existing exclusions
   (series other than EQ/BE, ASM/GSM/T2T/suspended, fewer than 252 sessions of
   history, and the 20-day median traded value floor) or state the deviation.

## Output format

Produce a Markdown document with:

- **Section A — Additional return filters** and **Section B — Pullback and
  reversal section**, in that order.
- Every requirement carrying an ID continuing the existing scheme (`FR-x.y`),
  RFC 2119 keywords (**MUST** / **SHOULD** / **MAY**), and a **testable
  acceptance criterion**.
- An **exact formula** for every computed value, in the notation the existing
  SRS uses (`C_0` is the adjusted close of the latest session, `C_N` the close
  N sessions before it).
- A **decisions table** recording each of the eight decisions above, its
  resolution, and its rationale.
- A **schema delta** — the exact new `metrics_daily` columns with SQL types,
  plus the registry entry (name, label, formula, description, group, unit) for
  each new metric.
- A **test plan**: the hand-computed unit test for each new formula with its
  expected value, the null-handling case for insufficient history, and the
  determinism case.
- An **open questions** list for anything genuinely undecidable without the
  operator, each with the decision's owner and the date it is needed by.

## Definition of done

The addendum is complete when an implementer can build both items without
asking a question; when every new number has a formula, a test with a
hand-computed expected value, and a null-handling rule; when the top-10
ordering is deterministic including ties; and when the relationship to the
existing pullback screen is unambiguous.

Do not restate the existing SRS. Do not invent data the system does not
ingest — there is no intraday, tick, options, or fundamental data available,
and delivery-percentage data may be null and must be excluded rather than
treated as zero when it is.
