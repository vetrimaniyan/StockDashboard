/**
 * Virtualised results grid (FR-8.3, NFR-1.2).
 *
 * Row virtualisation is mandatory: a 500-row x 40-column DOM table does not
 * meet the 1.5s render budget.
 *
 * Column choice and order persist per screen (localStorage). Sorting is
 * multi-column via shift-click. The symbol column is sticky.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { MetricDefinition, ScreenRow } from '../api'
import { DATE_COLUMNS, STATIC_LABELS, TEXT_COLUMNS, TIER_LABELS } from '../columns'
import { byUnit, directionClass, arrow, EM_DASH, isBlank } from '../format'
import { CardList } from './CardList'

const ROW_HEIGHT = 30

const STATIC_UNITS: Record<string, string> = {
  // byUnit switches to lakh/crore above 1e5, which is the only readable
  // form for a capitalisation.
  market_cap: 'currency',
  close: 'currency',
  volume: 'integer',
  delivery_pct: 'percent',
}

/** Metrics where the sign carries meaning and should be shown with an arrow. */
const SIGNED = new Set([
  'ret_1d', 'ret_1w', 'ret_1m', 'ret_3m', 'ret_6m', 'ret_9m', 'ret_12m',
  'ret_12m_1m', 'rs_1m', 'rs_3m', 'rs_6m', 'rs_12m', 'sma_200_slope_1m',
  'pct_from_52w_high', 'pct_above_52w_low', 'composite_z', 'macd_hist',
  // Same quantity as pct_from_52w_high over a longer window; formatting them
  // differently in adjacent columns reads as a difference in kind.
  'pct_from_period_high',
])

interface Props {
  rows: ScreenRow[]
  definitions: Map<string, MetricDefinition>
  /** Column order is owned by the Screener, beside the filter builder. */
  visible: string[]
  onSelect?: (symbol: string) => void
}

/** Heat shading for a value's position within its own column's range. */
function heatStyle(value: unknown, min: number, max: number): React.CSSProperties {
  if (isBlank(value) || typeof value !== 'number' || min === max) return {}
  const t = (value - min) / (max - min)
  // Muted so the numbers stay readable; colour is never the only signal.
  const alpha = 0.06 + Math.abs(t - 0.5) * 0.22
  return {
    background:
      t >= 0.5
        ? `rgba(53, 201, 127, ${alpha.toFixed(3)})`
        : `rgba(239, 95, 107, ${alpha.toFixed(3)})`,
  }
}

/** FR-8.12: the grid degrades to cards below 768px. */
function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches,
  )
  useEffect(() => {
    const query = window.matchMedia('(max-width: 767px)')
    const onChange = (e: MediaQueryListEvent) => setNarrow(e.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return narrow
}

export function ResultsGrid({ rows, definitions, visible, onSelect }: Props) {
  const [sorting, setSorting] = useState<SortingState>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const isNarrow = useIsNarrow()

  // Per-column numeric range, for the conditional colour scales.
  const ranges = useMemo(() => {
    const out = new Map<string, { min: number; max: number }>()
    for (const key of visible) {
      let min = Infinity
      let max = -Infinity
      for (const row of rows) {
        const v = row[key]
        if (typeof v === 'number' && isFinite(v)) {
          if (v < min) min = v
          if (v > max) max = v
        }
      }
      if (min !== Infinity) out.set(key, { min, max })
    }
    return out
  }, [rows, visible])

  const columns = useMemo<ColumnDef<ScreenRow>[]>(() => {
    return visible.map((key) => {
      const def = definitions.get(key)
      const label = def?.label ?? STATIC_LABELS[key] ?? key
      const unit = def?.unit ?? STATIC_UNITS[key]
      const isSymbol = key === 'tradingsymbol'
      const isText = TEXT_COLUMNS.has(key) || DATE_COLUMNS.has(key)

      return {
        id: key,
        accessorFn: (row) => row[key],
        header: () => (
          <span
            title={
              def
                ? `${def.label}\n\nFormula: ${def.formula}\n\n${def.description}`
                : label
            }
          >
            {label}
            {def ? <span className="ml-1 text-[var(--muted)]">ⓘ</span> : null}
          </span>
        ),
        sortingFn: 'basic',
        sortUndefined: 'last',
        cell: (ctx) => {
          const value = ctx.getValue()
          if (isSymbol) {
            return (
              <button
                className="text-[var(--accent)] hover:underline font-medium"
                onClick={() => onSelect?.(String(value))}
              >
                {String(value)}
              </button>
            )
          }
          // typeof guards the case TEXT_COLUMNS misses: any string column added
          // later would otherwise reach byUnit below and render as NaN.
          if (isText || typeof value === 'string') {
            if (value == null) return <span>{EM_DASH}</span>
            const text = String(value)
            return <span>{key === 'index_tier' ? TIER_LABELS[text] ?? text : text}</span>
          }
          if (typeof value === 'boolean') {
            return (
              <span className={value ? 'text-[var(--up)]' : 'text-[var(--muted)]'}>
                {value ? '✓ Yes' : '· No'}
              </span>
            )
          }
          const text = byUnit(value, unit)
          if (SIGNED.has(key)) {
            return (
              <span className={`num ${directionClass(value as number)}`}>
                {isBlank(value)
                  ? EM_DASH
                  : `${arrow(value as number)} ${byUnit(Math.abs(value as number), unit)}`}
              </span>
            )
          }
          return <span className="num">{text}</span>
        },
        meta: { isText },
      } as ColumnDef<ScreenRow>
    })
  }, [visible, definitions, onSelect])

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    enableSortingRemoval: true,
    isMultiSortEvent: (e) => (e as React.MouseEvent).shiftKey,
  })

  const tableRows = table.getRowModel().rows
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  })

  const items = virtualizer.getVirtualItems()
  const paddingTop = items.length ? items[0].start : 0
  const paddingBottom = items.length
    ? virtualizer.getTotalSize() - items[items.length - 1].end
    : 0

  if (isNarrow) {
    return <CardList rows={rows} onSelect={onSelect} />
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center px-3 py-2 border-b border-[var(--border)]">
        <span className="text-[var(--muted)]">
          {rows.length} row{rows.length === 1 ? '' : 's'}
          {sorting.length > 0 && (
            <span className="ml-2">
              · sorted by {sorting.map((s) => `${s.id} ${s.desc ? '↓' : '↑'}`).join(', ')}
            </span>
          )}
          <span className="ml-2 opacity-60">· shift-click a header to add a sort</span>
        </span>
      </div>

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-auto">
        <table className="w-full border-collapse" style={{ tableLayout: 'fixed' }}>
          <colgroup>
            {visible.map((key) => (
              <col
                key={key}
                style={{ width: key === 'tradingsymbol' ? 110 : key === 'name' ? 200 : 96 }}
              />
            ))}
          </colgroup>
          <thead className="sticky top-0 z-20">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header, index) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        header.column.toggleSorting(undefined, e.shiftKey)
                      }
                    }}
                    className={`px-2 py-1.5 text-left font-medium bg-[var(--panel-2)] border-b border-[var(--border)] cursor-pointer select-none whitespace-nowrap overflow-hidden text-ellipsis ${
                      index === 0 ? 'sticky left-0 z-30' : ''
                    }`}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {{ asc: ' ↑', desc: ' ↓' }[header.column.getIsSorted() as string] ?? ''}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {paddingTop > 0 && (
              <tr>
                <td style={{ height: paddingTop }} colSpan={visible.length} />
              </tr>
            )}
            {items.map((item) => {
              const row = tableRows[item.index]
              return (
                <tr
                  key={row.id}
                  className="hover:bg-[var(--panel-2)]"
                  style={{ height: ROW_HEIGHT }}
                >
                  {row.getVisibleCells().map((cell, index) => {
                    const key = cell.column.id
                    const range = ranges.get(key)
                    const isText = (cell.column.columnDef.meta as { isText?: boolean })?.isText
                    return (
                      <td
                        key={cell.id}
                        style={
                          !isText && range
                            ? heatStyle(cell.getValue(), range.min, range.max)
                            : undefined
                        }
                        className={`px-2 border-b border-[var(--border)] whitespace-nowrap overflow-hidden text-ellipsis ${
                          index === 0
                            ? 'sticky left-0 z-10 bg-[var(--panel)]'
                            : isText
                              ? ''
                              : 'text-right'
                        }`}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
            {paddingBottom > 0 && (
              <tr>
                <td style={{ height: paddingBottom }} colSpan={visible.length} />
              </tr>
            )}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div className="p-8 text-center text-[var(--muted)]">
            No symbols match this screen for the selected session.
          </div>
        )}
      </div>
    </div>
  )
}
