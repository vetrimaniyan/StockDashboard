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

**The location gate and the trend gates were in tension**, and that has since
been repaired — see below. It was not, however, what makes this screen
unusable.

### The trend gates, reconciled (2026-09-10)

The metric engine keeps `is_long_term_uptrend` separate from `ma_alignment`
for a documented reason:

> `ma_alignment` also demands close > sma_50, which a 50-61.8% retracement
> normally breaks — using it to gate a pullback screen would exclude the very
> setups the screen exists to find.

The preset then added `trend_template_score >= 6`, which reimposes exactly that
through criterion 5 (close > SMA50) and criterion 1 (close > SMA150 and
SMA200). Measured inside the zone over this window:

| Trend template criterion | Held on |
|---|---|
| 5. close > SMA50 | **9.0%** |
| 8. RS rating ≥ 70 | 9.9% |
| 1. close > SMA150 and SMA200 | **15.1%** |
| 2. SMA150 > SMA200 | 40.8% |
| 3. SMA200 slope > 0 | 42.6% |
| 4. SMA50 > SMA150 and SMA200 | 52.1% |
| 6. close ≥ 1.3× 52w low | 24.1% |
| 7. close ≥ 0.75× 52w high | 41.6% |

Demanding six of eight asked the screen to find a deep pullback and then
required price not to have pulled back. The template is now replaced by
criterion 3 alone — the slope of the long average, which a retracement does
not invalidate. `is_long_term_uptrend` already carries SMA50 > SMA200, the
pullback-safe half of criterion 4.

**This raises the count from 1 signal to 2.** The trend gates were never the
binding constraint:

| Gate | Signals over the window |
|---|---|
| As shipped | 1 |
| Reconciled, RS ≥ 70 | **2** |
| Reconciled, RS ≥ 50 | 4 |
| Reconciled, no RS gate | 8 |
| **No trend gate at all — the ceiling** | **56** |

Fifty-six in seven years is the most this screen can produce however its trend
gates are set. The real cliffs are elsewhere: `in_fib_zone` admits 8,897 of
642,952 eligible rows (1.4%), and of those only 282 carry a reversal bar (3.2%),
which the volume shape then takes to 84 and the reward:risk floor to 56.

### The RS floor was tested, and stays (2026-09-10)

`rs_rating >= 70` looked like the same contradiction in milder form: inside the
zone it holds on 9.9% of rows against 30.3% of all eligible rows. It is not.

The pullback does depress the rating, but only slightly — the same names read a
median RS of **31** sixty sessions before entering the zone and **24** on the
zone day. And the gate earns what it costs. Forward 21-session return measured
from every zone day over the window:

| Band | n | Median | Mean | Positive |
|---|---|---|---|---|
| **RS ≥ 70** | 884 | **+2.35%** | **+4.18%** | **58.1%** |
| RS 50-69 | 1,052 | +1.33% | +0.76% | 54.0% |
| RS < 50 | 6,821 | +1.29% | +1.84% | 55.6% |

Best band on every measure. Relaxing to 50 would buy two extra signals a decade
by admitting the weaker two thirds, so the floor stays at 70.

**The same measurement says something harsher about the zone itself.** Median RS
inside it is **24**, against **50** across all eligible rows. The 50-61.8% band
is not mostly finding strong trends pulling back; it is finding names that have
already broken down. That reframes the reconciliation above: the trend gates and
the band conflict not because the gates are wrong, but because most things that
reach the band are genuinely weak. Whether the band is the right location test
is FR-17's question to answer.

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
2. **The Fibonacci arm cannot serve a 2–3 slot strategy at any trend-gate
   setting.** The gates have been reconciled and it buys one extra signal. With
   a ceiling of 56 over seven years, the remaining questions belong to FR-17,
   not here: whether `in_fib_zone` at 1.4% of eligible rows and the reversal bar
   at 3.2% of those are the intended strictness, and whether `rs_rating >= 70`
   should stand inside a deep pullback.
3. **Q-4 is resolved and the runs above are the tested configuration.** The
   cooldown applies to any exit under this rule, time exits included, because
   FR-19.2 fires the time branch only on a position that is flat or losing:
   **42 of 42 time exits across both runs were losses**. A different question
   fell out of the same count and is filed as Q-5 — 449 of 1,675 exits were
   *profitable* stop-outs, which the cooldown also stands down.

## Reproducing

```
.venv/Scripts/python scripts/run_swing_backtest.py
```

Stop the API first — the analytical store takes one writer or many readers,
never both. Per-run trade logs land in `exports/swing_backtest_*.json`, and the
collected summary in `exports/swing_backtest_summary.json`.
