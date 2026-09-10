# Swing backtest findings — the FR-19 tiered trailing stop

The FR-19.4 gate. Four runs of the tiered trailing-stop exit rule over the two
candidate entry screens at two position counts, measured 2026-09-10 over
**2019-08-30 → 2026-08-27 (1,733 sessions)**, the same window
`backtest-findings.md` reports so the two are comparable.

> **Verdict: all four runs FAIL. Phase 2 (FR-19.5–19.7) stays blocked.**
> Two runs lose money decisively. The other two produced no trades, because
> the screen behind them yields **one signal in seven years** once its own
> gates are applied together.

Every figure below is survivorship-biased upward. See the standing caveat.

> **Revised.** An earlier version of this document attributed the Fibonacci
> runs' zero trades to missing data — the FR-17 columns did not exist before
> 2022, so a run starting in 2019 could not signal. That was true and it was
> not the cause. The history has since been re-materialised from 2019 and the
> columns now span the window; the screen still returns one signal. §"The
> Fibonacci screen" below replaces the earlier diagnosis.

## Configuration

Per FR-19.4: `--exit-rule tiered_trailing`, `--max-holding-days 21`,
`--time-stop-conditional`, `--reentry-cooldown-sessions 21`, stage 1 arming at
+5% and giving back 4 points, stage 2 at +10% giving back 2, initial stop at
`support_level - 0.5 * ATR14`. Sizing left at the engine defaults per
Decision 5. No exit screen, per Decision 3.

## The four runs

| Run | Net CAGR | Net total | Max DD | Sharpe | Trades |
|---|---|---|---|---|---|
| Pullback + Reversal @ 2 | **−11.12%** | −55.55% | −56.63% | −1.65 | 680 |
| Pullback + Reversal @ 3 | **−15.89%** | −69.58% | −70.92% | −1.92 | 995 |
| Fibonacci Reversal Zone @ 2 | — | — | — | — | **0** |
| Fibonacci Reversal Zone @ 3 | — | — | — | — | **0** |
| *NIFTY 500 buy-and-hold* | *15.13%* | *161.56%* | — | — | — |

Gross of TDS the two Pullback runs are −6.92% and −10.22% CAGR, so tax is not
what makes them negative. It deepens a hole the rule digs on its own.

### Why the Pullback runs lose

The trade statistics say it plainly, and they are consistent across both
position counts:

| | @ 2 | @ 3 |
|---|---|---|
| Hit rate | 26.6% | 26.9% |
| Average win | +5.64% | +5.45% |
| Average loss | −3.70% | −3.69% |
| Average hold | 7.4 sessions | 7.6 sessions |

Expectancy per trade is `0.266 × 5.64 − 0.734 × 3.70 = −1.22%`. A win/loss
ratio of 1.52 does not pay for a 27% hit rate; it needs roughly 40% to break
even before friction.

The rule works exactly as designed and that is the problem. An average win of
5.6% against a stage-1 arm at 5% and a 4-point giveback shows the trail doing
its job: it arms, price gives back four points, the trade closes near +5.5%.
Meanwhile the initial stop takes a 3.7% loss on nearly three trades in four.
**The exit caps the winners at roughly the size of the losers while leaving the
loss rate untouched**, which is the arithmetic the addendum predicted for
`Momentum Leaders` in §1 and expected `Pullback + Reversal` to escape. It does
not escape it.

The 7.4-session average hold also disposes of the §1 hypothesis that the bounce
resolves its first 5–10% quickly. It resolves quickly and then stops out. The
102-day average hold reported for this screen in `backtest-findings.md` is not a
slow version of the same trade — it is a different trade, one this exit rule
never allows to happen.

### The cooldown did not reduce trade count

FR-19.4 expects the cooldown to lower trade count relative to an uncooled run,
and asks for it as its own line so it is not mistaken for a bug. It does not
behave that way:

| Run | With cooldown | Without |
|---|---|---|
| Pullback + Reversal @ 2 | 680 | 679 |
| Pullback + Reversal @ 3 | 995 | 989 |

Both directions are inside noise, and at three positions the cooldown
**increased** trades. Blocking one token frees a slot that a different token
fills, and with 2–3 slots against a screen matching dozens of names a day,
substitution dominates. FR-19.4's expectation assumed the cooldown removes
trades outright; in a slot-constrained portfolio it mostly reshuffles which
name occupies the slot.

## The Fibonacci screen cannot fill two slots

Zero trades at both position counts. The history now carries the FR-17 columns
across the whole window — 10,441 rows with a reward:risk in 2019 where there
were none — and the screen still produces **one signal between 2019-08-30 and
2026-08-27**.

The funnel says which gate is responsible:

| Stage | Rows surviving |
|---|---|
| Eligible | 642,952 |
| In a long-term uptrend | 367,548 |
| Trend template score ≥ 6 | 305,780 |
| RS rating ≥ 70 | 175,771 |
| **Inside the 50–61.8% retracement** | **348** |
| Volume: advance confirmed | 243 |
| Volume: pullback thinned | 56 |
| Turned that session | 2 |
| Reward:risk ≥ 2.0 | **1** |

**The location gate and the trend gates are in tension.** 175,771 rows clear
the trend requirements; requiring price to sit inside the retracement band as
well cuts that by 99.8%. That is not a rare setup being rare. A retracement deep
enough to reach the 50–61.8% zone has usually broken the trend template the
screen simultaneously demands, so the two conditions rarely hold at once. The
reversal-bar gate then takes 56 to 2.

For context, the same store holds 11,576 rows with `in_fib_zone` true across all
years. Nearly all of them fail the trend gates.

This is a finding about the screen, not about the exit rule. **FR-19.4's
Fibonacci arm cannot be answered by any exit rule**, because there is nothing to
exit. §1's worry about signal scarcity with 2–3 slots is confirmed, and is
considerably worse than "0–5 rows most sessions" suggested.

It also sits awkwardly against FR-17.6/17.7's own acceptance note. Live, the
screen behaves as documented. Over seven years of stored history it effectively
never fires. Whether that is the screen being correctly strict or a threshold
mis-set is a question for FR-17, not for this document.

## Against the five checks

| # | Check | Pullback @2 | Pullback @3 | Fib @2 | Fib @3 |
|---|---|---|---|---|---|
| 1 | Net CAGR and total return | **FAIL** −11.12% | **FAIL** −15.89% | **FAIL** no result | **FAIL** no result |
| 2 | ≥ ~30 closed trades | PASS 680 | PASS 995 | **FAIL** 0 | **FAIL** 0 |
| 3 | Survivorship warning reported | PASS, fires | PASS, fires | PASS, fires | PASS, fires |
| 4 | Walk-forward plateau, not a peak | PASS, no warning | PASS, no warning | **FAIL** vacuous | **FAIL** vacuous |
| 5 | Beats NIFTY 500 buy-and-hold | **FAIL** by 26pp CAGR | **FAIL** by 31pp | **FAIL** | **FAIL** |

**No run passes all five. Phase 2 must not start.**

Check 4 deserves a note. `assess_peak` raised no overfitting warning on either
Pullback run, and the walk-forward gap is small: in-sample −7.14% against
out-of-sample −10.02% at two positions, −13.18% against −15.52% at three. That
is not reassurance. It means the rule was reliably bad in and out of sample
rather than fitted to one span.

For the Fibonacci runs check 4 is vacuous: a sweep over a configuration that
never trades returns the same zero at every value, which `assess_peak` reads as
a perfect plateau. A plateau of nothing is not a pass.

## Two defects this exercise exposed

**The survivorship warning was silent** on the first pass of these runs.
`survivorship_warnings` asked whether `index_membership` held any closed
interval at all. On 2026-09-09 a placeholder constituent (`DUMMYHEG`, NSE's
stand-in for the HEG demerger) joined the index and was removed two days later,
creating exactly one closed interval — and switching the warning off across a
store holding eight years of prices behind three weeks of membership. It now
asks whether membership reaches back as far as the prices being tested. It does
not:

```
SURVIVORSHIP BIAS: index_membership cannot describe the universe as it stood
on the dates being tested. Membership begins 2026-08-26 but prices begin
2018-08-17.
```

Covered by `test_survivorship_warning_survives_one_stray_closed_interval`.

**`materialise` could not rewrite a large range at all.** Pass 2 opens by
clearing the range it is about to rewrite, and that delete went through
`idx_metrics_date_rank`:

```
FATAL Error: Invalid Input Error:
Failed to delete all rows from index. Only deleted 601 out of 1052 rows.
```

The same fault `TROUBLESHOOTING.md` records against `compute_metrics` on
2026-09-07, reached from the other direction and far more expensively: it fires
after pass 1 has staged every symbol, so the whole run is lost. The rewrite now
drops the index and rebuilds it in a `finally`. Without this fix the
re-materialisation that produced the corrected Fibonacci diagnosis above could
not have been run.

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

Not recommendations to act on, only the questions the data raises:

1. **The arm threshold, not the giveback, looks like the wrong parameter.** A
   4-point giveback on a 5-point arm exits almost as soon as it arms, and the
   sweep over 0.02–0.06 did not help. A 5% arm on a setup whose winners
   historically run 39.56% is cutting into the part that pays. Testing a higher
   arm is a different experiment, not a tuning of this one.
2. **The Fibonacci arm needs an FR-17 decision before it can be retested.** One
   signal in seven years is not a sample. Either the trend gates and the
   retracement band need reconciling, or the screen is accepted as a rarity and
   dropped from consideration for a 2–3 slot strategy.
3. **Open question Q-4 is still unanswered** and these runs assume one reading:
   the cooldown applies to time-exits as well as stops. Given the cooldown moved
   trade count by less than 1% either way, resolving it will not change the
   verdict, but it should be resolved before anyone quotes these numbers as the
   tested configuration.

## Reproducing

```
.venv/Scripts/python scripts/run_swing_backtest.py
```

Stop the API first — the analytical store takes one writer or many readers,
never both. Per-run trade logs land in `exports/swing_backtest_*.json`, and the
collected summary in `exports/swing_backtest_summary.json`.
