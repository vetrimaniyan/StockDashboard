# Backtest findings — Pullback + Reversal vs Momentum Leaders

Measured 2026-08-27 against 1,246 materialised sessions (2021-08-16 →
2026-08-25), engine at commit `4784bae`. Every figure below is
survivorship-biased upward; see the last section before quoting any of it.

## Constraint: nothing before 2022-08-19 is testable

Eligibility requires 252 sessions of history (FR-1.5) and the price store
starts 2021-08-16, so the first session with any eligible stock is
**2022-08-19** — 347 of 500. Backtests over the nominal full range silently
trade nothing for their first year.

Consequence: the February–July 2022 correction (−18.5%) **cannot be tested**
with the current five-year backfill. Testing the pullback screen against a
proper bear phase needs `alpha500 backfill --years 6` or more, which is the
strongest argument yet for the deeper history D-7 waived.

## Head to head, identical settings

`k = 3.0`, 10 positions, no trailing stop, Momentum Breakdown exit on,
2021-08-16 → 2026-08-25.

| | Pullback + Reversal | Momentum Leaders | NIFTY 500 |
|---|---|---|---|
| Net CAGR | 2.43% | **13.60%** | 11.13% |
| Net total return | 12.6% | 87.9% | 67.8% |
| Max drawdown | −32.60% | −30.38% | −18.84% |
| Sharpe (net) | 0.24 | 0.81 | — |
| Trades | 142 | 88 | — |
| Hit rate | 29.6% | 30.7% | — |
| Avg win / avg loss | 20.32% / −7.95% | 55.28% / −9.61% | — |
| Win/loss ratio | 2.55 | 5.75 | — |
| Avg hold | 93 d | 145 d | — |

**The hit rates are the same.** Both screens are right about 30% of the time.
The entire gap is win size — 20% against 55%. Buying at support caps upside by
construction: entry comes after the stock has given back 3–25% of its move, so
the trade captures the bounce back toward the prior high and the exit takes it
out. Momentum Leaders buys strength and holds 145 days, letting a few winners
reach 55%. At a 30% hit rate a strategy lives on win size, and this one
truncates it systematically.

## Regime dependence — mixed, not conclusive

Total return, exit screen on. Corrections identified from index drawdowns
below −7% lasting 15+ sessions.

| Period | Regime | Pullback | Momentum | Index |
|---|---|---|---|---|
| 2022-08-19 → 2026-08-25 | mixed | 12.6% | 87.9% | 55.0% |
| 2024-12-15 → 2025-06-30 | corrective, −18.8% | −9.1% | −9.8% | +1.1% |
| 2026-02-01 → 2026-05-31 | corrective, −16.2% | **+1.6%** | −5.0% | −0.8% |
| 2023-05-01 → 2024-12-31 | trending | 66.8% | 70.2% | 46.2% |

The hypothesis that this screen suits corrective regimes is **half supported**.
It won the 2026 correction outright, beating both the momentum screen and the
index. It lost the 2025 correction while the index gained. One win and one loss
is two data points, not a regime edge.

More useful: in the trending stretch the two screens are near-identical (66.8%
vs 70.2%). The screen is not structurally weak; its full-window damage
concentrates in periods outside those tested windows.

## The exit-screen result is a trap — do not act on it

Turning the Momentum Breakdown exit off appears to transform both strategies:

| Screen | Exit | Net CAGR | Trades | Closed winners |
|---|---|---|---|---|
| Pullback + Reversal | on | 3.05% | 142 | 42 |
| Pullback + Reversal | off | 8.12% | 20 | **0** |
| Momentum Leaders | on | 17.32% | 88 | 27 |
| Momentum Leaders | off | 31.22% | 23 | **0** |

Every closed trade in both exit-off runs is a **stop-out, and not one is a
winner**. All profitable positions remain open at the end, carried at market
value. Removing the exit does not improve the strategy — it degenerates it into
buy-and-hold of a portfolio drawn entirely from *current* NIFTY 500 members,
which is the survivorship bias in its purest expression. The dataset rewards
never selling because everything in it survived.

The finding is not "the exit screen is harmful". It is "this dataset cannot
answer that question", and the effect is large enough to invert the result
completely.

## Standing caveat

`index_membership` holds one snapshot with no closed intervals, and dropped
constituents were never ingested, so no figure here is achievable. **Relative**
comparisons over the same window with the same exit are the only trustworthy
readings; absolute returns are not. Parameter tuning on top of this dataset
fits bias, not signal.

## Verdict

Momentum Leaders is the better screen on available evidence. Pullback +
Reversal is **unproven rather than disproven** — it matches momentum in
trending periods and splits 1–1 across the two testable corrections. Settling
it needs point-in-time index membership, which is a data-sourcing problem
rather than a code one.
