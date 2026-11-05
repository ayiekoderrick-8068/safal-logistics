import clsx from 'clsx'
import { ChevronRight, CircleAlert, Info, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import { useApi } from '../../hooks/useApi'
import type { AlertSeverity, OpsAlert, Page } from '../../lib/types'
import { EmptyState, ErrorState, LoadingState } from '../ui/States'

const STYLE: Record<AlertSeverity, { box: string; icon: typeof Info; iconClass: string; label: string }> = {
  critical: { box: 'border-red-100 bg-red-50', icon: CircleAlert, iconClass: 'text-red-600', label: 'Critical' },
  warning: { box: 'border-amber-100 bg-amber-50', icon: TriangleAlert, iconClass: 'text-amber-600', label: 'Warning' },
  info: { box: 'border-sky-100 bg-sky-50', icon: Info, iconClass: 'text-sky-600', label: 'Info' },
}

export function AlertItem({ alert, compact = false }: { alert: OpsAlert; compact?: boolean }) {
  const s = STYLE[alert.severity]
  return (
    <li>
      <Link to={alert.link}
        className={clsx('flex items-start gap-3 rounded-xl border p-3 text-sm transition-colors hover:brightness-[0.98]', s.box)}>
        <s.icon className={clsx('mt-0.5 size-5 shrink-0', s.iconClass)} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-ink">
            <span className="sr-only">{s.label}: </span>{alert.title}
          </span>
          {!compact && <span className="block text-xs text-ink-muted">{alert.message}</span>}
          {alert.status === 'acknowledged' && (
            <span className="block text-xs font-semibold text-sky-700">Acknowledged{alert.acknowledged_by ? ` by ${alert.acknowledged_by}` : ''}</span>
          )}
        </span>
        <ChevronRight className="mt-0.5 size-4 shrink-0 text-ink-muted" aria-hidden />
      </Link>
    </li>
  )
}

/** Active operational alerts matching `query` (e.g. "types=delivery_overdue&limit=4"). */
export function AlertList({ query = '', limit = 5, emptyTitle = 'No active alerts', compact, version = 0 }: {
  query?: string
  limit?: number
  emptyTitle?: string
  compact?: boolean
  version?: number
}) {
  const { data, error, refetch } = useApi<Page<OpsAlert>>(`/alerts?status=active&limit=${limit}${query ? `&${query}` : ''}&v=${version}`)
  if (error && !data) return <ErrorState message={error.message} onRetry={refetch} />
  if (!data) return <LoadingState />
  if (data.items.length === 0) return <EmptyState title={emptyTitle} />
  return (
    <>
      <ul className="space-y-2.5" aria-label="Active alerts">
        {data.items.map((a) => <AlertItem key={a.id} alert={a} compact={compact} />)}
      </ul>
      {data.total > data.items.length && (
        <Link to="/alerts" className="mt-3 inline-block text-sm font-semibold text-primary hover:underline">
          View all {data.total} alerts →
        </Link>
      )}
    </>
  )
}
