/** Grid column choice, order and persistence (FR-8.3).
 *
 * Lifted out of ResultsGrid so the Screener can host the picker beside the
 * filter builder while the grid stays a presentational component. Both need
 * the same defaults, labels and storage key, and duplicating them is how the
 * two drift apart.
 */

export const DEFAULT_COLUMNS = [
  'tradingsymbol',
  'close',
  'index_tier',
  'market_cap',
  'ret_1d',
  'ret_1w',
  'ret_1m',
  'rs_rating',
  'momentum_rank',
  'momentum_score',
  'exp_reg_r2_90',
  'trend_template_score',
  'range_position_52w',
  'pct_from_52w_high',
  // Shown together on purpose: the period high means little without the depth
  // it was measured over, which varies from months to years by symbol.
  'pct_from_period_high',
  'history_days',
  // FR-17. The status and the exclusion reason together answer both
  // "is this a setup" and "why is this not one".
  'fib_zone_status',
  'fib_retracement_ratio',
  'fib_reward_risk',
  'rel_volume',
  'atr_pct_14',
  'rsi_14',
  'turnover_20d_median',
  // NSE's constituent file publishes a macro "Industry" and no finer sector,
  // so that is the classification the grid and heatmap both use.
  'industry',
]

/** Size tier codes as stored, mapped to the index's published name.
 *
 * The store keeps NSE's own constituent-file keys so a screen filter matches
 * what the provider publishes; only the display is prettified. Mirrors
 * TIER_LABELS in backend/alpha500/pipeline/indices.py — the NIFTY 500 is
 * exactly these four lists, so an unmapped code means the sync found a fifth
 * and is shown raw rather than hidden.
 */
export const TIER_LABELS: Record<string, string> = {
  NIFTY50: 'Nifty 50',
  NIFTYNEXT50: 'Next 50',
  NIFTYMIDCAP150: 'Midcap 150',
  NIFTYSMALLCAP250: 'Smallcap 250',
}

/** Columns whose values are text, not numbers.
 *
 * Kept here rather than inline in the grid: a string column formatted as a
 * number renders NaN, which is how index_tier and ineligible_reason were
 * both displaying.
 */
export const TEXT_COLUMNS: ReadonlySet<string> = new Set([
  'tradingsymbol', 'name', 'sector', 'industry', 'series',
  'index_tier', 'ineligible_reason',
  // FR-17: string-valued, so they must not reach the numeric formatter.
  'fib_zone_status', 'fib_zone_entry_type', 'fib_exclusion_reason',
])

/** Date-valued columns. Rendered as dates, not run through byUnit. */
export const DATE_COLUMNS: ReadonlySet<string> = new Set([
  'fib_leg_low_date', 'fib_leg_high_date', 'fib_leg_confirmed_date',
])

export const STATIC_LABELS: Record<string, string> = {
  tradingsymbol: 'Symbol',
  name: 'Company',
  sector: 'Sector',
  industry: 'Industry',
  close: 'Close',
  market_cap: 'Market cap (free float)',
  index_tier: 'Index tier',
  ineligible_reason: 'Excluded because',
  volume: 'Volume',
  delivery_pct: 'Delivery %',
}

const key = (storageKey: string) => `grid:${storageKey}`

export function loadColumns(storageKey: string): string[] {
  try {
    const raw = localStorage.getItem(key(storageKey))
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length) return parsed
    }
  } catch {
    /* storage unavailable or corrupt; fall back to defaults */
  }
  return DEFAULT_COLUMNS
}

export function saveColumns(storageKey: string, columns: string[]): void {
  try {
    localStorage.setItem(key(storageKey), JSON.stringify(columns))
  } catch {
    /* private browsing or quota; the choice simply will not survive a reload */
  }
}

/** Column keys present in the returned rows, minus the internal identifiers. */
export function availableColumns(rows: Array<Record<string, unknown>>): string[] {
  const keys = new Set<string>()
  for (const row of rows.slice(0, 5)) {
    Object.keys(row).forEach((k) => keys.add(k))
  }
  keys.delete('instrument_token')
  keys.delete('trade_date')
  return Array.from(keys).sort()
}
