# Backtest findings — Pullback + Reversal vs Momentum Leaders

Measured 2026-08-27 against **1,984 materialised sessions (2018-08-17 →
2026-08-27)**, engine at commit `4784bae`. Every figure is survivorship-biased
upward; see the caveat before quoting any of it.

> **Revised.** An earlier version of this document tested five years and
> concluded Pullback + Reversal was near-worthless (2.43% net CAGR). That was
> wrong, and wrong for a knowable reason: five years of prices leaves only
> ~3.9 years of *eligible* universe, starting at an unrepresentative point.
> Deepening the backfill to eight years moved the same screen, unchanged, from
> 2.43% to **14.46%**. The screen did not improve — the measurement did.

## Coverage after the eight-year backfill

| | Before (5y) | After (8y) |
|---|---|---|
| Sessions | 1,246 | **1,984** |
| Metric rows | 562,661 | **841,019** |
| First eligible session | 2022-08-19 | **2019-08-30** |
| Testable corrections | 2 | **6** |

Eligibility needs 252 sessions of history (FR-1.5), so the usable window always
begins about a year after the price data does.

### Acceptance criterion 1 is structurally unachievable

398 of 500 symbols now carry ≥1 260 sessions, against the ≥495 the criterion
requires. The shortfall is **not** a fetch failure: all 102 are genuine recent
listings — ICICIAMC (2025-12-19), MEESHO (2025-12-10), PINELABS (2025-11-14),
and 99 others first traded between 2021 and 2025.

A current-constituent universe necessarily contains recent IPOs, so no backfill
depth can satisfy the criterion as literally written. The SRS's own escape
clause — "with the shortfall symbols named and explained" — is the resolution;
the shortfall is named above and explained by listing date.

## Head to head, eight years

`k = 3.0`, 10 positions, no trailing stop, Momentum Breakdown exit on,
2019-08-30 → 2026-08-27.

| | Pullback + Reversal | Momentum Leaders | NIFTY 500 |
|---|---|---|---|
| Net CAGR | 14.46% | **21.80%** | — |
| Net total return | 153.1% | **288.1%** | 161.9% |
| Max drawdown | **−28.32%** | −34.20% | — |
| Sharpe (net) | 0.90 | **1.16** | — |
| Trades | 231 | 170 | — |
| Hit rate | 31.2% | **40.0%** | — |
| Avg win | 39.56% | 47.92% | — |
| Avg hold | 102 d | 135 d | — |

Momentum Leaders still wins on return and risk-adjusted return, and it is the
only one of the two that beats buy-and-hold outright (288.1% against 161.9%).
Pullback + Reversal returns 153.1%, marginally *below* the index — but with the
**shallower drawdown of the two**, −28.32% against −34.20%.

The 5-year finding that the two screens shared a hit rate no longer holds:
over eight years Momentum is right 40.0% of the time against 31.2%.

## By regime — the hypothesis now has support

Total return over each correction the deeper history makes testable, padded
30 days each side. Corrections identified from index drawdowns below −7%
lasting 15+ sessions.

| Window | Trough | Pullback | Momentum | Index |
|---|---|---|---|---|
| 2020-01-29 → 2020-09-17 (COVID) | −38.3% | −3.5% | **+1.3%** | −4.4% |
| 2022-01-18 → 2022-04-28 | −14.6% | −1.0% | **−0.3%** | −4.2% |
| 2022-04-02 → 2022-08-28 | −18.5% | **+9.7%** | +4.5% | −1.5% |
| 2023-02-07 → 2023-05-11 | −11.2% | **+10.1%** | +4.4% | +3.9% |
| 2024-12-04 → 2025-06-13 | −18.8% | −13.3% | **−11.7%** | −0.8% |
| 2026-02-02 → 2026-05-16 | −16.2% | **+4.3%** | −2.9% | −1.3% |

**Pullback + Reversal beats the index in five of six corrections** and beats
Momentum in three of six — and its wins are by wider margins (+5.2, +5.7, +7.2
points) than Momentum's (+4.8, +0.7, +1.6). The regime hypothesis that failed
on two data points now has six, and it holds.

**The exception matters.** In the 2024-12 → 2025-06 correction the screen lost
13.3% while the index lost 0.8% — its worst relative showing anywhere in eight
years, and the most recent one. That is a real counter-example, not noise to be
explained away, and it is the single strongest argument against trading this
screen on the strength of the table above.

## The exit-screen result is a trap — do not act on it

Measured on the five-year data; the mechanism is structural and does not depend
on window length.

| Screen | Exit | Net CAGR | Trades | Closed winners |
|---|---|---|---|---|
| Pullback + Reversal | on | 3.05% | 142 | 42 |
| Pullback + Reversal | off | 8.12% | 20 | **0** |
| Momentum Leaders | on | 17.32% | 88 | 27 |
| Momentum Leaders | off | 31.22% | 23 | **0** |

Every closed trade in both exit-off runs is a **stop-out, and not one is a
winner**. All profitable positions remain open at the end, carried at market
value. Removing the exit does not improve the strategy — it degenerates it into
buy-and-hold of a portfolio drawn entirely from *current* index members, which
is survivorship bias in its purest expression.

The finding is not "the exit screen is harmful". It is "this dataset cannot
answer that question", and the effect is large enough to invert the result.

## Standing caveat

`index_membership` holds one snapshot with no closed intervals, and dropped
constituents were never ingested, so no absolute figure here is achievable.
**Relative** comparisons over the same window with the same exit are the only
trustworthy readings. Parameter tuning on top of this dataset fits bias, not
signal.

The bias also grows with window length: an eight-year test asks every symbol to
have survived eight years in the index, which is a harder filter than five. The
improvement from 2.43% to 14.46% is therefore *partly* real — a fairer sample
of regimes — and *partly* an artefact of a stronger survivorship screen. Both
effects point the same way and cannot be separated with this data.

## Verdict

**Momentum Leaders remains the better single screen**: more return, higher
Sharpe, a better hit rate, and the only one that beats buy-and-hold.

**Pullback + Reversal is now a viable strategy rather than an unproven one.**
It returns 14.46% CAGR with a shallower drawdown than Momentum, and it
outperforms the index in five of six corrections. Its plausible role is as a
complement in defensive regimes rather than a replacement — with the 2025
counter-example understood first.

What would settle it remains point-in-time index membership, which is a
data-sourcing problem rather than a code one.
