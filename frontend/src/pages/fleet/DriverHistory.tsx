import { History } from 'lucide-react'
import { useApi } from '../../hooks/useApi'
import { formatDateTime } from '../../lib/format'
import type { DriverAssignment } from '../../lib/types'

const SOURCE_NOTE: Record<DriverAssignment['source'], string | null> = {
  manual: null,
  backfill: 'Start date estimated when history tracking was introduced',
  sample: 'Sample data',
}

/** Driver-assignment history for one truck (newest first). Shown to operational roles only. */
export function DriverHistory({ truckId, version, limit = 5 }: { truckId: number; version: number; limit?: number }) {
  const { data, error, loading } = useApi<DriverAssignment[]>(`/trucks/${truckId}/assignments?v=${version}`)

  return (
    <section className="mt-3" aria-labelledby={`driver-history-${truckId}`}>
      <p id={`driver-history-${truckId}`} className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-ink">
        <History className="size-4 text-ink-muted" aria-hidden /> Driver history
      </p>
      {error ? (
        <p className="text-xs text-red-700">Could not load driver history: {error.message}</p>
      ) : !data || loading ? (
        <p className="text-xs text-ink-muted">Loading…</p>
      ) : data.length === 0 ? (
        <p className="text-xs text-ink-muted">No driver has been assigned to this truck.</p>
      ) : (
        <ol className="space-y-2" data-testid="driver-history">
          {data.slice(0, limit).map((a) => (
            <li key={a.id} className="rounded-lg border border-line px-3 py-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-ink">{a.driver.label}</span>
                {a.is_current && (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-semibold text-emerald-700">Current</span>
                )}
              </div>
              <p className="mt-0.5 text-ink-muted">
                {formatDateTime(a.assigned_at)} → {a.released_at ? formatDateTime(a.released_at) : 'present'}
              </p>
              {(a.assigned_by || a.released_by) && (
                <p className="text-ink-muted">
                  {a.assigned_by && <>Assigned by {a.assigned_by}</>}
                  {a.assigned_by && a.released_by && ' · '}
                  {a.released_by && <>Released by {a.released_by}</>}
                </p>
              )}
              {a.note && <p className="text-ink">“{a.note}”</p>}
              {SOURCE_NOTE[a.source] && <p className="italic text-ink-muted">{SOURCE_NOTE[a.source]}</p>}
            </li>
          ))}
          {data.length > limit && (
            <li className="text-xs text-ink-muted">+ {data.length - limit} earlier assignment(s)</li>
          )}
        </ol>
      )}
    </section>
  )
}
