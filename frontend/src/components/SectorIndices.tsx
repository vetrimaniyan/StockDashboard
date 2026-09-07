/** FR-18.3/18.4/18.10 — where each sector index sits in its own range.
 *
 * A range bar per index, because the question "is this segment extended or
 * beaten down" is a position question, and a position reads faster as a
 * position than as four numbers.
 *
 * The track spans low_52w to max(high_52w, period_high). Stopping it at the
 * 52-week high would push the peak marker off the end on exactly the indices
 * furthest below their peak — the ones the panel exists to show.
 *
 * FR-18.11: this says where strength currently sits, not where it will sit
 * next, and nothing here is a buy signal. Index futures are out of scope under
 * FR-12; the use of this panel is to narrow which stock screens to read.
 */

import { useEffect, useState } from 'react'
import { ApiError, api, type SectorIndex, type SectorIndicesResponse } from '../api'
import { formatDate, num, signedPct } from '../format'

/** Trend carried by glyph and label as well as colour (NFR-6.3). */
function Trend({ state, sessions }: { state: string | null; sessions: number | null }) {
  if (!state) return <span className="text-[var(--muted)]">—</span>
  const glyph = state === 'UPTREND' ? '▲' : state === 'DOWNTREND' ? '▼' : '◆'
  const tone =
    state === 'UPTREND'
      ? 'text-[var(--up)]'
      : state === 'DOWNTREND'
        ? 'text-[var(--down)]'
        : 'text-[var(--muted)]'
  const label = state.charAt(0) + state.slice(1).toLowerCase()
  return (
    <span className={tone}>
      {glyph} {label}
      {sessions !== null && (
        <span className="text-[var(--muted)]"> · {sessions}s</span>
      )}
    </span>
  )
}

/** low_52w ......... close ......... high_52w, with the period high beyond. */
function RangeBar({ row }: { row: SectorIndex }) {
  const { low_52w: low, high_52w: high, period_high: peak, close } = row
  if (low === null || high === null || close === null) {
    return <div className="text-[var(--muted)]">—</div>
  }
  const top = Math.max(high, peak ?? high)
  const span = top - low
  if (!(span > 0)) return <div className="text-[var(--muted)]">—</div>

  const at = (v: number) => `${((v - low) / span) * 100}%`
  const drawdownFrom = Math.min(close, peak ?? close)

  return (
    <div className="relative h-4 w-full rounded bg-[var(--border)]">
      {/* The gap between the peak and where the index trades now. */}
      {peak !== null && peak > close && (
        <div
          className="absolute top-0 bottom-0 rounded-r bg-[rgba(240,180,41,0.18)]"
          style={{ left: at(drawdownFrom), right: `${100 - parseFloat(at(peak))}%` }}
        />
      )}
      <div
        className="absolute top-0 bottom-0 w-[2px] bg-[var(--muted)]"
        style={{ left: at(high) }}
        title={`52w high ${num(high, 0)}`}
      />
      {peak !== null && (
        <div
          className="absolute -top-0.5 -bottom-0.5 w-[2px] bg-[var(--warn)]"
          style={{ left: at(peak) }}
          title={`period high ${num(peak, 0)}${
            row.period_high_date ? ` on ${formatDate(row.period_high_date)}` : ''
          }`}
        />
      )}
      <div
        className="absolute -top-1 -bottom-1 w-[3px] rounded bg-[var(--fg)]"
        style={{ left: at(close) }}
        title={`close ${num(close, 0)}`}
      />
    </div>
  )
}

export function SectorIndices() {
  const [data, setData] = useState<SectorIndicesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .sectorIndices()
      .then(setData)
      .catch((e: ApiError) => setError(e.message))
  }, [])

  if (error) return <div className="text-[var(--down)]">{error}</div>
  if (!data) return <div className="text-[var(--muted)]">Loading sector indices…</div>

  const shown = data.indices.filter((r) => r.available)
  const withheld = data.indices.filter((r) => !r.available)

  if (!shown.length) {
    return (
      <div className="text-[var(--muted)]">
        No index series yet — run <code>alpha500 index-series</code>.
      </div>
    )
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-3 flex-wrap text-[var(--muted)]">
        <span>
          as of <strong>{formatDate(data.as_of)}</strong>
        </span>
        <span>
          · {data.measurable} of {data.tracked} tracked indices measurable
        </span>
        {Object.entries(data.trend_counts).map(([state, n]) => (
          <span key={state}>
            · {n} {state.toLowerCase()}
          </span>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="text-[var(--muted)]">
            <tr>
              <th className="text-left font-normal py-1">Index</th>
              <th className="text-left font-normal">Trend</th>
              <th className="text-left font-normal w-[26%]">52-week range</th>
              <th className="text-right font-normal">In range</th>
              <th className="text-right font-normal">vs 52w high</th>
              <th className="text-right font-normal">vs period high</th>
              <th className="text-right font-normal">Peak set</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.index_name} className="border-t border-[var(--border)]">
                <td className="py-1.5 font-medium">
                  {row.index_name}
                  {row.ohlc_basis === 'CLOSE' && (
                    <span className="ml-1 text-[var(--muted)]" title="range measured on closing values; no intraday high or low available">
                      (close)
                    </span>
                  )}
                </td>
                <td>
                  <Trend state={row.trend_state} sessions={row.sessions_in_state} />
                </td>
                <td className="pr-3">
                  <RangeBar row={row} />
                </td>
                <td className="text-right num">
                  {row.range_position_52w === null
                    ? '—'
                    : `${(row.range_position_52w * 100).toFixed(0)}%`}
                </td>
                <td className="text-right num">{signedPct(row.pct_from_52w_high)}</td>
                <td className="text-right num">{signedPct(row.pct_from_period_high)}</td>
                <td className="text-right num text-[var(--muted)]">
                  {row.period_high_date ? formatDate(row.period_high_date) : '—'}
                  {row.sessions_since_period_high !== null && (
                    <span> · {row.sessions_since_period_high}s</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Named, not dropped. An index missing from a ranking reads as absent
          from the market rather than absent from the data. */}
      {withheld.length > 0 && (
        <details className="mt-3 text-[var(--muted)]">
          <summary className="cursor-pointer">
            {withheld.length} {withheld.length === 1 ? 'index' : 'indices'} not measurable
          </summary>
          <ul className="mt-1 leading-snug">
            {withheld.map((row) => (
              <li key={row.index_name}>
                <strong>{row.index_name}</strong> — {row.reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="mt-2 text-[var(--muted)] leading-snug">{data.note}</p>
    </div>
  )
}
