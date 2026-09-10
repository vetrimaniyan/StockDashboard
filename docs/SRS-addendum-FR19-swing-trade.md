# SRS Addendum — Swing Trade Setup (FR-19)

**Everything for this build in one document** — background, decisions,
requirements, full code appendix, including the re-entry cooldown design
that was previously left as an open question. Nothing needed from earlier
chat history.

Extends `URD.md` (Alpha-500), which extends the parent SRS. Continues the FR
numbering from URD.md §2 (`FR-19.x`, next free at time of writing: NFR-7,
D-12, B-12 also free if needed). Written for Claude Code to build directly
from.

---

## 0. Background — why this addendum exists

The operator (NRI, France, NRO non-PIS account, long-only, no
intraday/BTST) wants a **swing-trade strategy targeting 5–10% profit per
trade**, run alongside the existing Alpha-500 screens, with:

- **2–3 concurrent positions**
- **Max hold: 1 month (21 trading sessions)**
- **Exit rule**: a two-stage trailing stop that arms once a trade is up
  5% or more, tightens further past 10%, and — critically — **does not
  cap the upside**. A trade that runs to 20%+ keeps being trailed, not
  sold at a fixed target.
- **Position sizing: deferred** — the operator will supply real
  `risk_per_trade_pct` / `max_position_weight` numbers later; this
  addendum does not invent them.
- **No re-entry** into a stock for the rest of that trading month after
  it exits under this rule — now a resolved, implemented requirement
  (FR-19.8), not an open question. See §3a.
- **Backtest proof mandatory** before any of this reaches the dashboard —
  the operator was explicit that this needs "solid execution proof," not
  a plausible-sounding rule taken on faith.

Why the existing screens don't already answer this: the two closest
analogues, `Momentum Leaders` and `Pullback + Reversal`, are backtested
(see `backtest-findings.md`) at **avg wins of 47.92% / 39.56% over avg
holds of 135 / 102 days**. Both are trend-following systems built to let a
winner run for months. Nobody has tested what happens if the same entries
are exited on a fast trailing stop with a 1-month ceiling instead — the
win rate, average hold, and drawdown profile could all look completely
different. That gap is what Phase 1 below closes.

---

## 1. Entry screen — recommendation and reasoning

**Primary: `Pullback + Reversal`. Secondary, for comparison: `Fibonacci
Reversal Zone`.** Both reused verbatim from `presets.py` — no new entry
screen is proposed.

- **`Momentum Leaders` is the wrong base for this job.** Its edge lives in
  the long right tail (47.92% avg win / 135-day avg hold per
  `backtest-findings.md`). A trailing stop that arms at +5% would very
  likely amputate the trades that make the screen work, while still
  absorbing full exposure on the ones that fail.
- **`Pullback + Reversal` is a timing signal, not a trend-discovery
  signal** — it's already built around "at support, confirmed turn." The
  bounce it targets plausibly resolves its first 5–10% faster than the
  102-day average headline suggests, since that average blends the fast
  initial bounce with a long tail of trades that kept running. That's a
  hypothesis, which is exactly why FR-19.4 requires a real backtest
  rather than accepting the hypothesis on its face.
- **`Fibonacci Reversal Zone` is the same family, stricter** (needs
  `is_fib_reversal_bar`, a confirmed impulse leg, and `fib_reward_risk`
  above a floor — see the verbatim preset in the code appendix). Likely
  higher quality per signal, but per FR-17.6/17.7's own acceptance note,
  most sessions return 0–5 rows, and on 2026-08-31 it returned **zero**.
  With only 2–3 concurrent slots, signal scarcity is a real risk. Worth
  testing empirically against `Pullback + Reversal` rather than assuming
  either is better.
- **`Volatility Contraction`** (breakout continuation) was considered and
  not recommended: different entry mechanics entirely (momentum
  continuation, not mean-reversion), and failed breakouts tend to fail
  fast, which interacts badly with a stop that only arms *after* +5% —
  there's no protection against the failure mode this screen is most
  exposed to.

---

## 2. Decisions

| # | Decision | Resolution | Why |
|---|---|---|---|
| 1 | Where the new exit rule lives | New fields on `BacktestConfig`, activated only by `exit_rule="tiered_trailing"` | Every other config (`Momentum Leaders`, any run using the ATR-chandelier trail or the `Momentum Breakdown` exit screen) must produce byte-identical output to today, unchanged. This is an addition to a live system, not a replacement. |
| 2 | Entry screens | Reuse `PULLBACK_REVERSAL` and `FIB_REVERSAL_ZONE` from `presets.py` verbatim | See §1. The open design question is the *exit*, not the *entry*. |
| 3 | Interaction with `fib_target` | The tiered trailing stop is the only exit condition; `fib_target` (leg-high recovery) and `exit_screen=Momentum Breakdown` are both **not used** under this rule | A trailing stop and a fixed take-profit are two different exit philosophies. Combining them silently (whichever hits first) would make the backtest result impossible to attribute to either one. FR-17.6's `fib_reward_risk` floor still gates which signals qualify as entries — that part is untouched. |
| 4 | Re-entry cooldown | **Resolved.** Engine-internal state (`last_exit_slot` dict inside `_simulate`), tracked in trading sessions, checked at entry. See FR-19.8. | Keeps the rule co-located with the rest of the exit logic rather than split across two layers (engine + upstream signal filtering). Sessions, not calendar days, to match the engine's existing FR-6.1 convention rather than introducing a second, inconsistent notion of "a month." |
| 5 | Position sizing | **Deferred by the operator.** Phase 1 runs on the engine's existing `risk_per_trade_pct` / `max_position_weight` defaults | So nobody reads the Phase 1 backtest numbers as sized the way the operator will eventually trade. `risk.py`'s `size_position()` needs no change for this. |
| 6 | Phase 2 gate | Dashboard screen (§5) is **blocked** until Phase 1's acceptance criteria (FR-19.4) pass | Matches the system's own principle: "a backtest run on today's constituent list is worthless and worse than no backtest, since it produces confident wrong numbers." A UI surfacing an unproven exit rule is the same mistake with a nicer front end. |

**Correction to a prior assumption**, recorded here because it materially
affects §4's runner script: an earlier ad-hoc attempt (outside this repo)
assumed `Pullback + Reversal` was capped at 10 rows. It isn't — the
2026-09-09 change log entry made it deliberately uncapped, with the top-10
slice taken by the dashboard endpoint, not the preset. §4's script imports
the real preset directly rather than reconstructing it, which makes this
class of error structurally impossible going forward.

---

## 3. Phase 1 — Backtest proof (build first)

### FR-19.1 — Tiered trailing-stop exit rule

The system MUST support a second stop-and-trail mechanism in the backtest
engine, selected per-run and never applied unless explicitly requested.

**`backend/alpha500/backtest/engine.py`, `BacktestConfig`** — add:

```python
exit_rule: str = "atr_trailing"           # "atr_trailing" (default, unchanged) | "tiered_trailing"
initial_stop_atr_multiple: float = 0.5    # support_level - this * ATR14; tiered_trailing only
stage1_arm_pct: float = 0.05
stage1_giveback_pct: float = 0.04
stage2_arm_pct: float = 0.10
stage2_giveback_pct: float = 0.02
time_stop_only_if_not_profitable: bool = False   # default preserves existing unconditional time-stop
reentry_cooldown_sessions: int | None = None     # None = no cooldown (old behaviour); see FR-19.8
```

**`Trade`** — add `peak_gain_pct: float = 0.0`, included (as a percentage)
in `as_dict()`.

**`_price_panel`** — extend the SELECT to also pull `m.support_level`,
loaded into a new `"support"` array per token. Already stored in
adjusted-price terms by the metric engine (per `METRICS.md`), so no
`adj_factor` multiplication is applied to it, unlike the raw OHLC columns.

**Initial stop** (entry logic in `_simulate`), only when
`config.exit_rule == "tiered_trailing"`:
```python
support = arrays["support"][slot - 1]
if not (finite(open_px) and open_px > 0 and finite(atr) and finite(support)):
    continue  # skip this signal, no trade opened
fill_price = open_px * (1.0 + config.slippage_pct)
stop = support - config.initial_stop_atr_multiple * atr
```
Guard `stop <= 0 or stop >= fill_price` unchanged from the existing path.

**Trailing update** (the block currently reading `if reason is None or
fill is None: ...`), only when `config.exit_rule == "tiered_trailing"`:
```python
gain_pct = close_px / trade.entry_price - 1.0
trade.peak_gain_pct = max(trade.peak_gain_pct, gain_pct)
candidates = [trade.stop_price]
if trade.peak_gain_pct >= config.stage1_arm_pct:
    candidates.append(trade.entry_price * (1.0 + trade.peak_gain_pct - config.stage1_giveback_pct))
if trade.peak_gain_pct >= config.stage2_arm_pct:
    candidates.append(trade.entry_price * (1.0 + trade.peak_gain_pct - config.stage2_giveback_pct))
trade.stop_price = max(candidates)
```
The existing `atr_trailing` branch (`config.trailing_stop` /
`stop_atr_multiple`) is untouched and remains the default for every other
config. The exit-detection line — `if low <= trade.stop_price:` — MUST
NOT change. Only how `stop_price` is set and updated changes.

*Acceptance:*
- A trade entered at 100 whose peak gain reaches 8% then pulls back to 3%
  keeps a stop at `100 * (1 + 0.08 - 0.04) = 104`, not one recomputed off
  the pulled-back 3%. Named test `test_tiered_stop_never_unarms`.
- Peak gain later reaches 12%: stop becomes `100 * (1 + 0.12 - 0.02) = 110`,
  strictly above the Stage-1 value at the same peak. Named test
  `test_tiered_stop_stage2_is_tighter_than_stage1`.
- A signal whose `support_level` is null at entry time is skipped — no
  trade opens. Named test `test_tiered_entry_skips_null_support`.
- With `exit_rule` left at its default and every new field left at its
  default, output is byte-identical to the pre-change engine over a fixed
  date range and screen. Named test
  `test_tiered_trailing_fields_are_a_no_op_by_default`. **This is the
  most important test in this addendum** — it proves nothing else in the
  system moved.

*Status:* Proposed

---

### FR-19.2 — Conditional time stop

**`_simulate`**, the existing `max_holding_days` branch — add the
profitability check, gated by its own flag so no other config's behaviour
changes:

```python
elif (
    config.max_holding_days is not None
    and (session - trade.entry_date).days >= config.max_holding_days
    and np.isfinite(open_px)
    and (
        not config.time_stop_only_if_not_profitable
        or (open_px / trade.entry_price - 1.0) <= 0.0
    )
):
    fill = open_px
    reason = "time"
```

A position past the time limit but still profitable is deliberately left
open, for the trailing stop (FR-19.1) to close out whenever it triggers —
not forced out here.

*Acceptance:* with `time_stop_only_if_not_profitable=True` and
`max_holding_days=21`, a position at +6% on session 21 is NOT closed by
this branch and remains open; the same position at 0% or negative IS
closed at that session's open. Named test
`test_conditional_time_stop_spares_profitable_positions`.

*Status:* Proposed

---

### FR-19.3 — CLI surface

**`backend/alpha500/cli.py`**, `cmd_backtest` and its argparse subparser
(`p_bt`) — the current CLI has no flag for `max_holding_days` at all (the
field exists on `BacktestConfig` but nothing sets it from the command
line), and none of the new FR-19.1/19.2/19.8 fields are wired either. Add:

```python
p_bt.add_argument("--max-holding-days", type=int, default=None)
p_bt.add_argument("--exit-rule", choices=["atr_trailing", "tiered_trailing"], default="atr_trailing")
p_bt.add_argument("--initial-stop-atr", type=float, default=0.5)
p_bt.add_argument("--stage1-arm", type=float, default=0.05)
p_bt.add_argument("--stage1-giveback", type=float, default=0.04)
p_bt.add_argument("--stage2-arm", type=float, default=0.10)
p_bt.add_argument("--stage2-giveback", type=float, default=0.02)
p_bt.add_argument("--time-stop-conditional", action="store_true")
p_bt.add_argument("--reentry-cooldown-sessions", type=int, default=None)
```

Pass all eight into the `BacktestConfig(...)` construction in
`cmd_backtest` alongside the existing fields. `--use-exit-screen` MUST be
rejected (or ignored with a printed note — pick one, but decide) when
`--exit-rule tiered_trailing` is set, per Decision 3: the two exit
philosophies don't compose.

*Acceptance:* `alpha500 backtest "Pullback + Reversal" --exit-rule
tiered_trailing --max-holding-days 21 --time-stop-conditional
--reentry-cooldown-sessions 21 --max-positions 2` runs without error and
`_print_backtest` shows a nonzero trade count over the full 2019-08-30 to
2026-08-27 window.

*Status:* Proposed

---

### FR-19.4 — The gate Phase 2 is blocked on

Run FR-19.1–19.3 and FR-19.8 against **both** `Pullback + Reversal` and
`Fibonacci Reversal Zone`, at `max_positions` 2 and 3 (four runs total),
full 2019-08-30 to 2026-08-27 window, `--time-stop-conditional` on,
`--max-holding-days 21`, `--reentry-cooldown-sessions 21`.

For each run, using the CLI's existing `--walk-forward` machinery (already
built, `backend/alpha500/backtest/walkforward.py`), swept over
`stage1_giveback_pct` at a minimum:

The result MUST report, and a human MUST read before Phase 2 starts:
1. Net CAGR and net total return, gross and net of TDS (already computed
   by `stats.py`, unchanged).
2. Trade count. Fewer than ~30 closed trades over the full window on any
   one run is a sample too small to trust — say so plainly rather than
   quoting a percentage from it. The cooldown (FR-19.8) will reduce trade
   count relative to an uncooled run on the same screen — expected, and
   worth reporting as its own line so it isn't mistaken for a bug.
3. The `survivorship_warnings()` output, unchanged and un-suppressed.
4. The walk-forward verdict's `warning` field, specifically whether the
   chosen `stage1_giveback_pct`/`stage2_giveback_pct` sit on a plateau or
   a narrow peak (`assess_peak` in `walkforward.py`, already built — this
   addendum adds no new overfitting-detection code, only uses what
   exists).
5. Net CAGR against NIFTY 500 buy-and-hold over the same window (161.9%
   total return per `backtest-findings.md`) — is this exit rule actually
   competitive, or worse than doing nothing?

*Acceptance:* a written verdict, in the same document this backtest run
produces, stating explicitly whether each of the four runs passes or
fails each of the five checks above. **Phase 2 (§5 onward) MUST NOT be
started until this verdict exists and at least one of the four runs
passes all five.**

*Status:* Proposed — this is the requirement that determines whether
anything in §5 gets built at all.

---

### FR-19.8 — Re-entry cooldown (resolved)

The system MUST prevent a token from re-entering within a configurable
number of trading sessions after it exits under `exit_rule="tiered_trailing"`,
whether the exit was a stop (profitable or not) or the conditional time
stop (FR-19.2). Applies to **any** exit under this rule, not only a
losing stop-out — a time-exit is functionally the same "this one didn't
resolve as hoped" event for cooldown purposes. Stated here as the
resolved interpretation of the operator's original "none this month once
stopped out," which named the stop case but didn't rule the time case in
or out.

**`BacktestConfig`** — add `reentry_cooldown_sessions: int | None = None`.
`None` reproduces current behaviour exactly (no cooldown ever applied) —
opt-in, like every other field in this addendum.

**`_simulate`** — add `last_exit_slot: dict[int, int] = {}` alongside the
existing `open_trades` / `closed` / `curve` local state, keyed by token,
valued by the session index (`slot`) at which the token last exited.
Populated immediately after `closed.append(trade)` in the exits block,
only when `tiered and config.reentry_cooldown_sessions is not None`.
Consulted in the entries block, immediately after the existing
`if token in open_trades: continue` guard:

```python
if (
    tiered
    and config.reentry_cooldown_sessions is not None
    and token in last_exit_slot
    and (slot - last_exit_slot[token]) < config.reentry_cooldown_sessions
):
    continue
```

Sessions, not calendar days — consistent with `max_holding_days` and
every other period in this engine (FR-6.1). "This month" is therefore
operationalised as 21 sessions to match `max_holding_days`'s own value in
FR-19.4's runs, not as a calendar-month boundary; the field is a plain
session count so the operator can set it independently if 21 turns out to
be the wrong number once real results exist.

Deliberately tracked as local state inside `_simulate`, not as a field on
`Trade` or a second dict threaded through the function signature — every
other piece of state a cooldown check needs (`open_trades`, `cash`,
which `slot` is current) already lives at exactly this level, and a
closed `Trade` record has no other reason to be consulted again once its
exit is recorded.

*Acceptance:*
- A token stopped out (or time-exited) at slot N with
  `reentry_cooldown_sessions=21` does not reopen before slot N+21, even
  if it reappears in `entry_signals` on every intervening session. Named
  test `test_reentry_cooldown_blocks_until_session_count_elapses`.
- The same token DOES reopen at slot N+21 or later, given a qualifying
  signal. Named test `test_reentry_cooldown_expires_exactly_at_the_boundary`.
- `reentry_cooldown_sessions=None` (the default) reproduces byte-identical
  output to a run with no cooldown logic at all — folded into the same
  no-op regression test as FR-19.1's default-fields check.
- A cooldown fired under `exit_rule="atr_trailing"` MUST NOT occur — the
  `tiered` guard means `last_exit_slot` is never populated for a legacy
  run, so this is structurally guaranteed rather than merely tested, but
  a test exists anyway: `test_cooldown_is_inert_under_atr_trailing`.

*Status:* Proposed

---

## 4. Code appendix

### 4a. Full replacement — `backend/alpha500/backtest/engine.py`

Implements FR-19.1, FR-19.2 and FR-19.8 in full. Syntax-checked
(`python -m py_compile`) but **not run against real data** — no access to
the actual DuckDB store existed when this was written. Run the existing
test suite (`pytest backend/tests -q`, should stay at 172+ passing) before
trusting it, per NFR-5.1's own standard.

```python
"""Point-in-time backtest simulation (SRS Phase 3).

The rules that matter, and why:

* **Entry on the next session's open.** A signal computed from session T's close
  could not have been acted on at that close. Entering at T's close is the most
  common way a backtest invents returns that were never available.
* **Metrics are read as of the signal date only.** ``metrics_daily`` at date T
  is a function of prices up to T, so no row can see its own future.
* **Long only** (FR-12.2), **cash only** (FR-12.3, no margin on NRI accounts),
  and **no exit before settlement** (FR-12.1, delivery-based trading -- intraday
  and BTST are not permitted).
* **Friction on both legs**, plus TDS withheld from each profitable exit at
  settlement rather than at filing (FR-12.4).

What this engine cannot fix is stated loudly rather than hidden: see
``survivorship_warnings``.

---

**2026-09 addition -- tiered trailing-stop exit rule.**

Everything below this note is new, added to support a 5-10% swing-trade
strategy with its own risk management, distinct from the ATR-chandelier
trailing stop the rest of the system uses. It is **entirely opt-in**: every
new ``BacktestConfig`` field defaults to a value that reproduces the previous
behaviour exactly, so no existing config (Momentum Leaders, Pullback +
Reversal with the Momentum Breakdown exit screen, etc.) changes unless it
explicitly sets ``exit_rule="tiered_trailing"``.

Rule, as specified by the operator:

* **Initial stop** (before the trade has ever been up 5%):
  ``support_level - initial_stop_atr_multiple * ATR14``, evaluated once at
  entry from the prior session's values -- the same no-lookahead convention
  the rest of the engine already uses for the ATR-based stop.
* **Stage 1** (peak unrealised gain >= ``stage1_arm_pct``, default 5%): stop
  trails at ``peak_gain - stage1_giveback_pct`` (default 4 percentage points)
  behind the highest close-based gain seen since entry.
* **Stage 2** (peak unrealised gain >= ``stage2_arm_pct``, default 10%): stop
  trails tighter, at ``peak_gain - stage2_giveback_pct`` (default 2 points).
* The three candidate stops (initial, stage 1, stage 2) are combined with
  ``max()`` every session, so the stop is monotonically non-decreasing and a
  stage never un-arms once reached, even if price pulls back below that
  stage's arming threshold afterwards.
* **Time stop**, when ``time_stop_only_if_not_profitable`` is True (it is
  False by default, matching the old unconditional behaviour): the
  ``max_holding_days`` exit only fires if the position is flat or losing at
  that point (``open_px / entry_price - 1 <= 0``). A profitable position past
  the time limit is left for the trailing stop to govern instead.
* **Re-entry cooldown**, when ``reentry_cooldown_sessions`` is set (default
  None, no cooldown, old behaviour): once a token exits under this rule --
  by the stop or the time branch, either counts -- it cannot re-enter for
  that many *sessions* (not calendar days, per the engine's existing FR-6.1
  convention). Tracked as ``last_exit_slot: dict[token, slot]`` inside
  ``_simulate`` rather than as a field on ``Trade``, since a closed trade's
  own record has no further reason to be inspected once the cooldown check
  is what needs answering, and every other cooldown-relevant piece of state
  already lives at the ``_simulate`` level (``open_trades``, ``cash``, etc).

The exit-detection line itself -- ``if low <= trade.stop_price`` -- is
unchanged. Only how ``stop_price`` is initialised and updated changes, which
is deliberately the smallest change that implements the new rule on a system
already relied on for other, unrelated backtests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Sequence

import duckdb
import numpy as np

from alpha500.backtest.stats import Summary, summarise
from alpha500.risk import CostModel, earliest_sellable_date
from alpha500.screens.filter_engine import compile_screen


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    screen: dict[str, Any]
    start: date
    end: date
    initial_capital: float = 1_000_000.0
    max_positions: int = 10
    risk_per_trade_pct: float = 0.0075
    max_position_weight: float = 0.10
    stop_atr_multiple: float = 2.0
    trailing_stop: bool = True
    max_holding_days: int | None = None
    slippage_pct: float = 0.0015
    cost_model: CostModel = field(default_factory=CostModel)
    exit_screen: dict[str, Any] | None = None

    # -- 2026-09 tiered trailing-stop exit rule (opt-in; see module docstring) --
    exit_rule: str = "atr_trailing"  # "atr_trailing" (legacy, default) | "tiered_trailing"
    initial_stop_atr_multiple: float = 0.5  # support_level - this * ATR14, tiered_trailing only
    stage1_arm_pct: float = 0.05
    stage1_giveback_pct: float = 0.04
    stage2_arm_pct: float = 0.10
    stage2_giveback_pct: float = 0.02
    time_stop_only_if_not_profitable: bool = False  # default preserves old unconditional time-stop
    reentry_cooldown_sessions: int | None = None  # None = no cooldown (old behaviour); tiered_trailing only


@dataclass(slots=True)
class Trade:
    token: int
    symbol: str
    entry_date: date
    entry_price: float
    quantity: int
    stop_price: float
    sellable_from: date
    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    costs: float = 0.0
    tds: float = 0.0
    peak_gain_pct: float = 0.0  # high-water mark of close-based unrealised gain; tiered_trailing only

    @property
    def holding_days(self) -> int:
        if self.exit_date is None:
            return 0
        return (self.exit_date - self.entry_date).days

    @property
    def gross_pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.quantity

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.costs - self.tds

    @property
    def net_return_pct(self) -> float:
        cost_basis = self.entry_price * self.quantity
        return (self.net_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date.isoformat(),
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "holding_days": self.holding_days,
            "peak_gain_pct": self.peak_gain_pct * 100.0,
            "gross_pnl": self.gross_pnl,
            "costs": self.costs,
            "tds": self.tds,
            "net_pnl": self.net_pnl,
            "net_return_pct": self.net_return_pct,
        }


@dataclass(slots=True)
class BacktestResult:
    summary: Summary
    trades: list[Trade]
    equity_gross: list[float]
    equity_net: list[float]
    sessions: list[date]

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.summary.as_dict(),
            "trades_detail": [t.as_dict() for t in self.trades],
            "equity_curve": [
                {"date": d.isoformat(), "gross": g, "net": n}
                for d, g, n in zip(self.sessions, self.equity_gross, self.equity_net)
            ],
        }


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def _sessions(conn: duckdb.DuckDBPyConnection, start: date, end: date) -> list[date]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT trade_date FROM metrics_daily "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [start, end],
        ).fetchall()
    ]


def signals_over_range(
    conn: duckdb.DuckDBPyConnection,
    definition: dict[str, Any],
    start: date,
    end: date,
) -> dict[date, list[tuple[int, str, float | None]]]:
    """Screen matches for every session in one query.

    Running the screen once per session would issue 1 200+ round trips per
    parameter combination, which makes walk-forward evaluation impractical.
    """
    compiled = compile_screen(definition)
    sort_field = definition.get("sort", [{}])[0].get("field") or "momentum_score"

    sql = f"""
        SELECT m.trade_date, m.instrument_token, i.tradingsymbol, m.{sort_field}
          FROM metrics_daily m
          JOIN instruments i ON i.instrument_token = m.instrument_token
         WHERE m.trade_date BETWEEN ? AND ? AND ({compiled.where_sql})
         ORDER BY m.trade_date, m.{sort_field} DESC NULLS LAST
    """
    rows = conn.execute(sql, [start, end, *compiled.params]).fetchall()

    out: dict[date, list[tuple[int, str, float | None]]] = {}
    for trade_date, token, symbol, score in rows:
        out.setdefault(trade_date, []).append((int(token), str(symbol), score))

    limit = definition.get("limit")
    if limit:
        for day, matches in out.items():
            out[day] = matches[: int(limit)]
    return out


def _price_panel(
    conn: duckdb.DuckDBPyConnection, start: date, end: date
) -> tuple[dict[int, dict[str, np.ndarray]], dict[date, int]]:
    """Adjusted OHLC per token, aligned to a shared session index.

    2026-09: also loads ``support_level`` (already computed in adjusted-price
    terms by the metric engine, so no adj_factor multiplication is applied to
    it) for the tiered_trailing initial stop.
    """
    sessions = _sessions(conn, start, end)
    index = {day: i for i, day in enumerate(sessions)}

    rows = conn.execute(
        """
        SELECT o.instrument_token, o.trade_date,
               o.open * o.adj_factor, o.high * o.adj_factor,
               o.low * o.adj_factor, o.close * o.adj_factor,
               m.atr_14, m.support_level
          FROM ohlcv_daily o
          JOIN metrics_daily m
            ON m.instrument_token = o.instrument_token AND m.trade_date = o.trade_date
         WHERE o.trade_date BETWEEN ? AND ?
         ORDER BY o.instrument_token, o.trade_date
        """,
        [start, end],
    ).fetchall()

    n = len(sessions)
    panel: dict[int, dict[str, np.ndarray]] = {}
    for token, day, op, hi, lo, cl, atr, support in rows:
        token = int(token)
        slot = index.get(day)
        if slot is None:
            continue
        arrays = panel.get(token)
        if arrays is None:
            arrays = {
                name: np.full(n, np.nan)
                for name in ("open", "high", "low", "close", "atr", "support")
            }
            panel[token] = arrays
        arrays["open"][slot] = op if op is not None else np.nan
        arrays["high"][slot] = hi if hi is not None else np.nan
        arrays["low"][slot] = lo if lo is not None else np.nan
        arrays["close"][slot] = cl if cl is not None else np.nan
        arrays["atr"][slot] = atr if atr is not None else np.nan
        arrays["support"][slot] = support if support is not None else np.nan
    return panel, index


# --------------------------------------------------------------------------
# Cost model
# --------------------------------------------------------------------------

def _entry_costs(value: float, model: CostModel) -> float:
    brokerage = value * model.brokerage_pct + model.brokerage_flat_inr
    charges = value * (model.exchange_txn_pct + model.sebi_fee_pct)
    stamp = value * model.stamp_duty_buy_pct
    gst = (brokerage + charges) * model.gst_pct
    return brokerage + charges + stamp + gst


def _exit_costs(value: float, model: CostModel) -> float:
    brokerage = value * model.brokerage_pct + model.brokerage_flat_inr
    charges = value * (model.exchange_txn_pct + model.sebi_fee_pct)
    stt = value * model.stt_sell_pct
    gst = (brokerage + charges) * model.gst_pct
    return brokerage + charges + stt + gst


def _withholding(trade: Trade, model: CostModel) -> float:
    """TDS on the realised gain, withheld at settlement (FR-12.4).

    Only profitable exits are withheld from, and the rate depends on whether
    the holding crossed twelve months.
    """
    gain = trade.gross_pnl - trade.costs
    if gain <= 0:
        return 0.0
    rate = (
        model.ltcg_effective_rate
        if trade.holding_days >= 365
        else model.stcg_effective_rate
    )
    return gain * rate


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def survivorship_warnings(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """State plainly what the available data cannot support.

    FR-13 (Phase 3) requires point-in-time universe reconstruction from
    ``index_membership``, because "a backtest run on today's constituent list
    is worthless and worse than no backtest, since it produces confident wrong
    numbers". That warning is aimed squarely at this situation, so the result
    carries it rather than burying it.
    """
    warnings: list[str] = []
    row = conn.execute(
        "SELECT count(DISTINCT valid_from), count(*) FILTER (WHERE valid_to IS NOT NULL) "
        "FROM index_membership"
    ).fetchone()
    distinct_starts, closed = (row or (0, 0))

    if distinct_starts <= 1 and not closed:
        warnings.append(
            "SURVIVORSHIP BIAS: index_membership holds a single snapshot with no "
            "closed intervals, so the universe cannot be reconstructed as it stood "
            "on any past date. Every symbol tested is a *current* NIFTY 500 member; "
            "constituents that were dropped over the period were never ingested at "
            "all. Results are biased upward by an unknown but material amount and "
            "MUST NOT be read as achievable returns."
        )
    return warnings


def run_backtest(
    conn: duckdb.DuckDBPyConnection, config: BacktestConfig
) -> BacktestResult:
    """Simulate the strategy twice: with TDS withheld, and without.

    The two runs cannot be derived from one another. Withholding takes cash out
    at each profitable exit, so the net path compounds on a smaller base and
    subsequently sizes smaller positions -- it does not merely lag the gross
    path by the tax paid. Reconstructing one curve by adding cumulative tax
    back to the other understates the untaxed path and, worse, produces a
    drawdown profile that belongs to neither.
    """
    sessions = _sessions(conn, config.start, config.end)
    if len(sessions) < 2:
        raise ValueError(
            f"Need at least two sessions of materialised metrics between "
            f"{config.start} and {config.end}; found {len(sessions)}. "
            "Run 'alpha500 materialise' first."
        )

    entry_signals = signals_over_range(conn, config.screen, config.start, config.end)
    exit_signals = (
        signals_over_range(conn, config.exit_screen, config.start, config.end)
        if config.exit_screen
        else {}
    )
    panel, _index = _price_panel(conn, config.start, config.end)

    net_equity, trades, exposure = _simulate(
        config, sessions, entry_signals, exit_signals, panel, withhold_tax=True
    )
    gross_equity, _gross_trades, _gross_exposure = _simulate(
        config, sessions, entry_signals, exit_signals, panel, withhold_tax=False
    )

    summary = summarise(
        gross_equity=gross_equity,
        net_equity=net_equity,
        sessions=sessions,
        trades=trades,
        exposure_samples=exposure,
        initial=config.initial_capital,
        warnings=survivorship_warnings(conn),
    )
    return BacktestResult(summary, trades, gross_equity, net_equity, sessions)


def _simulate(
    config: BacktestConfig,
    sessions: list[date],
    entry_signals: dict[date, list[tuple[int, str, float | None]]],
    exit_signals: dict[date, list[tuple[int, str, float | None]]],
    panel: dict[int, dict[str, np.ndarray]],
    withhold_tax: bool,
) -> tuple[list[float], list[Trade], list[float]]:
    model = config.cost_model
    tiered = config.exit_rule == "tiered_trailing"

    cash = config.initial_capital
    tax_paid = 0.0
    open_trades: dict[int, Trade] = {}
    closed: list[Trade] = []
    curve: list[float] = []
    exposure: list[float] = []
    # Sessions-based, not calendar-based, per the engine's existing FR-6.1
    # convention. Populated on every exit while tiered_trailing is active;
    # checked at entry. None/absent means no cooldown ever applied to that
    # token, so a config with reentry_cooldown_sessions=None never consults
    # this at all.
    last_exit_slot: dict[int, int] = {}

    def mark_to_market(slot: int) -> float:
        total = 0.0
        for token, trade in open_trades.items():
            arrays = panel.get(token)
            price = arrays["close"][slot] if arrays is not None else np.nan
            if not np.isfinite(price):
                price = trade.entry_price
            total += price * trade.quantity
        return total

    exit_token_sets = {
        day: {token for token, _symbol, _score in matches}
        for day, matches in exit_signals.items()
    }

    for slot, session in enumerate(sessions):
        previous_session = sessions[slot - 1] if slot > 0 else None
        exit_tokens_prev: set[int] = (
            exit_token_sets.get(previous_session, set())
            if previous_session is not None
            else set()
        )

        # ---- exits, evaluated before new entries so capital recycles -----
        for token in list(open_trades):
            trade = open_trades[token]
            arrays = panel.get(token)
            if arrays is None:
                continue
            low = arrays["low"][slot]
            open_px = arrays["open"][slot]
            close_px = arrays["close"][slot]
            if not np.isfinite(close_px):
                continue

            # FR-12.1: delivery-based only; nothing may be sold before credit.
            if session < trade.sellable_from:
                continue

            reason: str | None = None
            fill: float | None = None

            if np.isfinite(low) and low <= trade.stop_price:
                # A gap through the stop fills at the open, not at the stop.
                fill = min(open_px, trade.stop_price) if np.isfinite(open_px) else trade.stop_price
                reason = "stop"
            elif previous_session is not None and token in exit_tokens_prev:
                # The exit screen is computed from a session's close, so it can
                # only be acted on at the next open -- the same rule that governs
                # entries. Selling at the close that produced the signal would
                # be look-ahead, and it flatters every exit.
                if not np.isfinite(open_px):
                    continue
                fill = open_px
                reason = "exit_signal"
            elif (
                config.max_holding_days is not None
                and (session - trade.entry_date).days >= config.max_holding_days
                and np.isfinite(open_px)
                and (
                    not config.time_stop_only_if_not_profitable
                    or (open_px / trade.entry_price - 1.0) <= 0.0
                )
            ):
                # time_stop_only_if_not_profitable=True: a position that is
                # still profitable past the time limit is deliberately left
                # for the trailing stop to close out instead of forcing an
                # exit here. Default False reproduces the old, unconditional
                # behaviour for every config that doesn't opt in.
                fill = open_px
                reason = "time"

            if reason is None or fill is None:
                if tiered:
                    gain_pct = close_px / trade.entry_price - 1.0
                    if gain_pct > trade.peak_gain_pct:
                        trade.peak_gain_pct = gain_pct
                    candidates = [trade.stop_price]
                    if trade.peak_gain_pct >= config.stage1_arm_pct:
                        candidates.append(
                            trade.entry_price
                            * (1.0 + trade.peak_gain_pct - config.stage1_giveback_pct)
                        )
                    if trade.peak_gain_pct >= config.stage2_arm_pct:
                        candidates.append(
                            trade.entry_price
                            * (1.0 + trade.peak_gain_pct - config.stage2_giveback_pct)
                        )
                    trade.stop_price = max(candidates)
                elif config.trailing_stop and np.isfinite(arrays["atr"][slot]):
                    trailed = close_px - config.stop_atr_multiple * arrays["atr"][slot]
                    trade.stop_price = max(trade.stop_price, trailed)
                continue

            fill_price = float(fill) * (1.0 - config.slippage_pct)
            proceeds = fill_price * trade.quantity
            trade.exit_date = session
            trade.exit_price = fill_price
            trade.exit_reason = reason
            exit_cost = _exit_costs(proceeds, model)
            trade.costs += exit_cost
            trade.tds = _withholding(trade, model) if withhold_tax else 0.0

            # FR-12.4: withholding leaves the account at settlement, so it is
            # deducted from cash here rather than accrued for year-end.
            cash += proceeds - exit_cost - trade.tds
            tax_paid += trade.tds
            closed.append(trade)
            del open_trades[token]
            if tiered and config.reentry_cooldown_sessions is not None:
                last_exit_slot[token] = slot

        # ---- entries: yesterday's signal, filled at today's open ---------
        if slot > 0 and len(open_trades) < config.max_positions:
            previous = sessions[slot - 1]
            for token, symbol, _score in entry_signals.get(previous, []):
                if len(open_trades) >= config.max_positions:
                    break
                if token in open_trades:
                    continue
                if (
                    tiered
                    and config.reentry_cooldown_sessions is not None
                    and token in last_exit_slot
                    and (slot - last_exit_slot[token]) < config.reentry_cooldown_sessions
                ):
                    continue
                arrays = panel.get(token)
                if arrays is None:
                    continue
                open_px = arrays["open"][slot]
                atr = arrays["atr"][slot - 1]

                if tiered:
                    support = arrays["support"][slot - 1]
                    if (
                        not np.isfinite(open_px)
                        or open_px <= 0
                        or not np.isfinite(atr)
                        or not np.isfinite(support)
                    ):
                        continue
                    fill_price = open_px * (1.0 + config.slippage_pct)
                    stop = support - config.initial_stop_atr_multiple * atr
                else:
                    if not np.isfinite(open_px) or open_px <= 0 or not np.isfinite(atr):
                        continue
                    fill_price = open_px * (1.0 + config.slippage_pct)
                    stop = fill_price - config.stop_atr_multiple * atr

                if stop <= 0 or stop >= fill_price:
                    continue

                equity_now = cash + mark_to_market(slot)
                risk_amount = equity_now * config.risk_per_trade_pct
                quantity = math.floor(risk_amount / (fill_price - stop))
                max_value = equity_now * config.max_position_weight
                if quantity * fill_price > max_value:
                    quantity = math.floor(max_value / fill_price)
                if quantity <= 0:
                    continue

                cost_basis = quantity * fill_price
                entry_cost = _entry_costs(cost_basis, model)
                # FR-12.3: cash only. No position may be funded on margin.
                if cost_basis + entry_cost > cash:
                    quantity = math.floor((cash - entry_cost) / fill_price)
                    if quantity <= 0:
                        continue
                    cost_basis = quantity * fill_price
                    entry_cost = _entry_costs(cost_basis, model)
                    if cost_basis + entry_cost > cash:
                        continue

                cash -= cost_basis + entry_cost
                open_trades[token] = Trade(
                    token=token,
                    symbol=symbol,
                    entry_date=session,
                    entry_price=fill_price,
                    quantity=quantity,
                    stop_price=stop,
                    sellable_from=earliest_sellable_date(session),
                    costs=entry_cost,
                )

        held = mark_to_market(slot)
        equity = cash + held
        curve.append(equity)
        exposure.append(held / equity if equity > 0 else 0.0)

    return curve, closed, exposure
```

### 4b. Standalone runner — `scripts/run_swing_backtest.py`

Executes FR-19.4's four runs, including the cooldown. Imports the real,
live presets directly (`from alpha500.screens.presets import get_preset`)
rather than reconstructing screen definitions — see the correction in §2.
Superseded once FR-19.3's CLI flags exist; kept as a way to test
FR-19.1/19.2/19.8 before touching `cli.py`, or as a permanent alternative
if you'd rather not.

```python
"""Ad-hoc backtest: the 5-10% swing strategy, tiered trailing-stop exit.

Imports the REAL, live preset definitions directly from
alpha500.screens.presets rather than reconstructing them -- eliminates any
risk of testing a screen definition that doesn't match what's actually
registered. Runs Pullback + Reversal and Fibonacci Reversal Zone, each at
max_positions 2 and 3 (four runs total).

Superseded once FR-19.3's CLI flags exist -- at that point the four runs
below are just:

    alpha500 backtest "Pullback + Reversal" --exit-rule tiered_trailing \
        --max-holding-days 21 --time-stop-conditional --max-positions 2
    ...(repeat for max-positions 3, and for "Fibonacci Reversal Zone")

Keep this script only as a way to test FR-19.1/19.2 before FR-19.3 is wired,
or if you'd rather not touch cli.py at all.

Usage (from the project root, with the venv active):
    .venv/Scripts/python scripts/run_swing_backtest.py

Stop the API first if it's running with --with-scheduler (D-6).
"""

from __future__ import annotations

import json
import os
from datetime import date

import duckdb

from alpha500.backtest.engine import BacktestConfig, run_backtest
from alpha500.screens.presets import get_preset

DB_PATH = r"C:\StockDashboard\data\alpha500.duckdb"
OUTPUT_DIR = "exports"

START = date(2019, 8, 30)   # first session any stock is eligible (D-9)
END = date(2026, 8, 27)     # matches backtest-findings.md's window


def make_config(screen_name: str, max_positions: int) -> BacktestConfig:
    return BacktestConfig(
        screen=get_preset(screen_name),   # the real, live preset -- not reconstructed
        start=START,
        end=END,
        max_positions=max_positions,
        max_holding_days=21,
        exit_rule="tiered_trailing",
        initial_stop_atr_multiple=0.5,
        stage1_arm_pct=0.05,
        stage1_giveback_pct=0.04,
        stage2_arm_pct=0.10,
        stage2_giveback_pct=0.02,
        time_stop_only_if_not_profitable=True,
        reentry_cooldown_sessions=21,  # "no re-entry this month" -- see FR-19.8
        exit_screen=None,  # the tiered stop is the only exit; see Decision 3
    )


def fmt(value, suffix: str = "%", decimals: int = 2) -> str:
    return f"{value:.{decimals}f}{suffix}" if value is not None else "n/a"


def report(label: str, result) -> None:
    s = result.summary
    print(f"\n=== {label} ===")
    print(f"Sessions: {s.sessions}  ({s.start} -> {s.end})")
    print(f"Net CAGR:         {fmt(s.net.cagr_pct)}")
    print(f"Net total return: {fmt(s.net.total_return_pct)}")
    print(f"Max drawdown:     {fmt(s.net.max_drawdown_pct)}  ({s.net.max_drawdown_days} sessions)")
    print(f"Sharpe (net):     {fmt(s.net.sharpe, suffix='', decimals=3)}")
    print(f"Trades:           {s.trades.trades}")
    print(f"Hit rate:         {fmt(s.trades.hit_rate_pct)}")
    print(f"Avg win:          {fmt(s.trades.avg_win_pct)}")
    print(f"Avg loss:         {fmt(s.trades.avg_loss_pct)}")
    print(f"Win/loss ratio:   {fmt(s.trades.win_loss_ratio, suffix='', decimals=2)}")
    print(f"Avg hold (days):  {fmt(s.trades.avg_holding_days, suffix='', decimals=1)}")
    print(f"Exposure:         {fmt(s.trades.exposure_pct)}")
    print(f"Total TDS:        Rs.{s.trades.total_tds:,.0f}")
    if s.trades.trades < 30:
        print(f"  !! Only {s.trades.trades} closed trades -- too small a sample to trust a hit rate or avg win/loss from.")
    if s.warnings:
        print("WARNINGS:")
        for w in s.warnings:
            print(f"  - {w}")


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        for screen_name in ("Pullback + Reversal", "Fibonacci Reversal Zone"):
            for max_pos in (2, 3):
                config = make_config(screen_name, max_pos)
                result = run_backtest(conn, config)
                label = f"{screen_name} -- max_positions={max_pos}"
                report(label, result)

                safe_name = screen_name.split()[0].lower()
                out_path = os.path.join(OUTPUT_DIR, f"swing_backtest_{safe_name}_{max_pos}.json")
                try:
                    with open(out_path, "w") as f:
                        json.dump(result.as_dict(), f, indent=2, default=str)
                    print(f"Full trade log: {out_path}")
                except OSError as exc:
                    print(f"Could not write {out_path}: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

---

## 5. Phase 2 — Dashboard screen (blocked on FR-19.4)

Deliberately left at requirement-sketch depth, not implementation depth —
writing this to Phase 1's precision before Phase 1's gate has cleared
would be exactly the "confident wrong numbers" failure mode DECISIONS.md
warns about, applied to a UI instead of a backtest.

**FR-19.5 — Swing Trade Candidates screen.** Once gated open: a tenth
screen (or an annotated view over the existing `Pullback + Reversal` /
`Fibonacci Reversal Zone` results — decide which once FR-19.4's winning
run is known) showing, per candidate: current stage (0/1/2 per FR-19.1),
today's computed stop price and distance to it, days held against the
21-session limit, and — new since FR-19.8 — whether the symbol is
currently in cooldown from a prior exit this month, so a candidate that
re-triggers mid-cooldown is shown as blocked rather than silently absent.

**FR-19.6 — Dashboard section.** Surfaced the way `Momentum Breakdown`
already outranks entries (FR-7.6) — an open position approaching its time
limit while unprofitable is exit-relevant information and belongs with
comparable prominence, not buried in a generic grid.

**FR-19.7 — Position sizing.** Explicitly NOT specified here (Decision 5).
Reuses `risk.py`'s existing `size_position()` and `suggest_stop()` once
the operator supplies real `risk_per_trade_pct` / `max_position_weight`
values — this addendum does not invent numbers for that.

*Status, all of FR-19.5–19.7:* Proposed, blocked on FR-19.4.

---

## 6. Schema delta

```sql
-- No metrics_daily changes. support_level already exists (FR-14.2).
-- All Phase 1 changes are to BacktestConfig/Trade (Python dataclasses,
-- not DuckDB tables) and to the CLI argument parser.
```

## 7. Test plan

1. `test_tiered_trailing_fields_are_a_no_op_by_default` — the regression
   test that matters most; covers FR-19.1, FR-19.2 and FR-19.8 defaults
   together, since all three are opt-in off the same `exit_rule` switch.
2. `test_tiered_stop_never_unarms`,
   `test_tiered_stop_stage2_is_tighter_than_stage1`,
   `test_tiered_entry_skips_null_support` — FR-19.1.
3. `test_conditional_time_stop_spares_profitable_positions`, plus its
   mirror confirming a flat/losing position IS closed — FR-19.2.
4. `test_reentry_cooldown_blocks_until_session_count_elapses`,
   `test_reentry_cooldown_expires_exactly_at_the_boundary`,
   `test_cooldown_is_inert_under_atr_trailing` — FR-19.8.
5. CLI smoke test: `alpha500 backtest "Pullback + Reversal" --exit-rule
   tiered_trailing` exits 0 — FR-19.3.
6. The four FR-19.4 runs, committed to the repo as their own findings
   document (`docs/swing-backtest-findings.md`, matching the existing
   `backtest-findings.md` convention) once run — not just printed to a
   terminal and lost.

## 8. Open questions

| # | Question | Owner | Needed by |
|---|---|---|---|
| Q-5 | The cooldown stands a token down after a *profitable* stop-out as readily as a losing one — 449 of 1,675 exits in the gate runs. Should a setup that paid out be stood down at all? Raised by Q-4's resolution; no run isolates it | Operator | Only if a swing screen is revived |
| Q-2 | Position sizing real values (Decision 5, FR-19.7) | Operator | Before Phase 2, not before Phase 1 |
| Q-3 | If more than one of the four FR-19.4 runs passes the gate, which becomes the one dashboard screen — best CAGR, best Sharpe, most trades (statistical confidence), or does each become its own screen? | Operator | After FR-19.4's results exist, not before |
| Q-4 | ~~FR-19.8 applies the cooldown to time-exits as well as stops~~ | **Resolved 2026-09-10** | — |

*(Q-1, the original re-entry-cooldown open question, is resolved as
FR-19.8 above and removed from this table.)*

**Q-4, as resolved.** The interpretation stands: the cooldown applies to any
exit under this rule, time exits included. It is not a judgement call, because
FR-19.2 decides it. With `time_stop_only_if_not_profitable` set - which
FR-19.4's runs require - the time branch fires only when the position is flat
or losing, so a time exit is a failed setup by construction. Measured across
both Pullback runs, **42 of 42 time exits were losses, none profitable**.
Exempting them would re-admit a name that had just spent 21 sessions failing
to get into profit, which is the opposite of what the cooldown is for.

The case that *is* debatable turns out to be a different one, and the same
numbers surface it: 449 of 1,675 exits were **profitable** stop-outs, where the
trail fired after a gain. The cooldown blocks those re-entries too. Whether a
name that just paid out should be stood down for 21 sessions is a real
question, but it is not Q-4 and no run to date isolates it. Filed as Q-5
rather than folded into this answer.

## 9. Change log entry (append to URD.md §9 once merged)

| Date | Change | Requirements |
|---|---|---|
| 2026-09-09 | Swing-trade tiered trailing-stop exit rule with re-entry cooldown, opt-in on the backtest engine; Phase 2 dashboard screen specified but gated on backtest proof | FR-19.1–19.8 |
