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
  'rel_volume',
  'atr_pct_14',
  'rsi_14',
  'turnover_20d_median',
  // NSE's constituent file publishes a macro "Industry" and no finer sector,
  // so that is the classification the grid and heatmap both use.
  'industry',
]

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
