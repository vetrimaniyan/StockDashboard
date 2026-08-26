# Metric Reference

Generated from `alpha500.metrics.registry`. Do not edit by hand — regenerate with `python -m alpha500.tools.gen_metrics_doc`.

## Returns

| Metric | Formula | Meaning |
|---|---|---|
| `ret_1d` | `C_0 / C_1 - 1` | Latest session's price change. |
| `ret_1w` | `C_0 / C_5 - 1` | Return over the last 5 trading sessions. |
| `ret_1m` | `C_0 / C_21 - 1` | Return over the last 21 trading sessions. |
| `ret_3m` | `C_0 / C_63 - 1` | Return over the last 63 trading sessions. |
| `ret_6m` | `C_0 / C_126 - 1` | Return over the last 126 trading sessions. |
| `ret_9m` | `C_0 / C_189 - 1` | Return over the last 189 trading sessions. |
| `ret_12m` | `C_0 / C_252 - 1` | Return over the last 252 sessions. Reference only — the composite uses ret_12m_1m instead. |
| `ret_12m_1m` | `C_21 / C_252 - 1` | Medium-term momentum with the most recent month skipped. Short-horizon reversal is well documented: stocks that ran hardest in the last 21 sessions tend to give some of it back, so including that month contaminates the signal. |

## Relative strength

| Metric | Formula | Meaning |
|---|---|---|
| `rs_1m` | `(1 + ret_1m) / (1 + index_ret_1m) - 1` | 1-month performance relative to the NIFTY 500. |
| `rs_3m` | `(1 + ret_3m) / (1 + index_ret_3m) - 1` | 3-month performance relative to the NIFTY 500. |
| `rs_6m` | `(1 + ret_6m) / (1 + index_ret_6m) - 1` | 6-month performance relative to the NIFTY 500. |
| `rs_12m` | `(1 + ret_12m) / (1 + index_ret_12m) - 1` | 12-month performance relative to the NIFTY 500. |
| `rs_rating` | `ceil(99 x percentile_rank(0.40*ret_3m + 0.20*ret_6m + 0.20*ret_9m + 0.20*ret_12m))` | Percentile 1-99 against the eligible universe. 99 means the stock outperformed 99% of it. Cross-sectional — recomputed for the whole universe every session. |

## Momentum

| Metric | Formula | Meaning |
|---|---|---|
| `exp_reg_slope_90` | `exp(b x 252) - 1` | Annualised slope of an OLS fit of ln(close) on session index over the last 90 sessions. |
| `exp_reg_r2_90` | `R^2 of the ln(close) regression` | How consistently the advance followed its trendline. Penalises choppy, gap-driven moves. |
| `momentum_score` | `(exp(b x 252) - 1) x R^2` | Trend strength multiplied by trend consistency. A 60% slope at R^2 0.35 scores 0.21, below a 30% slope at R^2 0.90 scoring 0.27 — that ordering is intentional and is the point of the metric. Null when the gap disqualifier fires. |
| `momentum_rank` | `dense_rank(momentum_score DESC)` | 1 = strongest in the eligible universe. |
| `composite_z` | `sum of weighted z-scores of winsorised components` | Configurable blend of momentum, 12m-1m return, RS rating, 52-week range position, ATR% (negative weight) and relative volume. |
| `gap_disqualified` | `any \|ret_1d\| > 15% within the 90-session lookback` | A one-off event move (block deal, court ruling, takeover bid) means the stock is not in a tradeable trend. Excluded from momentum ranking. |

## Trend

| Metric | Formula | Meaning |
|---|---|---|
| `sma_20` | `mean(close, 20)` | 20-session simple moving average. |
| `sma_50` | `mean(close, 50)` | 50-session simple moving average. |
| `sma_100` | `mean(close, 100)` | 100-session simple moving average. |
| `sma_150` | `mean(close, 150)` | 150-session simple moving average. |
| `sma_200` | `mean(close, 200)` | 200-session simple moving average. |
| `ema_21` | `EMA(close, 21), alpha = 2/22` | 21-session exponential moving average. |
| `ema_50` | `EMA(close, 50), alpha = 2/51` | 50-session exponential moving average. |
| `sma_200_slope_1m` | `sma_200_today / sma_200_21_sessions_ago - 1` | Direction of the long-term average over the last month. |
| `ma_alignment` | `C_0 > sma_50 > sma_100 > sma_200` | Price and averages stacked in trend order. |
| `trend_template_score` | `count of 8 criteria met` | 0-8 structural uptrend quality. Shown as a partial score because a 7/8 stock approaching its eighth criterion is an actionable watchlist item that a binary flag would hide. |
| `is_trend_template` | `trend_template_score = 8` | All eight structural criteria met. |

## 52-week

| Metric | Formula | Meaning |
|---|---|---|
| `high_52w` | `max(High) over 252 sessions` | From intraday highs, not closes — using closes understates the range and produces false breakouts. |
| `low_52w` | `min(Low) over 252 sessions` | From intraday lows, not closes. |
| `pct_from_52w_high` | `C_0 / high_52w - 1` | Always <= 0; closer to zero is stronger. |
| `pct_above_52w_low` | `C_0 / low_52w - 1` | Distance above the 52-week low. |
| `range_position_52w` | `(C_0 - low_52w) / (high_52w - low_52w)` | 0 = at the 52-week low, 1 = at the high. |
| `days_since_52w_high` | `sessions elapsed since high_52w was set` | 0 means the high is today's bar. |

## Volatility

| Metric | Formula | Meaning |
|---|---|---|
| `atr_14` | `Wilder-smoothed 14-period mean of true range` | Average true range. Drives the stop distance and position size. |
| `atr_pct_14` | `ATR_14 / C_0` | Volatility as a share of price. Lower scores better in the composite. |
| `stdev_21` | `sample sd of daily log returns over 21 sessions` | Short-run realised volatility. |
| `stdev_63` | `sample sd of daily log returns over 63 sessions` | Quarterly realised volatility. |
| `adr_pct_20` | `mean over 20 sessions of (High/Low - 1)` | Average daily range. |

## Volume

| Metric | Formula | Meaning |
|---|---|---|
| `vol_sma_20` | `mean(volume, 20)` | 20-session average volume. |
| `vol_sma_50` | `mean(volume, 50)` | 50-session average volume. |
| `rel_volume` | `Volume_0 / vol_sma_50` | Participation versus normal. 1.5 or above is the default breakout confirmation threshold. |
| `turnover_20d_median` | `median(close x volume, 20)` | Traded value. The liquidity floor for screen eligibility. |
| `delivery_pct_sma_20` | `mean(delivery_pct, 20)` | A breakout on high volume but low delivery is more likely speculative churn than accumulation. |

## Oscillators

| Metric | Formula | Meaning |
|---|---|---|
| `rsi_14` | `100 - 100/(1 + avg_gain/avg_loss), Wilder smoothing` | Relative strength index. |
| `adx_14` | `Wilder-smoothed DX from +DI and -DI` | Trend strength irrespective of direction. |
| `macd` | `EMA(12) - EMA(26)` | Moving average convergence/divergence. |
| `macd_signal` | `EMA(macd, 9)` | Signal line. |
| `macd_hist` | `macd - macd_signal` | Histogram. |

## Patterns

| Metric | Formula | Meaning |
|---|---|---|
| `is_52w_high_breakout` | `C_0 > prior high_52w AND rel_volume >= 1.5` | New 52-week high on confirming volume. |
| `is_n_day_breakout_20` | `C_0 > max(High over prior 20) AND rel_volume >= 1.5` | 20-session breakout on confirming volume. |
| `is_n_day_breakout_50` | `C_0 > max(High over prior 50) AND rel_volume >= 1.5` | 50-session breakout on confirming volume. |
| `is_in_base` | `depth <= 15% AND ATR contracting AND prior advance >= 25%` | Volatility contraction after a strong advance — the setup that precedes most clean breakouts, which is how candidates surface before the move rather than after it. |
| `base_depth_pct` | `(max(High) - min(Low)) / max(High) over the window` | Tightness of the consolidation. |
| `base_length_days` | `consecutive sessions the base has held` | How long the contraction has persisted. |
| `is_pullback` | `trend template AND within 3% of ema_21 or sma_50 AND ret_1w < 0 AND RSI 40-55` | Pullback within an established uptrend. |

## Data quality

| Metric | Formula | Meaning |
|---|---|---|
| `history_days` | `count of stored sessions` | Fewer than 252 sessions is insufficient for 52-week and 12-month metrics. |
| `is_eligible` | `series in (EQ, BE) AND history >= 252 AND turnover >= floor AND not flagged` | Whether the symbol may appear in screen results. Ineligible names are still ingested and stored. |
