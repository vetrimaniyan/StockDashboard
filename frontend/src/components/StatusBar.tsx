/**
 * Data-as-of indicator (FR-8.9).
 *
 * Staleness must be loud and must carry a reason. Silently serving yesterday's
 * data as though it were today's is the single most dangerous failure mode in
 * this class of tool, so a stale state gets a warning treatment rather than a
 * quiet grey date.
 */

import type { DataStatus } from '../api'
import { formatDate } from '../format'

export function StatusBar({ status }: { status: DataStatus | null }) {
  if (!status) {
    return (
      <div className="px-3 py-1.5 text-[var(--muted)] border-b border-[var(--border)]">
        Loading data status…
      </div>
    )
  }

  const stale = status.is_stale
  return (
    <div
      role={stale ? 'alert' : undefined}
      className={`px-3 py-1.5 border-b flex items-center gap-3 flex-wrap ${
        stale
          ? 'bg-[rgba(240,180,41,0.12)] border-[var(--warn)] text-[var(--warn)]'
          : 'bg-[var(--panel)] border-[var(--border)] text-[var(--muted)]'
      }`}
    >
      <span className="font-medium">
        {status.engine_stale
          ? '⚠ Metrics out of date with the engine'
          : stale
            ? '⚠ Data is stale'
            : '● Data current'}
      </span>
      <span>
        as of <strong>{formatDate(status.data_as_of)}</strong>
      </span>
      {status.latest_session && status.data_as_of !== status.latest_session && (
        <span>· latest completed session {formatDate(status.latest_session)}</span>
      )}
      {status.reason && <span className="opacity-90">· {status.reason}</span>}
      {status.last_run_status && (
        <span className="ml-auto opacity-75">
          last pipeline stage: {status.last_run_status}
        </span>
      )}
    </div>
  )
}
