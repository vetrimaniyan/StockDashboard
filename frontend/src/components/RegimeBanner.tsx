/**
 * Market-regime banner (FR-7.7, FR-7.8).
 *
 * In a Risk-off regime the advisory is persistent. The system never blocks
 * screening — the operator decides — but the context must be visible without
 * being sought.
 */

import type { Breadth, MarketRegime } from '../api'
import { currency, num } from '../format'

const STYLES: Record<string, string> = {
  'Risk-on': 'bg-[rgba(53,201,127,0.12)] border-[var(--up)] text-[var(--up)]',
  Neutral: 'bg-[var(--panel-2)] border-[var(--border)] text-[var(--text)]',
  'Risk-off': 'bg-[rgba(239,95,107,0.12)] border-[var(--down)] text-[var(--down)]',
  Unknown: 'bg-[var(--panel-2)] border-[var(--border)] text-[var(--muted)]',
}

const GLYPHS: Record<string, string> = {
  'Risk-on': '▲',
  Neutral: '=',
  'Risk-off': '▼',
  Unknown: '?',
}

export function RegimeBanner({
  regime,
  breadth,
}: {
  regime: MarketRegime
  breadth: Breadth
}) {
  const style = STYLES[regime.regime] ?? STYLES.Unknown

  return (
    <div className={`rounded border p-3 ${style}`}>
      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="text-lg font-semibold">
          {GLYPHS[regime.regime] ?? ''} {regime.regime}
        </span>
        <span className="opacity-80">NIFTY 500</span>
        {regime.index_close != null && (
          <span className="num">{currency(regime.index_close, 2)}</span>
        )}
        {regime.sma_50 != null && regime.sma_200 != null && (
          <span className="num opacity-80">
            50d {num(regime.sma_50, 0)} · 200d {num(regime.sma_200, 0)}
          </span>
        )}
        <span className="opacity-80">
          Breadth: {breadth.advances} adv / {breadth.declines} dec · net new highs{' '}
          {breadth.net_new_highs >= 0 ? '+' : ''}
          {breadth.net_new_highs}
        </span>
      </div>
      {regime.advisory && (
        <p className="mt-2 opacity-95 leading-snug">{regime.advisory}</p>
      )}
    </div>
  )
}
