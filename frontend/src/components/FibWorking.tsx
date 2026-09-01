/**
 * FR-17.9 — "show working" for the Fibonacci retracement zone.
 *
 * Every number the screen used, with the arithmetic that produced it. A level
 * the operator cannot re-derive is a level they will either over-trust or
 * ignore, and neither is useful.
 *
 * The word "support" is deliberately absent. A Fibonacci level is geometry
 * projected onto a past advance; support is where buyers actually appeared,
 * which is a different metric (support_level, FR-14.2).
 */

type Metrics = Record<string, unknown>

const num = (m: Metrics, key: string): number | null => {
  const v = m[key]
  return typeof v === 'number' && isFinite(v) ? v : null
}
const str = (m: Metrics, key: string): string | null => {
  const v = m[key]
  return typeof v === 'string' && v.length > 0 ? v : null
}
const money = (v: number | null) => (v == null ? '—' : `₹${v.toFixed(2)}`)
const pct = (v: number | null, dp = 2) => (v == null ? '—' : `${(v * 100).toFixed(dp)}%`)
const ratio = (v: number | null, dp = 3) => (v == null ? '—' : v.toFixed(dp))

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 border-b border-[var(--border)] last:border-0">
      <span className="text-[var(--muted)]">{label}</span>
      <span className="num text-right">{children}</span>
    </div>
  )
}

export function FibWorking({ metrics }: { metrics: Metrics }) {
  const a = num(metrics, 'fib_leg_low_price')
  const b = num(metrics, 'fib_leg_high_price')
  const reason = str(metrics, 'fib_exclusion_reason')

  // No leg is a real answer, not an empty panel (FR-17.8).
  if (a == null || b == null) {
    return (
      <section className="m-3 rounded border border-[var(--border)] bg-[var(--panel)]">
        <header className="px-3 py-2 border-b border-[var(--border)]">
          <h3 className="font-semibold">Retracement zone</h3>
        </header>
        <p className="px-3 py-2 text-[var(--muted)]">
          No impulse leg qualifies today
          {reason ? <> — <code>{reason}</code></> : null}. The screen is not
          hiding a setup; there is not one to show.
        </p>
      </section>
    )
  }

  const span = b - a
  const close = num(metrics, 'close') ?? num(metrics, 'close_adj')
  const status = str(metrics, 'fib_zone_status') ?? 'NONE'
  const entry = str(metrics, 'fib_zone_entry_type')
  const stop = num(metrics, 'fib_stop')
  const rr = num(metrics, 'fib_reward_risk')
  const impulse = num(metrics, 'vol_impulse_ratio')
  const dryup = num(metrics, 'vol_dryup_ratio')
  const delivery = num(metrics, 'delivery_pct')
  const deliveryMean = num(metrics, 'delivery_pct_sma_20')
  const lowDelivery =
    delivery != null && deliveryMean != null && delivery < deliveryMean * 0.8

  const levels: Array<[string, number | null]> = [
    ['38.2%', num(metrics, 'fib_level_382')],
    ['50%', num(metrics, 'fib_level_500')],
    ['61.8%', num(metrics, 'fib_level_618')],
    ['78.6%', num(metrics, 'fib_level_786')],
  ]

  return (
    <section className="m-3 rounded border border-[var(--border)] bg-[var(--panel)]">
      <header className="px-3 py-2 border-b border-[var(--border)] flex items-baseline justify-between gap-3">
        <div>
          <h3 className="font-semibold">Retracement zone — working</h3>
          <p className="text-[var(--muted)] leading-snug mt-0.5">
            Levels are geometry on the last advance, not places buyers have
            appeared. Arriving in the band is arithmetic; the reversal bar is
            the event.
          </p>
        </div>
        <span
          className={
            status === 'TRIGGERED'
              ? 'text-[var(--up)] font-semibold'
              : status === 'ARMED'
                ? 'text-[var(--warn,#f0b429)] font-semibold'
                : 'text-[var(--muted)]'
          }
        >
          {status}
        </span>
      </header>

      <div className="px-3 py-2 grid md:grid-cols-2 gap-x-8">
        <div>
          <h4 className="text-[var(--muted)] mb-1">The leg</h4>
          <Row label="A — swing low">
            {money(a)} · {str(metrics, 'fib_leg_low_date') ?? '—'}
          </Row>
          <Row label="B — swing high">
            {money(b)} · {str(metrics, 'fib_leg_high_date') ?? '—'}
          </Row>
          <Row label="Usable from">
            {str(metrics, 'fib_leg_confirmed_date') ?? '—'}
          </Row>
          <Row label="Amplitude (B−A)/A">
            {pct(num(metrics, 'fib_leg_amplitude_pct'))}
          </Row>
          <Row label="R = B − A">{money(span)}</Row>
          <Row label="Length">
            {num(metrics, 'fib_leg_sessions') ?? '—'} sessions
          </Row>
        </div>

        <div>
          <h4 className="text-[var(--muted)] mb-1">Levels — B − r × R</h4>
          {levels.map(([label, value]) => (
            <Row key={label} label={label}>
              {money(b)} − {label.replace('%', '')}% × {money(span)} ={' '}
              <strong>{money(value)}</strong>
            </Row>
          ))}
          <Row label="Retracement (B−C)/R">
            {close != null ? `(${money(b)} − ${money(close)}) / ${money(span)} = ` : ''}
            {ratio(num(metrics, 'fib_retracement_ratio'), 5)}
          </Row>
          <Row label="Deepest since B">
            {ratio(num(metrics, 'fib_max_retracement'), 5)}
          </Row>
        </div>

        <div className="mt-2">
          <h4 className="text-[var(--muted)] mb-1">Volume shape</h4>
          <Row label="Impulse — mean(A→B) / mean(50 before A)">
            {ratio(impulse)}
          </Row>
          <Row label="Dry-up — mean(B→today) / mean(A→B)">{ratio(dryup)}</Row>
          <Row label="Relative volume today">
            {ratio(num(metrics, 'rel_volume'), 2)}
          </Row>
          {lowDelivery && (
            // FR-2.7 is warn-not-block: a caution badge, never a filter.
            <p className="mt-1 text-[var(--warn,#f0b429)]">
              ⚠ Delivery {pct(delivery, 1)} is below its 20-session mean of{' '}
              {pct(deliveryMean, 1)} — more of today's volume was intraday
              churn than committed buying.
            </p>
          )}
        </div>

        <div className="mt-2">
          <h4 className="text-[var(--muted)] mb-1">Stop, target, reward</h4>
          <Row label="Stop — wider of 78.6% / swing − 0.5 ATR">
            {money(stop)}
          </Row>
          <Row label="Risk per share">
            {close != null && stop != null ? money(close - stop) : '—'}
          </Row>
          <Row label="Target — B">{money(num(metrics, 'fib_target'))}</Row>
          <Row label="Reward : risk">{ratio(rr, 2)}</Row>
          <Row label="Zone entry">{entry ?? '—'}</Row>
          <Row label="Sessions in band">
            {num(metrics, 'fib_sessions_in_zone') ?? '—'}
          </Row>
        </div>
      </div>

      {reason && (
        <p className="px-3 pb-2 text-[var(--muted)]">
          Not in the screen today: <code>{reason}</code>
        </p>
      )}
    </section>
  )
}
