/**
 * Narrow-viewport fallback for the results grid (FR-8.12).
 *
 * Below 768px the grid degrades to cards showing symbol, close, 1-day and
 * 1-week change, RS rating and momentum rank. This is not a phone-first
 * product, so the card carries the minimum needed to recognise a name and
 * decide whether to open it — not a reflowed forty-column table.
 */

import type { ScreenRow } from '../api'
import { currency, directionClass, num, signedPct, EM_DASH } from '../format'

export function CardList({
  rows,
  onSelect,
}: {
  rows: ScreenRow[]
  onSelect?: (symbol: string) => void
}) {
  if (rows.length === 0) {
    return (
      <div className="p-8 text-center text-[var(--muted)]">
        No symbols match this screen for the selected session.
      </div>
    )
  }

  return (
    <div className="overflow-auto h-full p-2 space-y-2">
      {rows.map((row) => (
        <button
          key={row.tradingsymbol}
          onClick={() => onSelect?.(row.tradingsymbol)}
          className="w-full text-left rounded border border-[var(--border)] bg-[var(--panel)] p-2.5 hover:border-[var(--accent)]"
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-semibold text-[var(--accent)]">
              {row.tradingsymbol}
            </span>
            <span className="num">{currency(row.close as number)}</span>
          </div>

          {row.name != null && (
            <div className="text-[var(--muted)] truncate">{String(row.name)}</div>
          )}

          <div className="mt-1.5 grid grid-cols-4 gap-2">
            <Field
              label="1d"
              value={signedPct(row.ret_1d as number)}
              tone={directionClass(row.ret_1d as number)}
            />
            <Field
              label="1w"
              value={signedPct(row.ret_1w as number)}
              tone={directionClass(row.ret_1w as number)}
            />
            <Field
              label="RS"
              value={row.rs_rating == null ? EM_DASH : num(row.rs_rating as number, 0)}
            />
            <Field
              label="Rank"
              value={
                row.momentum_rank == null ? EM_DASH : num(row.momentum_rank as number, 0)
              }
            />
          </div>
        </button>
      ))}
    </div>
  )
}

function Field({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="text-[var(--muted)]">{label}</div>
      <div className={`num ${tone ?? ''}`}>{value}</div>
    </div>
  )
}
