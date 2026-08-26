/** Column selection and reordering, persisted per screen (FR-8.3). */

import { useMemo, useState } from 'react'
import type { MetricDefinition } from '../api'

interface Props {
  available: string[]
  visible: string[]
  definitions: Map<string, MetricDefinition>
  staticLabels: Record<string, string>
  onChange: (columns: string[]) => void
  onClose: () => void
}

export function ColumnPicker({
  available,
  visible,
  definitions,
  staticLabels,
  onChange,
  onClose,
}: Props) {
  const [filter, setFilter] = useState('')

  const label = (key: string) => definitions.get(key)?.label ?? staticLabels[key] ?? key

  const grouped = useMemo(() => {
    const groups = new Map<string, string[]>()
    for (const key of available) {
      if (filter && !`${key} ${label(key)}`.toLowerCase().includes(filter.toLowerCase())) {
        continue
      }
      const group = definitions.get(key)?.group ?? 'Identity'
      if (!groups.has(group)) groups.set(group, [])
      groups.get(group)!.push(key)
    }
    return groups
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [available, filter, definitions])

  const toggle = (key: string) => {
    onChange(
      visible.includes(key) ? visible.filter((k) => k !== key) : [...visible, key],
    )
  }

  const move = (key: string, delta: number) => {
    const index = visible.indexOf(key)
    const target = index + delta
    if (index < 0 || target < 0 || target >= visible.length) return
    const next = [...visible]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }

  return (
    <div className="border-b border-[var(--border)] bg-[var(--panel-2)] max-h-80 overflow-auto">
      <div className="flex items-center gap-2 p-2 sticky top-0 bg-[var(--panel-2)] border-b border-[var(--border)]">
        <input
          autoFocus
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter columns…"
          className="px-2 py-1 rounded bg-[var(--panel)] border border-[var(--border)] flex-1"
        />
        <button
          className="px-2 py-1 rounded border border-[var(--border)]"
          onClick={onClose}
        >
          Done
        </button>
      </div>

      <div className="p-2">
        <div className="mb-2 text-[var(--muted)]">Shown, in order</div>
        <div className="flex flex-wrap gap-1 mb-3">
          {visible.map((key) => (
            <span
              key={key}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--panel)] border border-[var(--border)]"
            >
              <button title="Move left" onClick={() => move(key, -1)}>
                ‹
              </button>
              {label(key)}
              <button title="Move right" onClick={() => move(key, 1)}>
                ›
              </button>
              <button
                title="Remove"
                className="text-[var(--down)]"
                onClick={() => toggle(key)}
              >
                ×
              </button>
            </span>
          ))}
        </div>

        {Array.from(grouped.entries()).map(([group, keys]) => (
          <div key={group} className="mb-2">
            <div className="text-[var(--muted)] mb-1">{group}</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-x-3 gap-y-1">
              {keys.map((key) => (
                <label key={key} className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={visible.includes(key)}
                    onChange={() => toggle(key)}
                  />
                  <span title={definitions.get(key)?.formula}>{label(key)}</span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
