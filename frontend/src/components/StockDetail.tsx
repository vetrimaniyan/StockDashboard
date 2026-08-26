/**
 * Stock detail drawer (FR-8.4).
 *
 * Opens over the grid without unmounting it, so grid state (sort, columns,
 * scroll position) survives a round trip into a symbol and back.
 */

import { useEffect, useState } from 'react'
import { api, type MetricDefinition, type StockDetail as Detail } from '../api'
import { byUnit, currency, formatDate, pct, signedPct, directionClass, EM_DASH } from '../format'
import { PriceChart } from './PriceChart'

interface Props {
  symbol: string
  definitions: Map<string, MetricDefinition>
  onClose: () => void
}

export function StockDetail({ symbol, definitions, onClose }: Props) {
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setDetail(null)
    setError(null)
    api
      .stock(symbol)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(String(e.message ?? e)))
    return () => {
      cancelled = true
    }
  }, [symbol])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const groups = new Map<string, MetricDefinition[]>()
  if (detail) {
    for (const def of definitions.values()) {
      if (!(def.name in detail.metrics)) continue
      if (!groups.has(def.group)) groups.set(def.group, [])
      groups.get(def.group)!.push(def)
    }
  }

  const risk = detail?.risk
  const close = detail?.candles.at(-1)?.close ?? null

  return (
    <div className="fixed inset-0 z-50 flex" role="dialog" aria-modal="true">
      <div className="flex-1 bg-black/50" onClick={onClose} />
      <div className="w-full max-w-5xl bg-[var(--bg)] border-l border-[var(--border)] flex flex-col">
        <header className="px-4 py-2.5 border-b border-[var(--border)] flex items-center gap-3">
          <div>
            <h2 className="text-lg font-semibold">{symbol}</h2>
            <p className="text-[var(--muted)]">
              {detail?.name ?? ''} {detail?.industry ? `· ${detail.industry}` : ''}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            {close != null && <span className="text-lg num">{currency(close)}</span>}
            <button
              className="px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--accent)]"
              onClick={onClose}
            >
              Close (Esc)
            </button>
          </div>
        </header>

        {error && <div className="p-4 text-[var(--down)]">{error}</div>}
        {!detail && !error && (
          <div className="p-4 text-[var(--muted)]">Loading {symbol}…</div>
        )}

        {detail && (
          <div className="flex-1 overflow-auto">
            {detail.upcoming_ex_dates.length > 0 && (
              <div className="m-3 rounded border border-[var(--warn)] bg-[rgba(240,180,41,0.1)] p-2.5 text-[var(--warn)]">
                <strong>Upcoming ex-date</strong>
                <span className="ml-2">
                  {detail.upcoming_ex_dates
                    .map(
                      (a) =>
                        `${String(a.action_type)} on ${formatDate(String(a.ex_date))}`,
                    )
                    .join(' · ')}
                </span>
                <p className="text-[var(--muted)] mt-1 leading-snug">
                  A swing entry into an ex-date gap is a known avoidable error.
                </p>
              </div>
            )}

            <div className="h-80 m-3 rounded border border-[var(--border)] bg-[var(--panel)] p-1">
              <PriceChart
                candles={detail.candles}
                high52w={detail.metrics.high_52w as number | null}
                low52w={detail.metrics.low_52w as number | null}
              />
            </div>

            {risk && (
              <section className="m-3 rounded border border-[var(--border)] bg-[var(--panel)]">
                <header className="px-3 py-2 border-b border-[var(--border)]">
                  <h3 className="font-semibold">Risk and cost</h3>
                  <p className="text-[var(--muted)] leading-snug mt-0.5">
                    Sizing assumes 100% cash funding — NRI accounts have no margin or
                    pledged collateral. Figures are planning estimates, not advice.
                  </p>
                </header>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-3">
                  <Stat
                    label="ATR stop"
                    value={currency(risk.atr_stop_price)}
                    note={
                      risk.atr_stop_distance_pct != null
                        ? `${pct(risk.atr_stop_distance_pct)} away`
                        : undefined
                    }
                  />
                  <Stat
                    label="Structural stop"
                    value={currency(risk.structural_stop_price)}
                    note={risk.wider_stop ? `wider: ${risk.wider_stop}` : undefined}
                  />
                  <Stat
                    label="Break-even move"
                    value={pct(risk.breakeven_move_pct)}
                    note="frictions only — tax applies above this"
                  />
                  <Stat
                    label="Cost of a 1R win"
                    value={pct(risk.round_trip_cost_pct)}
                    note={
                      risk.net_gain_at_target_pct != null
                        ? `you keep ${pct(risk.net_gain_at_target_pct)}`
                        : 'frictions + TDS withheld'
                    }
                    tone={risk.cost_exceeds_atr_target ? 'warn' : undefined}
                  />
                </div>
                {risk.cost_exceeds_atr_target && (
                  <p className="mx-3 mb-3 rounded border border-[var(--warn)] bg-[rgba(240,180,41,0.1)] p-2 text-[var(--warn)]">
                    ⚠ Costs and withholding on a 1R win consume the whole ATR-based
                    target — this candidate has no room to pay for itself.
                  </p>
                )}
              </section>
            )}

            <section className="m-3">
              <h3 className="font-semibold mb-2">Metrics</h3>
              <div className="grid gap-3 md:grid-cols-2">
                {Array.from(groups.entries()).map(([group, defs]) => (
                  <div
                    key={group}
                    className="rounded border border-[var(--border)] bg-[var(--panel)]"
                  >
                    <div className="px-3 py-1.5 border-b border-[var(--border)] text-[var(--muted)]">
                      {group}
                    </div>
                    <table className="w-full">
                      <tbody>
                        {defs.map((def) => {
                          const value = detail.metrics[def.name]
                          const signed = def.unit === 'percent' && def.name.startsWith('ret_')
                          return (
                            <tr key={def.name} className="hover:bg-[var(--panel-2)]">
                              <td
                                className="px-3 py-1 cursor-help"
                                title={`${def.formula}\n\n${def.description}`}
                              >
                                {def.label}
                                <span className="ml-1 text-[var(--muted)]">ⓘ</span>
                              </td>
                              <td
                                className={`px-3 py-1 text-right num ${
                                  signed ? directionClass(value as number) : ''
                                }`}
                              >
                                {signed
                                  ? signedPct(value as number)
                                  : byUnit(value, def.unit)}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            </section>

            {detail.corporate_actions.length > 0 && (
              <section className="m-3 rounded border border-[var(--border)] bg-[var(--panel)]">
                <div className="px-3 py-1.5 border-b border-[var(--border)] text-[var(--muted)]">
                  Corporate actions
                </div>
                <table className="w-full">
                  <tbody>
                    {detail.corporate_actions.slice(0, 12).map((a, i) => (
                      <tr key={i} className="hover:bg-[var(--panel-2)]">
                        <td className="px-3 py-1">{formatDate(String(a.ex_date))}</td>
                        <td className="px-3 py-1">{String(a.action_type)}</td>
                        <td className="px-3 py-1 text-right num">
                          {a.action_type === 'DIVIDEND'
                            ? currency(a.amount as number)
                            : a.ratio_to
                              ? `1 : ${a.ratio_to}`
                              : EM_DASH}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string
  note?: string
  tone?: 'warn'
}) {
  return (
    <div className="rounded border border-[var(--border)] bg-[var(--panel-2)] p-2">
      <div className="text-[var(--muted)]">{label}</div>
      <div className={`text-lg num ${tone === 'warn' ? 'text-[var(--warn)]' : ''}`}>
        {value}
      </div>
      {note && <div className="text-[var(--muted)]">{note}</div>}
    </div>
  )
}
