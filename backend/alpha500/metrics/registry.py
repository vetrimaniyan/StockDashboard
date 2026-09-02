"""Metric registry.

NFR-3.2: metric definitions live here so adding one needs no change to the API
layer or the grid component.

NFR-5.6: ``METRICS.md`` is generated from this table, so documentation cannot
drift from implementation.

FR-8.10: the UI reads formulas from here. A number whose formula the operator
cannot recall is a number they will misuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class MetricDef:
    name: str
    label: str
    formula: str
    description: str
    group: str
    unit: str = "number"  # number | percent | currency | ratio | integer | boolean
    higher_is_better: bool | None = None


def _m(*args: object, **kwargs: object) -> MetricDef:
    return MetricDef(*args, **kwargs)  # type: ignore[arg-type]


REGISTRY: Final[tuple[MetricDef, ...]] = (
    # --- returns ---------------------------------------------------------
    _m("ret_1d", "1-day return", "C_0 / C_1 - 1",
       "Latest session's price change.", "Returns", "percent", True),
    _m("ret_1w", "1-week return", "C_0 / C_5 - 1",
       "Return over the last 5 trading sessions.", "Returns", "percent", True),
    _m("ret_2w", "2-week return", "C_0 / C_10 - 1",
       "Return over the last 10 trading sessions.", "Returns", "percent", True),
    _m("ret_3w", "3-week return", "C_0 / C_15 - 1",
       "Return over the last 15 trading sessions.", "Returns", "percent", True),
    _m("ret_1m", "1-month return", "C_0 / C_21 - 1",
       "Return over the last 21 trading sessions.", "Returns", "percent", True),
    _m("ret_2m", "2-month return", "C_0 / C_42 - 1",
       "Return over the last 42 trading sessions. A lookback to a single point "
       "42 sessions ago - not to be confused with ret_3m_2m, which measures an "
       "interval.", "Returns", "percent", True),
    _m("ret_3m_2m", "2-to-3-month return", "C_42 / C_63 - 1",
       "Return earned *across* the interval from 63 sessions ago to 42 sessions "
       "ago. Answers 'how did it do during that month', where ret_2m answers "
       "'how far is it above where it stood then'.", "Returns", "percent", True),
    _m("ret_3m", "3-month return", "C_0 / C_63 - 1",
       "Return over the last 63 trading sessions.", "Returns", "percent", True),
    _m("ret_6m", "6-month return", "C_0 / C_126 - 1",
       "Return over the last 126 trading sessions.", "Returns", "percent", True),
    _m("ret_9m", "9-month return", "C_0 / C_189 - 1",
       "Return over the last 189 trading sessions.", "Returns", "percent", True),
    _m("ret_12m", "12-month return", "C_0 / C_252 - 1",
       "Return over the last 252 sessions. Reference only — the composite uses "
       "ret_12m_1m instead.", "Returns", "percent", True),
    _m("ret_12m_1m", "12m-1m return", "C_21 / C_252 - 1",
       "Medium-term momentum with the most recent month skipped. Short-horizon "
       "reversal is well documented: stocks that ran hardest in the last 21 "
       "sessions tend to give some of it back, so including that month "
       "contaminates the signal.", "Returns", "percent", True),

    # --- relative strength -----------------------------------------------
    _m("rs_1m", "RS 1m", "(1 + ret_1m) / (1 + index_ret_1m) - 1",
       "1-month performance relative to the NIFTY 500.", "Relative strength",
       "percent", True),
    _m("rs_3m", "RS 3m", "(1 + ret_3m) / (1 + index_ret_3m) - 1",
       "3-month performance relative to the NIFTY 500.", "Relative strength",
       "percent", True),
    _m("rs_6m", "RS 6m", "(1 + ret_6m) / (1 + index_ret_6m) - 1",
       "6-month performance relative to the NIFTY 500.", "Relative strength",
       "percent", True),
    _m("rs_12m", "RS 12m", "(1 + ret_12m) / (1 + index_ret_12m) - 1",
       "12-month performance relative to the NIFTY 500.", "Relative strength",
       "percent", True),
    _m("rs_rating", "RS rating",
       "ceil(99 x percentile_rank(0.40*ret_3m + 0.20*ret_6m + 0.20*ret_9m + 0.20*ret_12m))",
       "Percentile 1-99 against the eligible universe. 99 means the stock "
       "outperformed 99% of it. Cross-sectional — recomputed for the whole "
       "universe every session.", "Relative strength", "integer", True),

    # --- momentum --------------------------------------------------------
    _m("exp_reg_slope_90", "Annualised slope", "exp(b x 252) - 1",
       "Annualised slope of an OLS fit of ln(close) on session index over the "
       "last 90 sessions.", "Momentum", "percent", True),
    _m("exp_reg_r2_90", "Trend R^2", "R^2 of the ln(close) regression",
       "How consistently the advance followed its trendline. Penalises choppy, "
       "gap-driven moves.", "Momentum", "ratio", True),
    _m("momentum_score", "Momentum score", "(exp(b x 252) - 1) x R^2",
       "Trend strength multiplied by trend consistency. A 60% slope at R^2 0.35 "
       "scores 0.21, below a 30% slope at R^2 0.90 scoring 0.27 — that ordering "
       "is intentional and is the point of the metric. Null when the gap "
       "disqualifier fires.", "Momentum", "number", True),
    _m("momentum_rank", "Momentum rank", "dense_rank(momentum_score DESC)",
       "1 = strongest in the eligible universe.", "Momentum", "integer", False),
    _m("composite_z", "Composite z", "sum of weighted z-scores of winsorised components",
       "Configurable blend of momentum, 12m-1m return, RS rating, 52-week range "
       "position, ATR% (negative weight) and relative volume.",
       "Momentum", "number", True),
    _m("gap_disqualified", "Gap disqualified",
       "any |ret_1d| > 15% within the 90-session lookback",
       "A one-off event move (block deal, court ruling, takeover bid) means the "
       "stock is not in a tradeable trend. Excluded from momentum ranking.",
       "Momentum", "boolean", False),

    # --- trend -----------------------------------------------------------
    _m("sma_20", "SMA 20", "mean(close, 20)", "20-session simple moving average.",
       "Trend", "currency"),
    _m("sma_50", "SMA 50", "mean(close, 50)", "50-session simple moving average.",
       "Trend", "currency"),
    _m("sma_100", "SMA 100", "mean(close, 100)", "100-session simple moving average.",
       "Trend", "currency"),
    _m("sma_150", "SMA 150", "mean(close, 150)", "150-session simple moving average.",
       "Trend", "currency"),
    _m("sma_200", "SMA 200", "mean(close, 200)", "200-session simple moving average.",
       "Trend", "currency"),
    _m("ema_21", "EMA 21", "EMA(close, 21), alpha = 2/22",
       "21-session exponential moving average.", "Trend", "currency"),
    _m("ema_50", "EMA 50", "EMA(close, 50), alpha = 2/51",
       "50-session exponential moving average.", "Trend", "currency"),
    _m("sma_200_slope_1m", "SMA200 slope",
       "sma_200_today / sma_200_21_sessions_ago - 1",
       "Direction of the long-term average over the last month.", "Trend",
       "percent", True),
    _m("ma_alignment", "MA alignment", "C_0 > sma_50 > sma_100 > sma_200",
       "Price and averages stacked in trend order.", "Trend", "boolean", True),
    _m("trend_template_score", "Trend template", "count of 8 criteria met",
       "0-8 structural uptrend quality. Shown as a partial score because a 7/8 "
       "stock approaching its eighth criterion is an actionable watchlist item "
       "that a binary flag would hide.", "Trend", "integer", True),
    _m("is_trend_template", "Trend template 8/8", "trend_template_score = 8",
       "All eight structural criteria met.", "Trend", "boolean", True),

    # --- 52-week ---------------------------------------------------------
    _m("high_52w", "52-week high", "max(High) over 252 sessions",
       "From intraday highs, not closes — using closes understates the range and "
       "produces false breakouts.", "52-week", "currency"),
    _m("low_52w", "52-week low", "min(Low) over 252 sessions",
       "From intraday lows, not closes.", "52-week", "currency"),
    _m("pct_from_52w_high", "% from 52w high", "C_0 / high_52w - 1",
       "Always <= 0; closer to zero is stronger.", "52-week", "percent", True),
    _m("pct_above_52w_low", "% above 52w low", "C_0 / low_52w - 1",
       "Distance above the 52-week low.", "52-week", "percent", True),
    _m("range_position_52w", "52w range position",
       "(C_0 - low_52w) / (high_52w - low_52w)",
       "0 = at the 52-week low, 1 = at the high.", "52-week", "ratio", True),
    _m("days_since_52w_high", "Days since 52w high",
       "sessions elapsed since high_52w was set",
       "0 means the high is today's bar.", "52-week", "integer", False),

    # --- period high -----------------------------------------------------
    _m("high_period", "Period high",
       "max(High) over all stored sessions before today",
       "Highest intraday high in this symbol's stored history, excluding "
       "today's bar. NOT an all-time high: the lookback is however much "
       "history was backfilled, which history_days reports per symbol. It is "
       "a true all-time high only for symbols listed inside that window.",
       "Period high", "currency"),
    _m("pct_from_period_high", "% from period high", "C_0 / high_period - 1",
       "Negative below the period high, 0 or above once today's close has "
       "taken it out. Read alongside history_days, which says how deep the "
       "high actually reaches.", "Period high", "percent", True),

    _m("is_long_term_uptrend", "Long-term uptrend",
       "C_0 > sma_200 AND sma_50 > sma_200",
       "The trend gate for pullback screens. Deliberately weaker than "
       "ma_alignment, which also requires price above the 50-day — a "
       "genuine retracement usually breaks that, so using it here would "
       "exclude the setups being looked for.", "Trend", "boolean", True),

    # --- Fibonacci retracement zone (FR-17) ------------------------------
    # Never described as "support" (FR-17.9). A level is support when buyers
    # have actually appeared there — that is support_level, built from real
    # swing lows. These are geometry projected onto a past advance.
    _m("fib_leg_low_price", "Leg low (A)", "low of the confirmed swing low A",
       "Start of the impulse leg the retracement is measured against.",
       "Fibonacci zone", "currency"),
    _m("fib_leg_high_price", "Leg high (B)", "high of the confirmed swing high B",
       "End of the impulse leg, and the target if price recovers it.",
       "Fibonacci zone", "currency"),
    _m("fib_leg_low_date", "Leg low date", "session A printed",
       "The session the swing low occurred, not the session it was knowable.",
       "Fibonacci zone", "date"),
    _m("fib_leg_high_date", "Leg high date", "session B printed",
       "The session the swing high occurred. Not tradeable then — see leg "
       "confirmed date.", "Fibonacci zone", "date"),
    _m("fib_leg_confirmed_date", "Leg confirmed", "B date + swing reach",
       "The session the leg first became usable. A centred fractal needs "
       "further sessions before it can be known, so screening against the "
       "leg high date instead is look-ahead bias — silent, because the screen "
       "still returns rows.", "Fibonacci zone", "date"),
    _m("fib_leg_amplitude_pct", "Leg amplitude", "(B - A) / A",
       "Size of the advance being retraced. Small legs produce levels too "
       "tight to trade against.", "Fibonacci zone", "percent", True),
    _m("fib_leg_sessions", "Leg length", "sessions from A to B",
       "Trading sessions, never calendar days (FR-6.1).",
       "Fibonacci zone", "integer"),
    _m("fib_level_382", "38.2% level", "B - 0.382 * (B - A)",
       "Shallowest of the four levels.", "Fibonacci zone", "currency"),
    _m("fib_level_500", "50% level", "B - 0.500 * (B - A)",
       "Half the advance given back. Upper edge of the zone — the HIGHER "
       "price of the two bounds.", "Fibonacci zone", "currency"),
    _m("fib_level_618", "61.8% level", "B - 0.618 * (B - A)",
       "Just under two-thirds given back. Lower edge of the zone — a deeper "
       "retracement is a LOWER price.", "Fibonacci zone", "currency"),
    _m("fib_level_786", "78.6% level", "B - 0.786 * (B - A)",
       "Default stop reference: below it the premise of the leg is gone.",
       "Fibonacci zone", "currency"),
    _m("fib_retracement_ratio", "Retracement", "(B - C_0) / (B - A)",
       "How much of the advance has been given back. Higher means deeper, "
       "i.e. cheaper — NOT stronger. Carries no weight in the setup score "
       "and is not a sort option: 58% is not evidence over 52%.",
       "Fibonacci zone", "ratio"),
    _m("fib_max_retracement", "Max retracement", "(B - min(Low since B)) / (B - A)",
       "Deepest point reached since B. A leg wicked to 0.72 and recovered to "
       "0.55 has been tested and held; one that never traded past 0.55 has "
       "not.", "Fibonacci zone", "ratio"),
    _m("in_fib_zone", "In zone", "level(0.618) <= C_0 <= level(0.500)",
       "Inclusive at both ends. A location, not an event — never a reason to "
       "act on its own.", "Fibonacci zone", "boolean"),
    _m("fib_sessions_in_zone", "Sessions in zone",
       "consecutive sessions with in_fib_zone true",
       "How long price has held the band rather than passed through it.",
       "Fibonacci zone", "integer", True),
    _m("fib_zone_status", "Zone status", "TRIGGERED | ARMED | NONE",
       "TRIGGERED needs zone, volume shape and a reversal bar together. "
       "ARMED is zone and dry-up with no turn yet.", "Fibonacci zone", "text"),
    _m("fib_zone_entry_type", "Entry type", "TRADED_INTO | GAP_THROUGH | RE_ENTERED",
       "GAP_THROUGH means price jumped the band without transacting in it, "
       "so no position was actually available there.",
       "Fibonacci zone", "text"),
    _m("vol_impulse_ratio", "Impulse volume", "mean(Vol A..B) / mean(Vol 50 before A)",
       "Whether the advance was confirmed by participation.",
       "Fibonacci zone", "ratio", True),
    _m("vol_dryup_ratio", "Pull-back volume",
       "mean(Vol B+1..yesterday) / mean(Vol A..B)",
       "Whether the pullback thinned. Lower is more constructive — selling "
       "that dries up is the shape that precedes a turn. Elevated volume in a "
       "retracement selects for distribution just as readily. Today is outside "
       "the window: it is the session this ratio has to arm, so letting its "
       "volume into the average lets a strong turn fail its own gate.",
       "Fibonacci zone", "ratio", False),
    _m("fib_turn_vol_ratio", "Turn volume", "Vol_0 / mean(Vol B+1..yesterday)",
       "Today's volume against the pullback it would be ending. Deliberately "
       "not rel_volume: that 50-session window spans the impulse leg, so it "
       "asks the most of the turn where the advance was best confirmed. Null "
       "until the pullback is three sessions old.",
       "Fibonacci zone", "ratio", True),
    _m("is_fib_reversal_bar", "Reversal bar",
       "close>open AND (C-L)/(H-L)>=0.60 AND fib_turn_vol_ratio>=1.5 "
       "AND L<=level(0.500)",
       "The event, as opposed to the location. Range travelled and held, on "
       "volume expanding against the pullback, having reached into the zone.",
       "Fibonacci zone", "boolean", True),
    _m("fib_stop", "Zone stop", "min(level(0.786), in-zone swing low - 0.5*ATR14)",
       "The wider of the two candidates on purpose: it survives noise the "
       "tighter one would be shaken out by.", "Fibonacci zone", "currency"),
    _m("fib_target", "Zone target", "B",
       "Recovery of the leg high. Not a projection beyond it.",
       "Fibonacci zone", "currency"),
    _m("fib_reward_risk", "Reward:risk", "(B - C_0) / (C_0 - fib_stop)",
       "Read alongside the round-trip cost: for an NRI account the "
       "withholding lands at exit, so break-even must be visible before "
       "entry.", "Fibonacci zone", "ratio", True),
    _m("fib_setup_score", "Setup score",
       "0.30 z(momentum) + 0.20 z(RS) + 0.20 z(1/dry-up) + 0.15 z(rel vol) "
       "+ 0.15 z(sessions in zone)",
       "Ranking for the Fibonacci Reversal Zone screen. Components are "
       "winsorised at the 1st/99th percentile before z-scoring (FR-6.8). The "
       "retracement ratio is deliberately excluded.",
       "Fibonacci zone", "number", True),
    _m("fib_exclusion_reason", "Zone excluded because",
       "first failing gate",
       "Why a constituent is not in the Fibonacci screen today. An absent row "
       "and a disqualified row are different answers, and only one is worth "
       "acting on.", "Fibonacci zone", "text"),

    # --- volatility ------------------------------------------------------
    _m("atr_14", "ATR 14", "Wilder-smoothed 14-period mean of true range",
       "Average true range. Drives the stop distance and position size.",
       "Volatility", "currency", False),
    _m("atr_pct_14", "ATR %", "ATR_14 / C_0",
       "Volatility as a share of price. Lower scores better in the composite.",
       "Volatility", "percent", False),
    _m("stdev_21", "Stdev 21", "sample sd of daily log returns over 21 sessions",
       "Short-run realised volatility.", "Volatility", "number", False),
    _m("stdev_63", "Stdev 63", "sample sd of daily log returns over 63 sessions",
       "Quarterly realised volatility.", "Volatility", "number", False),
    _m("adr_pct_20", "ADR %", "mean over 20 sessions of (High/Low - 1)",
       "Average daily range.", "Volatility", "percent", False),

    # --- volume ----------------------------------------------------------
    _m("vol_sma_20", "Volume SMA 20", "mean(volume, 20)", "20-session average volume.",
       "Volume", "integer"),
    _m("vol_sma_50", "Volume SMA 50", "mean(volume, 50)", "50-session average volume.",
       "Volume", "integer"),
    _m("rel_volume", "Relative volume", "Volume_0 / vol_sma_50",
       "Participation versus normal. 1.5 or above is the default breakout "
       "confirmation threshold.", "Volume", "ratio", True),
    _m("turnover_20d_median", "20d median turnover", "median(close x volume, 20)",
       "Traded value. The liquidity floor for screen eligibility.",
       "Volume", "currency", True),
    _m("delivery_pct_sma_20", "Delivery % (20d avg)", "mean(delivery_pct, 20)",
       "A breakout on high volume but low delivery is more likely speculative "
       "churn than accumulation.", "Volume", "percent", True),

    # --- oscillators -----------------------------------------------------
    _m("rsi_14", "RSI 14", "100 - 100/(1 + avg_gain/avg_loss), Wilder smoothing",
       "Relative strength index.", "Oscillators", "number"),
    _m("adx_14", "ADX 14", "Wilder-smoothed DX from +DI and -DI",
       "Trend strength irrespective of direction.", "Oscillators", "number", True),
    _m("macd", "MACD", "EMA(12) - EMA(26)", "Moving average convergence/divergence.",
       "Oscillators", "number"),
    _m("macd_signal", "MACD signal", "EMA(macd, 9)", "Signal line.",
       "Oscillators", "number"),
    _m("macd_hist", "MACD histogram", "macd - macd_signal", "Histogram.",
       "Oscillators", "number"),

    # --- patterns --------------------------------------------------------
    _m("is_52w_high_breakout", "52w high breakout",
       "C_0 > prior high_52w AND rel_volume >= 1.5",
       "New 52-week high on confirming volume.", "Patterns", "boolean", True),
    _m("is_n_day_breakout_20", "20-day breakout",
       "C_0 > max(High over prior 20) AND rel_volume >= 1.5",
       "20-session breakout on confirming volume.", "Patterns", "boolean", True),
    _m("is_n_day_breakout_50", "50-day breakout",
       "C_0 > max(High over prior 50) AND rel_volume >= 1.5",
       "50-session breakout on confirming volume.", "Patterns", "boolean", True),
    _m("is_in_base", "In base",
       "depth <= 15% AND ATR contracting AND prior advance >= 25%",
       "Volatility contraction after a strong advance — the setup that precedes "
       "most clean breakouts, which is how candidates surface before the move "
       "rather than after it.", "Patterns", "boolean", True),
    _m("base_depth_pct", "Base depth", "(max(High) - min(Low)) / max(High) over the window",
       "Tightness of the consolidation.", "Patterns", "percent", False),
    _m("base_length_days", "Base length", "consecutive sessions the base has held",
       "How long the contraction has persisted.", "Patterns", "integer", True),
    _m("support_level", "Support level",
       "highest confirmed swing low, sma_50 or ema_21 at or below C_0",
       "Nearest level beneath price where buyers previously appeared. Null at a "
       "new high, where nothing sits below.", "Patterns", "currency", True),
    _m("support_distance_pct", "Distance to support", "C_0 / support_level - 1",
       "How far price sits above its nearest support.", "Patterns", "percent", True),
    _m("is_at_support", "At support", "support_distance_pct <= 3%",
       "Price is within the tolerance band of its support level.",
       "Patterns", "boolean", True),
    _m("pullback_from_high_pct", "Pullback depth",
       "C_0 / max(High over 21 sessions) - 1",
       "How far price has retraced from its recent high.", "Patterns", "percent", True),
    _m("reversal_score", "Reversal score", "count of 5 checks: R1..R5",
       "RSI turning up from oversold, MACD histogram improving, price reclaiming "
       "ema_21, a close in the top third of the bar's range, and volume "
       "confirmation. 0-5.", "Patterns", "integer", True),
    _m("is_reversal", "Reversal", "reversal_score >= 2",
       "At least two independent reversal checks agree.",
       "Patterns", "boolean", True),
    _m("is_pullback_reversal", "Pullback + reversal",
       "at support AND pullback 3-25% AND reversal AND C_0 > sma_200",
       "Pulled back to a support level and showing confirmation the pullback has "
       "stopped, with the long-term uptrend intact.", "Patterns", "boolean", True),
    _m("is_pullback", "Pullback",
       "trend template AND within 3% of ema_21 or sma_50 AND ret_1w < 0 AND RSI 40-55",
       "Pullback within an established uptrend.", "Patterns", "boolean", True),

    # --- data quality ----------------------------------------------------
    _m("history_days", "History (sessions)", "count of stored sessions",
       "Fewer than 252 sessions is insufficient for 52-week and 12-month metrics.",
       "Data quality", "integer"),
    _m("ineligible_reason", "Exclusion reason",
       "series / surveillance / insufficient history / below liquidity floor",
       "Which rule holds this symbol out of screen results. Empty when eligible. "
       "Excluded names are still ingested and charted (FR-1.5).",
       "Data quality", "text", True),
    _m("is_eligible", "Eligible",
       "series in (EQ, BE) AND history >= 252 AND turnover >= floor AND not flagged",
       "Whether the symbol may appear in screen results. Ineligible names are "
       "still ingested and stored.", "Data quality", "boolean", True),
)

BY_NAME: Final[dict[str, MetricDef]] = {m.name: m for m in REGISTRY}

GROUPS: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(m.group for m in REGISTRY)
)


def get(name: str) -> MetricDef | None:
    return BY_NAME.get(name)


def to_markdown() -> str:
    """Render METRICS.md (NFR-5.6)."""
    lines = [
        "# Metric Reference",
        "",
        "Generated from `alpha500.metrics.registry`. Do not edit by hand — "
        "regenerate with `python -m alpha500.tools.gen_metrics_doc`.",
        "",
    ]
    for group in GROUPS:
        lines.append(f"## {group}")
        lines.append("")
        lines.append("| Metric | Formula | Meaning |")
        lines.append("|---|---|---|")
        for metric in REGISTRY:
            if metric.group != group:
                continue
            formula = metric.formula.replace("|", "\\|")
            description = metric.description.replace("|", "\\|")
            lines.append(f"| `{metric.name}` | `{formula}` | {description} |")
        lines.append("")
    return "\n".join(lines)
