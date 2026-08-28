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
  const [dragging, setDragging] = useState<number | null>(null)
  const [dropAt, setDropAt] = useState<number | null>(null)

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

  /** Lift one column out of the order and drop it before `to`. */
  const reorder = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0) return
    const next = [...visible]
    const [moved] = next.splice(from, 1)
    next.splice(from < to ? to - 1 : to, 0, moved)
    onChange(next)
  }

  const onDragStart = (index: number) => (e: React.DragEvent) => {
    setDragging(index)
    e.dataTransfer.effectAllowed = 'move'
    // Firefox refuses to start a drag unless some data is set.
    e.dataTransfer.setData('text/plain', String(index))
  }

  const onDragOver = (index: number) => (e: React.DragEvent) => {
    if (dragging === null) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    // Drop before or after the hovered chip depending on which half the
    // pointer is over, so a column can be placed at either end.
    const box = e.currentTarget.getBoundingClientRect()
    const after = e.clientX > box.left + box.width / 2
    setDropAt(index + (after ? 1 : 0))
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (dragging !== null && dropAt !== null) reorder(dragging, dropAt)
    setDragging(null)
    setDropAt(null)
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
        <div className="mb-2 text-[var(--muted)]">
          Shown, in order — drag to rearrange, or focus a column and use
          <kbd className="mx-1 px-1 rounded border border-[var(--border)]">←</kbd>
          <kbd className="mr-1 px-1 rounded border border-[var(--border)]">→</kbd>
        </div>
        <div
          className="flex flex-wrap gap-1 mb-3"
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
        >
          {visible.map((key, index) => (
            <span
              key={key}
              draggable
              onDragStart={onDragStart(index)}
              onDragOver={onDragOver(index)}
              onDragEnd={() => {
                setDragging(null)
                setDropAt(null)
              }}
              tabIndex={0}
              role="button"
              aria-label={`${label(key)}, position ${index + 1} of ${visible.length}`}
              onKeyDown={(e) => {
                // NFR-6.2: reordering must be reachable without a pointer.
                if (e.key === 'ArrowLeft') {
                  e.preventDefault()
                  move(key, -1)
                } else if (e.key === 'ArrowRight') {
                  e.preventDefault()
                  move(key, 1)
                } else if (e.key === 'Delete' || e.key === 'Backspace') {
                  e.preventDefault()
                  toggle(key)
                }
              }}
              className={[
                'inline-flex items-center gap-1 px-2 py-0.5 rounded border cursor-grab select-none',
                'bg-[var(--panel)] border-[var(--border)]',
                dragging === index ? 'opacity-40' : '',
                // The insertion point is shown as an edge, so the position a
                // column will land in is visible before the drop.
                dropAt === index ? 'border-l-2 border-l-[var(--accent)]' : '',
                dropAt === index + 1 ? 'border-r-2 border-r-[var(--accent)]' : '',
              ].join(' ')}
            >
              <span aria-hidden className="text-[var(--muted)]">⠿</span>
              <button
                title="Move left"
                aria-label={`Move ${label(key)} left`}
                tabIndex={-1}
                onClick={() => move(key, -1)}
              >
                ‹
              </button>
              {label(key)}
              <button
                title="Move right"
                aria-label={`Move ${label(key)} right`}
                tabIndex={-1}
                onClick={() => move(key, 1)}
              >
                ›
              </button>
              <button
                title="Remove"
                aria-label={`Remove ${label(key)}`}
                tabIndex={-1}
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
