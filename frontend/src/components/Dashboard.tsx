/**
 * Landing dashboard (FR-8.1).
 *
 * Layout order is deliberate. Exit signals sit above entry candidates because
 * FR-7.6 requires it: momentum tools overwhelmingly bias toward finding
 * entries, and surfacing exits with equal or greater prominence is a
 * counterweight, not a nicety.
 */

import type { DashboardResponse, ScreenRow } from '../api'
import { currency, signedPct, directionClass, num, EM_DASH } from '../format'
import { IndexValuation } from './IndexValuation'
import { RegimeBanner } from './RegimeBanner'

interface Props {
  data: DashboardResponse
  onSelect: (symbol: string) => void
  onOpenScreen: (name: string) => void
}

function Panel({
  title,
  subtitle,
  tone = 'default',
  children,
  action,
}: {
  title: string
  subtitle?: string
  tone?: 'default' | 'danger'
  children: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <section
      className={`rounded border ${
        tone === 'danger' ? 'border-[var(--down)]' : 'border-[var(--border)]'
      } bg-[var(--panel)] flex flex-col min-h-0`}
    >
      <header className="px-3 py-2 border-b border-[var(--border)] flex items-baseline justify-between gap-2">
        <div>
          <h2 className="font-semibold">{title}</h2>
          {subtitle && (
            <p className="text-[var(--muted)] leading-snug mt-0.5">{subtitle}</p>
          )}
        </div>
        {action}
      </header>
      <div className="overflow-auto flex-1 min-h-0">{children}</div>
    </section>
  )
}

function MiniTable({
  rows,
  columns,
  onSelect,
  empty,
}: {
  rows: ScreenRow[]
  columns: Array<{ key: string; label: string; render: (row: ScreenRow) => React.ReactNode }>
  onSelect: (symbol: string) => void
  empty: string
}) {
  if (!rows.length) {
    return <div className="p-4 text-[var(--muted)]">{empty}</div>
  }
  return (
    <table className="w-full">
      <thead>
        <tr className="text-[var(--muted)]">
          <th className="text-left px-3 py-1 font-medium">Symbol</th>
          {columns.map((c) => (
            <th key={c.key} className="text-right px-3 py-1 font-medium">
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.tradingsymbol} className="hover:bg-[var(--panel-2)]">
            <td className="px-3 py-1">
              <button
                className="text-[var(--accent)] hover:underline font-medium"
                onClick={() => onSelect(row.tradingsymbol)}
              >
                {row.tradingsymbol}
              </button>
            </td>
            {columns.map((c) => (
              <td key={c.key} className="px-3 py-1 text-right num">
                {c.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function Dashboard({ data, onSelect, onOpenScreen }: Props) {
  const maxAbsSector = Math.max(
    ...data.sector_heatmap.map((s) => Math.abs(s.median_ret_1w ?? 0)),
    0.0001,
  )

  return (
    <div className="p-3 space-y-3 overflow-auto">
      <RegimeBanner regime={data.regime} breadth={data.breadth} />

      {data.universe_changes.length > 0 && (
        <div className="rounded border border-[var(--warn)] bg-[rgba(240,180,41,0.1)] p-2.5">
          <strong className="text-[var(--warn)]">Universe changes</strong>
          <p className="text-[var(--muted)] mt-0.5 leading-snug">
            A stock newly entering the index can look like exceptional momentum simply
            because it is newly ranked. Treat these with care for a few sessions.
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {data.universe_changes.slice(0, 25).map((c, i) => (
              <span
                key={`${c.tradingsymbol}-${i}`}
                className={`px-1.5 py-0.5 rounded border ${
                  c.change_type === 'ADDED'
                    ? 'border-[var(--up)] text-[var(--up)]'
                    : 'border-[var(--down)] text-[var(--down)]'
                }`}
              >
                {c.change_type === 'ADDED' ? '+' : '−'} {c.tradingsymbol}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Exits first — FR-7.6. */}
      <Panel
        title="Exit signals"
        tone="danger"
        subtitle="Deteriorating momentum in held or watchlisted names. This is an exit screen for existing holdings, not a short-candidate list."
        action={
          <button
            className="px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--accent)]"
            onClick={() => onOpenScreen('Momentum Breakdown')}
          >
            Open screen
          </button>
        }
      >
        <MiniTable
          rows={data.exit_signals}
          onSelect={onSelect}
          empty="No exit signals for this session."
          columns={[
            {
              key: 'rank',
              label: 'Mom rank',
              render: (r) => (r.momentum_rank == null ? EM_DASH : num(r.momentum_rank as number, 0)),
            },
            {
              key: 'from_high',
              label: 'From 52w high',
              render: (r) => (
                <span className={directionClass(r.pct_from_52w_high as number)}>
                  {signedPct(r.pct_from_52w_high as number)}
                </span>
              ),
            },
            {
              key: 'ret_1w',
              label: '1w',
              render: (r) => (
                <span className={directionClass(r.ret_1w as number)}>
                  {signedPct(r.ret_1w as number)}
                </span>
              ),
            },
          ]}
        />
      </Panel>

      <Panel
        title="Index valuations"
        subtitle="Current P/E for each size segment against its own 7- and 10-year medians. A level alone says nothing; the gap to its own history does."
      >
        <IndexValuation />
      </Panel>

      {/* FR-14.6: pullbacks to support with reversal confirmation. FR-14.7
          requires this to be distinguishable from the "Pullback to Support"
          preset, which is a continuation filter and a different setup. */}
      <Panel
        title="Pullback + reversal"
        subtitle="Top 10 pulled back to a support level and showing reversal confirmation, uptrend intact. Distinct from the Pullback to Support preset, which finds continuation setups inside a perfect trend template."
        action={
          <button
            className="px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--accent)]"
            onClick={() => onOpenScreen('Pullback + Reversal')}
          >
            Open screen
          </button>
        }
      >
        <MiniTable
          rows={data.pullback_reversals}
          onSelect={onSelect}
          empty="No stock is at support with reversal confirmation this session."
          columns={[
            {
              key: 'close',
              label: 'Close',
              render: (r) => currency(r.close as number),
            },
            {
              key: 'support',
              label: 'Support',
              render: (r) => currency(r.support_level as number),
            },
            {
              key: 'dist',
              label: 'To support',
              render: (r) => signedPct(r.support_distance_pct as number),
            },
            {
              key: 'pullback',
              label: 'Pullback',
              render: (r) => signedPct(r.pullback_from_high_pct as number),
            },
            {
              key: 'rev',
              label: 'Reversal',
              render: (r) =>
                r.reversal_score == null ? (
                  <span className="text-[var(--muted)]">{EM_DASH}</span>
                ) : (
                  <span title="RSI turning up, MACD improving, reclaimed 21 EMA, close in top third of range, volume confirmation">
                    {num(r.reversal_score as number, 0)}/5
                  </span>
                ),
            },
            { key: 'rs', label: 'RS', render: (r) => num(r.rs_rating as number, 0) },
          ]}
        />
      </Panel>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel
          title="Momentum leaders"
          subtitle="Top 10 by volatility- and consistency-adjusted momentum score."
          action={
            <button
              className="px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--accent)]"
              onClick={() => onOpenScreen('Momentum Leaders')}
            >
              Open screen
            </button>
          }
        >
          <MiniTable
            rows={data.momentum_leaders}
            onSelect={onSelect}
            empty="No candidates for this session."
            columns={[
              {
                key: 'close',
                label: 'Close',
                render: (r) => currency(r.close as number),
              },
              {
                key: 'score',
                label: 'Score',
                render: (r) => num(r.momentum_score as number, 3),
              },
              { key: 'rs', label: 'RS', render: (r) => num(r.rs_rating as number, 0) },
              {
                key: 'tt',
                label: 'Trend',
                render: (r) =>
                  r.trend_template_score == null
                    ? EM_DASH
                    : `${r.trend_template_score}/8`,
              },
            ]}
          />
        </Panel>

        <Panel
          title="Sector heatmap"
          subtitle="Median 1-week return by industry, eligible names only."
        >
          <div className="p-2 space-y-1">
            {data.sector_heatmap.length === 0 && (
              <div className="text-[var(--muted)] p-2">No sector data yet.</div>
            )}
            {data.sector_heatmap.map((s) => {
              const v = s.median_ret_1w ?? 0
              const width = (Math.abs(v) / maxAbsSector) * 100
              return (
                <div key={s.sector} className="flex items-center gap-2">
                  <span className="w-40 shrink-0 truncate" title={s.sector}>
                    {s.sector}
                  </span>
                  <div className="flex-1 h-4 bg-[var(--panel-2)] rounded relative overflow-hidden">
                    <div
                      className="h-full rounded"
                      style={{
                        width: `${width}%`,
                        background: v >= 0 ? 'var(--up)' : 'var(--down)',
                        opacity: 0.55,
                      }}
                    />
                  </div>
                  <span
                    className={`num w-24 text-right ${directionClass(s.median_ret_1w)}`}
                  >
                    {signedPct(s.median_ret_1w)}
                  </span>
                  <span className="text-[var(--muted)] w-8 text-right">{s.count}</span>
                </div>
              )
            })}
          </div>
        </Panel>
      </div>

      <Panel title="Breadth" subtitle="Universe-level participation for this session.">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 p-3">
          {[
            { label: 'Advances', value: data.breadth.advances, tone: 'up' },
            { label: 'Declines', value: data.breadth.declines, tone: 'down' },
            { label: 'New highs', value: data.breadth.new_highs, tone: 'up' },
            { label: 'New lows', value: data.breadth.new_lows, tone: 'down' },
            {
              label: 'Eligible universe',
              value: data.breadth.universe,
              tone: 'neutral',
            },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded border border-[var(--border)] bg-[var(--panel-2)] p-2"
            >
              <div className="text-[var(--muted)]">{s.label}</div>
              <div
                className={`text-xl num ${
                  s.tone === 'up'
                    ? 'text-[var(--up)]'
                    : s.tone === 'down'
                      ? 'text-[var(--down)]'
                      : ''
                }`}
              >
                {s.value}
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
