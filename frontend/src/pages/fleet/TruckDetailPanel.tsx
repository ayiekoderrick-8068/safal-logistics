import { CalendarClock, Gauge, Pencil, Route as RouteIcon, ShieldCheck, Timer, Truck, User, Warehouse } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { useAuth } from '../../auth/context'
import { btnPrimary, btnSecondary } from '../../components/ui/buttons'
import { DriverHistory } from './DriverHistory'
import { AlertList } from '../../components/alerts/AlertList'
import { Card } from '../../components/ui/Card'
import { ErrorState, LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useApi } from '../../hooks/useApi'
import { formatDate, formatDuration, humanize } from '../../lib/format'
import type { TruckDetail } from '../../lib/types'

function Row({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 border-b border-line py-2.5 text-sm last:border-0">
      <span className="text-ink-muted" aria-hidden>{icon}</span>
      <span className="text-ink-muted">{label}</span>
      <span className="ml-auto text-right font-medium text-ink">{children}</span>
    </div>
  )
}

export function TruckDetailPanel({
  truckId,
  version,
  canEdit,
  canSchedule,
  onEdit,
}: {
  truckId: number
  version: number
  canEdit: boolean
  canSchedule: boolean
  onEdit: (t: TruckDetail) => void
}) {
  const { data, error, loading, refetch } = useApi<TruckDetail>(`/trucks/${truckId}?v=${version}`)
  const navigate = useNavigate()
  const canViewHistory = useAuth().hasRole('operations', 'fleet_manager', 'compliance')

  if (error && !data) return <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
  if (!data || (loading && data.id !== truckId)) return <Card><LoadingState /></Card>

  const t = data
  const complianceLabel = { valid: 'Valid', expiring: 'Expiring soon', overdue: 'Overdue', missing: 'No documents' }[t.compliance.status]
  return (
    <Card className="flex flex-col">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-xl font-bold text-ink">{t.registration}</h2>
        <StatusBadge status={t.status} />
      </div>
      <div className="relative mb-3 flex h-36 items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br from-sky-100 via-cyan-50 to-emerald-50">
        <Truck className="size-24 text-primary/80" strokeWidth={1.3} aria-hidden />
        <span className="absolute bottom-2 left-3 rounded-md bg-white/80 px-2 py-0.5 text-xs font-semibold text-ink">
          {[t.make, t.model].filter(Boolean).join(' ') || 'Make not recorded'}
        </span>
      </div>
      <div>
        <Row icon={<User className="size-4" />} label="Driver">{t.driver?.label ?? 'Unassigned'}</Row>
        <Row icon={<RouteIcon className="size-4" />} label="Route (last)">{t.last_route ?? '—'}</Row>
        <Row icon={<Gauge className="size-4" />} label="Capacity">{t.capacity_tonnes} t</Row>
        <Row icon={<Warehouse className="size-4" />} label="Loads (30 days)">{t.loads_completed_30d}</Row>
        <Row icon={<Timer className="size-4" />} label="Avg turnaround (30 days)">{formatDuration(t.avg_turnaround_30d)}</Row>
        <Row icon={<CalendarClock className="size-4" />} label="Next expiry">
          {t.compliance.next_expiry
            ? `${formatDate(t.compliance.next_expiry)} · ${humanize(t.compliance.next_expiry_type ?? '')}`
            : '—'}
        </Row>
        <Row icon={<ShieldCheck className="size-4" />} label="Compliance">
          <StatusBadge status={t.compliance.status} label={complianceLabel} />
        </Row>
      </div>
      {!t.compliance.eligible && (
        <div role="note" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          <p className="font-semibold">Blocked from dispatch</p>
          <ul className="mt-0.5 list-disc pl-4">{t.compliance.issues.map((i) => <li key={i}>{i}</li>)}</ul>
        </div>
      )}
      {canViewHistory && <DriverHistory truckId={t.id} version={version} />}
      <div className="mt-3">
        <p className="mb-2 text-sm font-semibold text-ink">Active alerts</p>
        <AlertList query={`truck_id=${t.id}`} limit={3} compact emptyTitle="No alerts for this truck" version={version} />
      </div>
      <Link to={`/compliance?truck=${t.id}`} className="mt-3 text-sm font-semibold text-primary hover:underline">
        View compliance documents →
      </Link>
      {(canEdit || canSchedule) && (
        <div className="mt-4 grid gap-3">
          {canSchedule && (
            <button type="button" className={`${btnPrimary} px-3`} disabled={t.status !== 'available'}
              title={t.status !== 'available' ? 'Only available trucks can be scheduled' : undefined}
              onClick={() => navigate(`/loading-bays?truck=${t.id}`)}>
              <Warehouse className="size-4" aria-hidden /> Schedule Loading
            </button>
          )}
          {canEdit && (
            <button type="button" className={`${btnSecondary} border-line px-3`} onClick={() => onEdit(t)}>
              <Pencil className="size-4" aria-hidden /> Edit Truck
            </button>
          )}
        </div>
      )}
    </Card>
  )
}
