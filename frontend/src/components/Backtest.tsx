/** Backtest workspace (SRS Phase 3).

The design puts the caveats above the numbers rather than below them. A
backtest result is the most persuasive artefact this application produces and
the least trustworthy, so the survivorship warning, the overfitting verdict and
the out-of-sample degradation are not footnotes — they sit where the eye lands
before the CAGR does. */

import { useEffect, useState } from 'react'
import {
  ApiError,
  api,
  type BacktestAvailability,
  type BacktestResponse,
  type PresetSummary,
} from '../api'
import { EquityChart } from './EquityChart'
import { currency, formatDate } from '../format'

const SWEEP_VALUES = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]

function pctText(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(digits)}%`
}

function numText(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toFixed(digits)
}

/** FR-8.11: sign carries the meaning, colour only reinforces it. */
function Signed({ value, digits = 2 }: { value: number | null; digits?: number }) {
  if (value === null || !Number.isFinite(value)) return <span>—</span>
  const positive = value > 0
  const cls = value === 0 ? '' : positive ? 'text-[var(--up)]' : 'text-[var(--down)]'
  return (
    <span className={cls}>
      {positive ? '▲' : value < 0 ? '▼' : ''} {value.toFixed(digits)}%
    </span>
  )
}

function Callout({
  tone,
  title,
  children,
}: {
  tone: 'danger' | 'warn'
  title: string
  children: React.ReactNode
}) {
  const palette =
    tone === 'danger'
      ? 'border-[var(--down)] bg-[rgba(239,95,107,0.10)] text-[var(--down)]'
      : 'border-[var(--warn)] bg-[rgba(224,168,74,0.10)] text-[var(--warn)]'
  return (
    <div className={`border rounded px-3 py-2 ${palette}`}>
      <div className="font-semibold mb-1">⚠ {title}</div>
      <div className="text-[var(--text)] leading-relaxed">{children}</div>
    </div>
  )
}

export function Backtest({ presets }: { presets: PresetSummary[] }) {
  const [availability, setAvailability] = useState<BacktestAvailability | null>(null)
  const [screenName, setScreenName] = useState('Momentum Leaders')
  const [stop, setStop] = useState(3.0)
  const [trailing, setTrailing] = useState(false)
  const [useExit, setUseExit] = useState(true)
  const [maxPositions, setMaxPositions] = useState(10)
  const [capital, setCapital] = useState(1_000_000)
  const [withSweep, setWithSweep] = useState(false)
  const [withWalkForward, setWithWalkForward] = useState(false)

  const [result, setResult] = useState<BacktestResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .backtestAvailability()
      .then(setAvailability)
      .catch((e: ApiError) => setError(e.message))
  }, [])

  const run = () => {
    setRunning(true)
    setError(null)
    api
      .backtest({
        screen_name: screenName,
        stop_atr_multiple: stop,
        trailing_stop: trailing,
        use_exit_screen: useExit,
        max_positions: maxPositions,
        initial_capital: capital,
        ...(withSweep || withWalkForward ? { sweep: SWEEP_VALUES } : {}),
        ...(withWalkForward ? { walk_forward: true } : {}),
      })
      .then(setResult)
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setRunning(false))
  }

  const entryScreens = presets.filter((p) => !p.is_exit_screen)

  if (availability && !availability.ready) {
    return (
      <div className="p-6 max-w-3xl">
        <Callout tone="warn" title="History not materialised">
          {availability.reason}
          <pre className="mt-3 px-3 py-2 rounded bg-[var(--panel-2)] text-[var(--text)] overflow-x-auto">
            alpha500 materialise
          </pre>
        </Callout>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto p-3 space-y-3">
      <section className="border border-[var(--border)] rounded bg-[var(--panel)] p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[var(--muted)]">Screen</span>
            <select
              className="px-2 py-1 rounded border border-[var(--border)] bg-[var(--panel-2)]"
              value={screenName}
              onChange={(e) => setScreenName(e.target.value)}
            >
              {entryScreens.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[var(--muted)]">ATR stop (k)</span>
            <input
              type="number"
              step="0.5"
              min="0.5"
              className="w-24 px-2 py-1 rounded border border-[var(--border)] bg-[var(--panel-2)]"
              value={stop}
              onChange={(e) => setStop(Number(e.target.value))}
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[var(--muted)]">Max positions</span>
            <input
              type="number"
              min="1"
              className="w-24 px-2 py-1 rounded border border-[var(--border)] bg-[var(--panel-2)]"
              value={maxPositions}
              onChange={(e) => setMaxPositions(Number(e.target.value))}
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[var(--muted)]">Capital (₹)</span>
            <input
              type="number"
              step="100000"
              className="w-32 px-2 py-1 rounded border border-[var(--border)] bg-[var(--panel-2)]"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
            />
          </label>

          <label className="flex items-center gap-2">
            <input type="checkbox" checked={trailing} onChange={(e) => setTrailing(e.target.checked)} />
            <span>Trailing stop</span>
          </label>

          <label className="flex items-center gap-2">
            <input type="checkbox" checked={useExit} onChange={(e) => setUseExit(e.target.checked)} />
            <span>Exit on breakdown</span>
          </label>

          <label className="flex items-center gap-2">
            <input type="checkbox" checked={withSweep} onChange={(e) => setWithSweep(e.target.checked)} />
            <span>Sweep stop</span>
          </label>

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={withWalkForward}
              onChange={(e) => setWithWalkForward(e.target.checked)}
            />
            <span>Walk-forward</span>
          </label>

          <button
            onClick={run}
            disabled={running}
            className="px-3 py-1 rounded border border-[var(--accent)] bg-[var(--panel-2)] disabled:opacity-50"
          >
            {running ? 'Running…' : 'Run backtest'}
          </button>

          {availability && (
            <span className="text-[var(--muted)] ml-auto">
              {availability.sessions.toLocaleString()} sessions materialised
              {availability.start && ` · ${formatDate(availability.start)} → ${formatDate(availability.end!)}`}
            </span>
          )}
        </div>
        {(withSweep || withWalkForward) && (
          <div className="mt-2 text-[var(--muted)]">
            Sweeping {SWEEP_VALUES.length} stop values
            {withWalkForward && ' with walk-forward'} runs the simulation many times —
            expect this to take a minute or two.
          </div>
        )}
      </section>

      {error && (
        <div className="px-3 py-2 rounded border border-[var(--down)] bg-[rgba(239,95,107,0.12)] text-[var(--down)]">
          {error}
        </div>
      )}

      {running && !result && (
        <div className="p-8 text-[var(--muted)]">Simulating…</div>
      )}

      {result && (
        <>
          {result.warnings.map((w, i) => (
            <Callout key={i} tone="danger" title="Read this before the numbers">
              {w}
            </Callout>
          ))}

          {result.walk_forward?.warning && (
            <Callout tone="danger" title="Out-of-sample degradation">
              {result.walk_forward.warning}
            </Callout>
          )}

          {result.sweep?.warning && (
            <Callout tone="warn" title="Parameter sensitivity">
              {result.sweep.warning}
            </Callout>
          )}

          <section className="grid gap-3 lg:grid-cols-[2fr_1fr]">
            <div className="border border-[var(--border)] rounded bg-[var(--panel)] p-3">
              <div className="flex items-baseline justify-between mb-2">
                <h2 className="font-semibold">Equity curve</h2>
                <span className="text-[var(--muted)]">
                  {result.start && formatDate(result.start)} → {result.end && formatDate(result.end)}
                  {' · '}
                  {result.sessions.toLocaleString()} sessions
                </span>
              </div>
              <EquityChart result={result} />
              <div className="flex gap-4 mt-2 text-[var(--muted)]">
                <span><span className="text-[var(--up)]">━</span> gross of tax</span>
                <span><span className="text-[var(--down)]">━</span> net of tax</span>
                {result.benchmark && (
                  <span><span className="text-[var(--muted)]">┅</span> {result.benchmark.index_name} buy &amp; hold</span>
                )}
              </div>
            </div>

            <div className="border border-[var(--border)] rounded bg-[var(--panel)] p-3">
              <h2 className="font-semibold mb-2">Result</h2>
              <table className="w-full">
                <thead className="text-[var(--muted)]">
                  <tr>
                    <th className="text-left font-normal">&nbsp;</th>
                    <th className="text-right font-normal">gross</th>
                    <th className="text-right font-normal">net of tax</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="py-1">CAGR</td>
                    <td className="text-right"><Signed value={result.gross_of_tax.cagr_pct} /></td>
                    <td className="text-right"><Signed value={result.net_of_tax.cagr_pct} /></td>
                  </tr>
                  <tr>
                    <td className="py-1">Total return</td>
                    <td className="text-right"><Signed value={result.gross_of_tax.total_return_pct} /></td>
                    <td className="text-right"><Signed value={result.net_of_tax.total_return_pct} /></td>
                  </tr>
                  <tr>
                    <td className="py-1">Max drawdown</td>
                    <td className="text-right"><Signed value={result.gross_of_tax.max_drawdown_pct} /></td>
                    <td className="text-right"><Signed value={result.net_of_tax.max_drawdown_pct} /></td>
                  </tr>
                  <tr>
                    <td className="py-1">Sharpe</td>
                    <td className="text-right">{numText(result.gross_of_tax.sharpe)}</td>
                    <td className="text-right">{numText(result.net_of_tax.sharpe)}</td>
                  </tr>
                  <tr>
                    <td className="py-1">Sortino</td>
                    <td className="text-right">{numText(result.gross_of_tax.sortino)}</td>
                    <td className="text-right">{numText(result.net_of_tax.sortino)}</td>
                  </tr>
                  <tr>
                    <td className="py-1">Final equity</td>
                    <td className="text-right">{currency(result.gross_of_tax.final_equity)}</td>
                    <td className="text-right">{currency(result.net_of_tax.final_equity)}</td>
                  </tr>
                </tbody>
              </table>

              {result.benchmark && (
                <div className="mt-3 pt-3 border-t border-[var(--border)]">
                  <div className="text-[var(--muted)] mb-1">
                    {result.benchmark.index_name} buy &amp; hold
                  </div>
                  <div className="flex justify-between">
                    <span>CAGR</span>
                    <Signed value={result.benchmark.cagr_pct} />
                  </div>
                  <div className="flex justify-between">
                    <span>Max drawdown</span>
                    <Signed value={result.benchmark.max_drawdown_pct} />
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="border border-[var(--border)] rounded bg-[var(--panel)] p-3">
            <h2 className="font-semibold mb-2">Trades</h2>
            <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Closed trades" value={result.trades.trades.toLocaleString()} />
              <Stat label="Hit rate" value={pctText(result.trades.hit_rate_pct, 1)} />
              <Stat label="Avg win" value={pctText(result.trades.avg_win_pct)} />
              <Stat label="Avg loss" value={pctText(result.trades.avg_loss_pct)} />
              <Stat label="Win/loss ratio" value={numText(result.trades.win_loss_ratio)} />
              <Stat label="Avg hold" value={`${numText(result.trades.avg_holding_days, 0)} d`} />
              <Stat label="Exposure" value={pctText(result.trades.exposure_pct, 0)} />
              <Stat label="Costs" value={currency(result.trades.total_costs)} />
              <Stat
                label="TDS withheld"
                value={currency(result.trades.total_tds)}
                hint="Deducted at settlement of each profitable exit (FR-12.4)"
              />
            </div>
          </section>

          {result.sweep && (
            <section className="border border-[var(--border)] rounded bg-[var(--panel)] p-3">
              <h2 className="font-semibold mb-2">
                Stop sweep — plateau width {result.sweep.plateau_width} of{' '}
                {result.sweep.points.length}
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="text-[var(--muted)]">
                    <tr>
                      <th className="text-left font-normal py-1">ATR multiple</th>
                      <th className="text-right font-normal">net CAGR</th>
                      <th className="text-right font-normal">trades</th>
                      <th className="text-right font-normal">max drawdown</th>
                      <th className="text-right font-normal">Sharpe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.sweep.points.map((pt) => {
                      const best = pt.value === result.sweep!.best_value
                      return (
                        <tr
                          key={pt.value}
                          className={best ? 'bg-[var(--panel-2)]' : ''}
                        >
                          <td className="py-1">
                            k = {pt.value}
                            {best && <span className="ml-2 text-[var(--accent)]">best</span>}
                          </td>
                          <td className="text-right"><Signed value={pt.metric} /></td>
                          <td className="text-right">{pt.trades}</td>
                          <td className="text-right"><Signed value={pt.max_drawdown_pct} /></td>
                          <td className="text-right">{numText(pt.sharpe)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {result.walk_forward && result.walk_forward.windows.length > 0 && (
            <section className="border border-[var(--border)] rounded bg-[var(--panel)] p-3">
              <h2 className="font-semibold mb-2">Walk-forward</h2>
              <p className="text-[var(--muted)] mb-2">
                The stop is chosen on the training window, then measured on data it
                never saw. Test windows are six months, so annualised figures swing
                widely — read the mean, not any single row.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="text-[var(--muted)]">
                    <tr>
                      <th className="text-left font-normal py-1">Test window</th>
                      <th className="text-right font-normal">chosen k</th>
                      <th className="text-right font-normal">in-sample</th>
                      <th className="text-right font-normal">out-of-sample</th>
                      <th className="text-right font-normal">trades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.walk_forward.windows.map((w) => (
                      <tr key={w.test_start}>
                        <td className="py-1">
                          {formatDate(w.test_start)} → {formatDate(w.test_end)}
                        </td>
                        <td className="text-right">{w.chosen_value}</td>
                        <td className="text-right"><Signed value={w.in_sample_cagr} /></td>
                        <td className="text-right"><Signed value={w.out_of_sample_cagr} /></td>
                        <td className="text-right">{w.out_of_sample_trades}</td>
                      </tr>
                    ))}
                    <tr className="border-t border-[var(--border)] font-semibold">
                      <td className="py-1">Mean</td>
                      <td />
                      <td className="text-right">
                        <Signed value={result.walk_forward.in_sample_cagr} />
                      </td>
                      <td className="text-right">
                        <Signed value={result.walk_forward.out_of_sample_cagr} />
                      </td>
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {result.trades_detail.length > 0 && (
            <section className="border border-[var(--border)] rounded bg-[var(--panel)] p-3">
              <h2 className="font-semibold mb-2">
                Trade log ({result.trades_detail.length.toLocaleString()})
              </h2>
              <div className="max-h-[420px] overflow-auto">
                <table className="w-full">
                  <thead className="text-[var(--muted)] sticky top-0 bg-[var(--panel)]">
                    <tr>
                      <th className="text-left font-normal py-1">Symbol</th>
                      <th className="text-left font-normal">Entry</th>
                      <th className="text-left font-normal">Exit</th>
                      <th className="text-left font-normal">Reason</th>
                      <th className="text-right font-normal">Days</th>
                      <th className="text-right font-normal">Costs</th>
                      <th className="text-right font-normal">TDS</th>
                      <th className="text-right font-normal">Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades_detail.map((t, i) => (
                      <tr key={`${t.symbol}-${t.entry_date}-${i}`} className="border-t border-[var(--border)]">
                        <td className="py-1 font-medium">{t.symbol}</td>
                        <td>{formatDate(t.entry_date)}</td>
                        <td>{t.exit_date ? formatDate(t.exit_date) : '— open —'}</td>
                        <td className="text-[var(--muted)]">{t.exit_reason ?? '—'}</td>
                        <td className="text-right">{t.holding_days}</td>
                        <td className="text-right">{currency(t.costs)}</td>
                        <td className="text-right">{t.tds > 0 ? currency(t.tds) : '—'}</td>
                        <td className="text-right"><Signed value={t.net_return_pct} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex justify-between gap-3" title={hint}>
      <span className="text-[var(--muted)]">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}
