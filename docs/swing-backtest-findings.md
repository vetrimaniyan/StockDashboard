# Swing backtest findings — the FR-19 tiered trailing stop

The FR-19.4 gate. Four runs of the tiered trailing-stop exit rule over the two
candidate entry screens at two position counts, measured 2026-09-09 over
**2019-08-30 → 2026-08-27 (1,733 sessions)**, the same window
`backtest-findings.md` reports so the two are comparable.

> **Verdict: all four runs FAIL. Phase 2 (FR-19.5–19.7) stays blocked.**
> Two runs lose money decisively. The other two produced no trades at all,
> for a data reason that has to be fixed before the question can even be
> asked.

Every figure below is survivorship-biased upward. See the standing caveat.

## Configuration

Per FR-19.4: `--exit-rule tiered_trailing`, `--max-holding-days 21`,
`--time-stop-conditional`, `--reentry-cooldown-sessions 21`, stage 1 arming at
+5% and giving back 4 points, stage 2 at +10% giving back 2, initial stop at
`support_level - 0.5 * ATR14`. Sizing left at the engine defaults per
Decision 5. No exit screen, per Decision 3.

## The four runs

| Run | Net CAGR | Net total | Max DD | Sharpe | Trades |
|---|---|---|---|---|---|
| Pullback + Reversal @ 2 | **−11.05%** | −55.31% | −55.31% | −1.63 | 667 |
| Pullback + Reversal @ 3 | **−15.84%** | −69.44% | −70.02% | −1.87 | 984 |
| Fibonacci Reversal Zone @ 2 | — | — | — | — | **0** |
| Fibonacci Reversal Zone @ 3 | — | — | — | — | **0** |
| *NIFTY 500 buy-and-hold* | *15.13%* | *161.56%* | — | — | — |

Gross of TDS the two Pullback runs are −7.18% and −10.22% CAGR, so tax is not
what makes them negative. It deepens a hole the rule digs on its own.

### Why the Pullback runs lose

The trade statistics say it plainly, and they are consistent across both
position counts:

| | @ 2 | @ 3 |
|---|---|---|
| Hit rate | 26.7% | 27.1% |
| Average win | +5.48% | +5.46% |
| Average loss | −3.70% | −3.70% |
| Average hold | 7.6 sessions | 7.7 sessions |

Expectancy per trade is `0.267 × 5.48 − 0.733 × 3.70 = −1.25%`. A win/loss
ratio of 1.48 does not pay for a 27% hit rate; it needs roughly 40% to break
even before friction.

The rule works exactly as designed and that is the problem. The average win of
5.5% against a stage-1 arm at 5% and a 4-point giveback shows the trail is
doing its job: it arms, price gives back four points, the trade closes near
+5.5%. Meanwhile the initial stop takes a 3.7% loss on nearly three trades in
four. **The exit caps the winners at roughly the size of the losers while
leaving the loss rate untouched**, which is the arithmetic the addendum
predicted for `Momentum Leaders` in §1 and expected `Pullback + Reversal` to
escape. It does not escape it.

The 7.6-session average hold also disposes of the §1 hypothesis that the
bounce resolves its first 5–10% quickly. It resolves quickly and then stops
out. The 102-day average hold reported for this screen in
`backtest-findings.md` is not a slow version of the same trade — it is a
different trade, one this exit rule never allows to happen.

### The cooldown did not reduce trade count

FR-19.4 expects the cooldown to lower trade count relative to an uncooled run,
and asks for it as its own line so it is not mistaken for a bug. It does not
behave that way:

| Run | With cooldown | Without |
|---|---|---|
| Pullback + Reversal @ 2 | 667 | 656 |
| Pullback + Reversal @ 3 | 984 | 990 |

At two positions the cooldown **increased** trades. Blocking one token frees a
slot that a different token fills, and with 2–3 slots against a screen
matching dozens of names a day, substitution dominates. The expectation in
FR-19.4 assumed the cooldown removes trades outright; with a slot-constrained
portfolio it mostly reshuffles which name occupies the slot. Neither direction
is large, and neither rescues the result.

### The Fibonacci runs measured nothing

Zero trades at both position counts, and the reason is not that the setup was
rare. **The Fibonacci metrics do not exist for the first three years of the
window.**

| Year | Metric rows | With `fib_reward_risk` | In zone | Reversal bar |
|---|---|---|---|---|
| 2019 | 89,908 | **0** | 0 | 0 |
| 2020 | 95,309 | **0** | 0 | 0 |
| 2021 | 98,504 | **0** | 0 | 0 |
| 2022 | 104,403 | 30,906 | 2,214 | 261 |
| 2023 | 106,469 | 37,450 | 943 | 106 |
| 2024 | 111,804 | 43,763 | 1,154 | 145 |
| 2025 | 119,955 | 33,229 | 1,872 | 261 |
| 2026 | 86,921 | 25,545 | 1,653 | 231 |

FR-17 added these columns in 2026-08; the materialised history was only
recomputed with them back to 2022. A run starting in 2019 spends its first
three years unable to signal by construction.

Even inside the populated span the full preset yields **one signal in four and
a half years** (2022-01-01 → 2026-08-27). The screen's own gates — long-term
uptrend, trend template ≥ 6, RS ≥ 70, both volume ratios, the reversal bar and
the reward:risk floor — compound to near-zero jointly over history, against
205 rows that clear `in_fib_zone` and `is_fib_reversal_bar` alone.

So the Fibonacci runs fail FR-19.4 check 2, but they fail it as **"this dataset
cannot answer the question"**, not as "the setup does not work". Recording them
as a strategy result would be the confident-wrong-numbers mistake this project
exists to avoid. §1's worry about signal scarcity with 2–3 slots is confirmed
as a real risk, but not quantified by these runs.

## Against the five checks

| # | Check | Pullback @2 | Pullback @3 | Fib @2 | Fib @3 |
|---|---|---|---|---|---|
| 1 | Net CAGR and total return | **FAIL** −11.05% | **FAIL** −15.84% | **FAIL** no result | **FAIL** no result |
| 2 | ≥ ~30 closed trades | PASS 667 | PASS 984 | **FAIL** 0 | **FAIL** 0 |
| 3 | Survivorship warning reported | PASS, fires | PASS, fires | PASS, fires | PASS, fires |
| 4 | Walk-forward plateau, not a peak | PASS, no warning | PASS, no warning | **FAIL** vacuous | **FAIL** vacuous |
| 5 | Beats NIFTY 500 buy-and-hold | **FAIL** by 26pp CAGR | **FAIL** by 31pp | **FAIL** | **FAIL** |

**No run passes all five. Phase 2 must not start.**

Check 4 deserves a note. `assess_peak` raised no overfitting warning on either
Pullback run, and the walk-forward gap is small: in-sample −8.30% against
out-of-sample −9.41% at two positions, −12.76% against −15.33% at three. That
is not reassurance. It means the rule was reliably bad in and out of sample
rather than fitted to one span. The swept `stage1_giveback_pct` chose values
across 0.04–0.06 with no stable preference, which is what a flat, uniformly
negative surface looks like.

For the Fibonacci runs check 4 is vacuous: a sweep over a configuration that
never trades returns the same zero at every value, which `assess_peak` reads
as a perfect plateau. A plateau of nothing is not a pass.

## A defect this run exposed

The survivorship warning was silent on the first pass of these runs, and it
should not have been. `survivorship_warnings` asked whether `index_membership`
held any closed interval at all. On 2026-09-09 a placeholder constituent
(`DUMMYHEG`, NSE's stand-in for the HEG demerger) joined the index and was
removed two days later, creating exactly one closed interval — and switching
the warning off across a store holding **eight years of prices behind three
weeks of membership**.

The test now asks the question that matters: whether membership reaches back
at least as far as the prices being tested. It does not.

```
SURVIVORSHIP BIAS: index_membership cannot describe the universe as it stood
on the dates being tested. Membership begins 2026-08-26 but prices begin
2018-08-17.
```

Covered by `test_survivorship_warning_survives_one_stray_closed_interval`.

## Standing caveat

Unchanged from `backtest-findings.md`, and it applies to every number here.
`index_membership` cannot reconstruct the past universe, and constituents
dropped over the period were never ingested. No absolute figure above is
achievable. Only relative comparisons over the same window with the same exit
are trustworthy.

That cuts both ways here. The bias inflates results, so a **negative** result
under it is if anything understated — the true figures are likely worse, not
better. That is what makes the FAIL verdict safe to act on even though the
underlying data cannot support a PASS.

## What would have to change

Not recommendations to act on, only the questions the data actually raises:

1. **The giveback is too tight for this entry.** A 4-point giveback on a
   5-point arm exits the trade almost as soon as it arms. The sweep covered
   0.02–0.06 and none of it helped, which suggests the arm threshold rather
   than the giveback is the wrong parameter — a 5% arm on a setup whose
   winners historically run 39.56% is cutting into the part that pays.
2. **The Fibonacci comparison has not been run.** It needs
   `alpha500 materialise` re-run from 2019 so the FR-17 columns exist across
   the window. Only then is a zero-trade result a finding rather than an
   artefact.
3. **Open question Q-4 is still unanswered** and these runs assume one
   reading of it: the cooldown applies to time-exits as well as stops. Given
   how little the cooldown moved trade count either way, resolving it is
   unlikely to change the verdict, but it should be resolved before anyone
   quotes these numbers as the tested configuration.

## Reproducing

```
.venv/Scripts/python scripts/run_swing_backtest.py
```

Stop the API first — the analytical store takes one writer or many readers,
never both. Per-run trade logs land in `exports/swing_backtest_*.json`, and the
collected summary in `exports/swing_backtest_summary.json`.
