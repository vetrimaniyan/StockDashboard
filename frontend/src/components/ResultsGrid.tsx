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
import { byUnit, directionClass, arrow, EM_DASH, isBlank } from '../format'
import { CardList } from './CardList'
import { ColumnPicker } from './ColumnPicker'

const ROW_HEIGHT = 30

export const DEFAULT_COLUMNS = [
  'tradingsymbol',
  'close',
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

const STATIC_LABELS: Record<string, string> = {
  tradingsymbol: 'Symbol',
  name: 'Company',
  sector: 'Sector',
  industry: 'Industry',
  close: 'Close',
  volume: 'Volume',
  delivery_pct: 'Delivery %',
}

const STATIC_UNITS: Record<string, string> = {
  close: 'currency',
  volume: 'integer',
  delivery_pct: 'percent',
}

/** Metrics where the sign carries meaning and should be shown with an arrow. */
const SIGNED = new Set([
  'ret_1d', 'ret_1w', 'ret_1m', 'ret_3m', 'ret_6m', 'ret_9m', 'ret_12m',
  'ret_12m_1m', 'rs_1m', 'rs_3m', 'rs_6m', 'rs_12m', 'sma_200_slope_1m',
  'pct_from_52w_high', 'pct_above_52w_low', 'composite_z', 'macd_hist',
])

interface Props {
  rows: ScreenRow[]
  definitions: Map<string, MetricDefinition>
  storageKey: string
  onSelect?: (symbol: string) => void
}

function loadColumns(storageKey: string): string[] {
  try {
    const raw = localStorage.getItem(`grid:${storageKey}`)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length) return parsed
    }
  } catch {
    /* storage unavailable or corrupt; fall back to defaults */
  }
  return DEFAULT_COLUMNS
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

export function ResultsGrid({ rows, definitions, storageKey, onSelect }: Props) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [visible, setVisible] = useState<string[]>(() => loadColumns(storageKey))
  const [pickerOpen, setPickerOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const isNarrow = useIsNarrow()

  useEffect(() => {
    setVisible(loadColumns(storageKey))
  }, [storageKey])

  useEffect(() => {
    try {
      localStorage.setItem(`grid:${storageKey}`, JSON.stringify(visible))
    } catch {
      /* persistence is a convenience, not a requirement */
    }
  }, [visible, storageKey])

  const available = useMemo(() => {
    const keys = new Set<string>()
    for (const row of rows.slice(0, 5)) {
      Object.keys(row).forEach((k) => keys.add(k))
    }
    keys.delete('instrument_token')
    keys.delete('trade_date')
    return Array.from(keys).sort()
  }, [rows])

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
      const isText = isSymbol || key === 'name' || key === 'sector' || key === 'industry'

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
          if (isText) return <span>{value == null ? EM_DASH : String(value)}</span>
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
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border)]">
        <span className="text-[var(--muted)]">
          {rows.length} row{rows.length === 1 ? '' : 's'}
          {sorting.length > 0 && (
            <span className="ml-2">
              · sorted by {sorting.map((s) => `${s.id} ${s.desc ? '↓' : '↑'}`).join(', ')}
            </span>
          )}
          <span className="ml-2 opacity-60">· shift-click a header to add a sort</span>
        </span>
        <button
          className="px-2 py-1 rounded border border-[var(--border)] bg-[var(--panel-2)] hover:border-[var(--accent)]"
          onClick={() => setPickerOpen((v) => !v)}
        >
          Columns ({visible.length})
        </button>
      </div>

      {pickerOpen && (
        <ColumnPicker
          available={available}
          visible={visible}
          definitions={definitions}
          staticLabels={STATIC_LABELS}
          onChange={setVisible}
          onClose={() => setPickerOpen(false)}
        />
      )}

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
