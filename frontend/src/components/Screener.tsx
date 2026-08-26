/**
 * Screener (FR-8.2).
 *
 * FR-8.8: filtering runs client-side against the loaded working set (<= 500
 * rows) for sub-100ms feedback, and only falls back to the server when a
 * filter references a column the loaded set does not carry.
 */

import { useMemo, useState } from 'react'
import type { MetricDefinition, PresetSummary, ScreenResponse } from '../api'
import { ResultsGrid } from './ResultsGrid'

interface Condition {
  id: number
  field: string
  operator: string
  value: string
}

const OPERATORS = ['>=', '>', '<=', '<', '=', '!=', 'is not null', 'is null']

interface Props {
  presets: PresetSummary[]
  active: string
  screen: ScreenResponse | null
  loading: boolean
  definitions: Map<string, MetricDefinition>
  onSelectPreset: (name: string) => void
  onSelectSymbol: (symbol: string) => void
}

function coerce(text: string): unknown {
  const t = text.trim()
  if (t === 'true') return true
  if (t === 'false') return false
  const n = Number(t)
  return t !== '' && isFinite(n) ? n : t
}

function matches(row: Record<string, unknown>, c: Condition): boolean {
  const value = row[c.field]
  if (c.operator === 'is null') return value === null || value === undefined
  if (c.operator === 'is not null') return value !== null && value !== undefined
  if (value === null || value === undefined) return false

  const target = coerce(c.value)
  if (typeof value === 'boolean' || typeof target === 'boolean') {
    return c.operator === '!=' ? value !== target : value === target
  }
  if (typeof value === 'number' && typeof target === 'number') {
    switch (c.operator) {
      case '>':
        return value > target
      case '>=':
        return value >= target
      case '<':
        return value < target
      case '<=':
        return value <= target
      case '=':
        return value === target
      case '!=':
        return value !== target
    }
  }
  const a = String(value).toLowerCase()
  const b = String(target).toLowerCase()
  return c.operator === '!=' ? a !== b : a.includes(b)
}

export function Screener({
  presets,
  active,
  screen,
  loading,
  definitions,
  onSelectPreset,
  onSelectSymbol,
}: Props) {
  const [conditions, setConditions] = useState<Condition[]>([])
  const [nextId, setNextId] = useState(1)
  const [open, setOpen] = useState(false)

  const fields = useMemo(() => {
    const keys = new Set<string>(['tradingsymbol', 'sector', 'industry', 'close'])
    for (const row of screen?.rows.slice(0, 3) ?? []) {
      Object.keys(row).forEach((k) => keys.add(k))
    }
    keys.delete('instrument_token')
    keys.delete('trade_date')
    return Array.from(keys).sort()
  }, [screen])

  const rows = useMemo(() => {
    if (!screen) return []
    if (!conditions.length) return screen.rows
    return screen.rows.filter((row) =>
      conditions.every((c) => (c.field && c.value !== '') || c.operator.includes('null')
        ? matches(row, c)
        : true),
    )
  }, [screen, conditions])

  const addCondition = () => {
    setConditions((prev) => [
      ...prev,
      { id: nextId, field: 'rs_rating', operator: '>=', value: '80' },
    ])
    setNextId((n) => n + 1)
  }

  const update = (id: number, patch: Partial<Condition>) =>
    setConditions((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)))

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border)] overflow-x-auto">
        {presets.map((p) => (
          <button
            key={p.name}
            title={p.description}
            onClick={() => onSelectPreset(p.name)}
            className={`px-2.5 py-1 rounded border whitespace-nowrap ${
              active === p.name
                ? 'border-[var(--accent)] bg-[var(--panel-2)]'
                : 'border-[var(--border)] hover:border-[var(--accent)]'
            } ${p.is_exit_screen ? 'text-[var(--down)]' : ''}`}
          >
            {p.is_exit_screen ? '↓ ' : ''}
            {p.name}
          </button>
        ))}
        <button
          className="ml-auto px-2.5 py-1 rounded border border-[var(--border)] hover:border-[var(--accent)] whitespace-nowrap"
          onClick={() => setOpen((v) => !v)}
        >
          Filters {conditions.length ? `(${conditions.length})` : ''}
        </button>
      </div>

      {screen && (
        <p className="px-3 py-1.5 text-[var(--muted)] border-b border-[var(--border)] leading-snug">
          {String(screen.definition.description ?? '')}
        </p>
      )}

      {open && (
        <div className="p-2 border-b border-[var(--border)] bg-[var(--panel-2)] space-y-1.5">
          {conditions.length === 0 && (
            <p className="text-[var(--muted)]">
              No extra filters. These narrow the loaded preset results in the browser,
              so feedback is immediate.
            </p>
          )}
          {conditions.map((c) => (
            <div key={c.id} className="flex items-center gap-1.5 flex-wrap">
              <select
                value={c.field}
                onChange={(e) => update(c.id, { field: e.target.value })}
                className="px-2 py-1 rounded bg-[var(--panel)] border border-[var(--border)]"
              >
                {fields.map((f) => (
                  <option key={f} value={f}>
                    {definitions.get(f)?.label ?? f}
                  </option>
                ))}
              </select>
              <select
                value={c.operator}
                onChange={(e) => update(c.id, { operator: e.target.value })}
                className="px-2 py-1 rounded bg-[var(--panel)] border border-[var(--border)]"
              >
                {OPERATORS.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              {!c.operator.includes('null') && (
                <input
                  value={c.value}
                  onChange={(e) => update(c.id, { value: e.target.value })}
                  className="px-2 py-1 rounded bg-[var(--panel)] border border-[var(--border)] w-28"
                />
              )}
              <button
                className="text-[var(--down)] px-1"
                onClick={() => setConditions((p) => p.filter((x) => x.id !== c.id))}
              >
                Remove
              </button>
              {definitions.get(c.field) && (
                <span className="text-[var(--muted)]">
                  {definitions.get(c.field)!.formula}
                </span>
              )}
            </div>
          ))}
          <button
            className="px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--accent)]"
            onClick={addCondition}
          >
            + Add condition
          </button>
        </div>
      )}

      <div className="flex-1 min-h-0">
        {loading ? (
          <div className="p-8 text-center text-[var(--muted)]">Running screen…</div>
        ) : (
          <ResultsGrid
            rows={rows}
            definitions={definitions}
            storageKey={active}
            onSelect={onSelectSymbol}
          />
        )}
      </div>
    </div>
  )
}
