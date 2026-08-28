/** Index P/E against its own history.
 *
 * A P/E level on its own says nothing — a midcap index at 30 is only
 * meaningful once you know it has historically sat near 25. So the current
 * figure is shown beside its own 7- and 10-year medians and the gap between
 * them, which is the number that actually carries information.
 */

import { useEffect, useState } from 'react'
import { ApiError, api, type IndexValuationResponse } from '../api'
import { num } from '../format'

function Gap({ value }: { value: number | null }) {
  if (value === null || !Number.isFinite(value)) {
    return <span className="text-[var(--muted)]">—</span>
  }
  // Rich versus cheap is the meaning, so the sign carries it and colour only
  // reinforces (FR-8.11). Expensive is not "good", so accent, not green.
  const rich = value > 0
  return (
    <span className={rich ? 'text-[var(--warn)]' : 'text-[var(--up)]'}>
      {rich ? '▲' : '▼'} {Math.abs(value).toFixed(1)}%
    </span>
  )
}

export function IndexValuation() {
  const [data, setData] = useState<IndexValuationResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .indexValuation()
      .then(setData)
      .catch((e: ApiError) => setError(e.message))
  }, [])

  if (error) {
    return <div className="text-[var(--down)]">{error}</div>
  }
  if (!data) {
    return <div className="text-[var(--muted)]">Loading valuations…</div>
  }
  if (!data.indices.length) {
    return (
      <div className="text-[var(--muted)]">
        No index valuation history yet — run <code>alpha500 indices</code>.
      </div>
    )
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="text-[var(--muted)]">
            <tr>
              <th className="text-left font-normal py-1">Index</th>
              <th className="text-right font-normal">P/E now</th>
              <th className="text-right font-normal">7y median</th>
              <th className="text-right font-normal">vs 7y</th>
              <th className="text-right font-normal">10y median</th>
              <th className="text-right font-normal">vs 10y</th>
              <th className="text-right font-normal">P/B</th>
              <th className="text-right font-normal">Div yld</th>
            </tr>
          </thead>
          <tbody>
            {data.indices.map((row) => (
              <tr key={row.index_name} className="border-t border-[var(--border)]">
                <td className="py-1 font-medium">{row.index_name}</td>
                <td className="text-right num">{num(row.pe, 2)}</td>
                <td className="text-right num text-[var(--muted)]">
                  {num(row.median_pe_7y, 1)}
                </td>
                <td className="text-right num">
                  <Gap value={row.pe_vs_7y_pct} />
                </td>
                <td className="text-right num text-[var(--muted)]">
                  {num(row.median_pe_10y, 1)}
                </td>
                <td className="text-right num">
                  <Gap value={row.pe_vs_10y_pct} />
                </td>
                <td className="text-right num text-[var(--muted)]">{num(row.pb, 2)}</td>
                <td className="text-right num text-[var(--muted)]">
                  {num(row.div_yield, 2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[var(--muted)] leading-snug">
        {data.history_from && (
          <>
            History {data.history_from} → {data.history_to},{' '}
            {data.observations.toLocaleString()} observations.{' '}
          </>
        )}
        {data.note}
      </p>
    </div>
  )
}
