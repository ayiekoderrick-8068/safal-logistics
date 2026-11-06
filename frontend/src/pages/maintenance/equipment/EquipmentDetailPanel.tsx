import { Archive, ArchiveRestore, History, Pencil } from 'lucide-react'
import { btnSmallGhost } from '../../../components/ui/buttons'
import { Card, CardHeader } from '../../../components/ui/Card'
import { ErrorState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { useApi } from '../../../hooks/useApi'
import { formatDate, formatDateTime } from '../../../lib/format'
import {
  CATEGORY_LABELS,
  EQUIPMENT_STATUS_LABELS,
  SERVICE_STATE_LABELS,
  serviceText,
  type EquipmentDetail,
} from '../../../lib/maintenance'
import { equipmentTone, serviceTone } from './tones'

export function EquipmentDetailPanel({
  equipmentId,
  version,
  canManage,
  onEdit,
  onArchive,
  onRestore,
}: {
  equipmentId: number
  version: number
  canManage: boolean
  onEdit: (e: EquipmentDetail) => void
  onArchive: (e: EquipmentDetail) => void
  onRestore: (e: EquipmentDetail) => void
}) {
  const { data: e, error, refetch } = useApi<EquipmentDetail>(`/maintenance/equipment/${equipmentId}?v=${version}`)

  if (error && !e) return <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
  if (!e) return <Card><LoadingState /></Card>

  const rows: [string, string | null][] = [
    ['Category', CATEGORY_LABELS[e.category]],
    ['Manufacturer', e.manufacturer],
    ['Model', e.model],
    ['Serial number', e.serial_number],
    ['Facility', e.facility],
    ['Department', e.department],
    ['Location', e.location],
    ['Installed', e.installed_on ? formatDate(e.installed_on) : null],
    ['Technician', e.assigned_technician?.full_name ?? null],
    ['Last service', e.last_service_on ? formatDate(e.last_service_on) : null],
    ['Next service', e.next_service_on ? formatDate(e.next_service_on) : null],
  ]

  return (
    <Card className="self-start">
      <CardHeader
        title={<span className="font-mono">{e.code}</span>}
        subtitle={e.name}
        action={
          e.archived_at
            ? <StatusBadge status="archived" label="Archived" tone="slate" />
            : <StatusBadge status={e.status} label={EQUIPMENT_STATUS_LABELS[e.status]} tone={equipmentTone(e.status)} />
        }
      />
      {!e.archived_at && (
        <div className="mb-4 flex items-center justify-between rounded-xl bg-surface-muted px-3 py-2.5 text-sm">
          <span className="text-ink-muted">Service</span>
          <span className="flex items-center gap-2">
            <span className="font-semibold text-ink">{serviceText(e)}</span>
            <StatusBadge status={e.service_state} label={SERVICE_STATE_LABELS[e.service_state]} tone={serviceTone(e.service_state)} />
          </span>
        </div>
      )}

      <dl className="divide-y divide-line text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 py-2">
            <dt className="text-ink-muted">{k}</dt>
            <dd className="text-right font-medium text-ink">{v ?? <span className="font-normal text-ink-muted">—</span>}</dd>
          </div>
        ))}
      </dl>
      {e.notes && <p className="mt-3 rounded-xl bg-surface-muted px-3 py-2.5 text-sm whitespace-pre-line text-ink">{e.notes}</p>}

      {canManage && (
        <div className="mt-4 flex flex-wrap gap-2">
          {e.archived_at ? (
            <button type="button" className={btnSmallGhost} onClick={() => onRestore(e)}>
              <ArchiveRestore className="size-3.5" aria-hidden /> Restore
            </button>
          ) : (
            <>
              <button type="button" className={btnSmallGhost} onClick={() => onEdit(e)}>
                <Pencil className="size-3.5" aria-hidden /> Edit
              </button>
              <button type="button" className={btnSmallGhost} onClick={() => onArchive(e)}>
                <Archive className="size-3.5" aria-hidden /> Archive
              </button>
            </>
          )}
        </div>
      )}

      <h3 className="mt-6 mb-2 flex items-center gap-2 text-sm font-bold text-ink">
        <History className="size-4 text-primary" aria-hidden /> Maintenance history
      </h3>
      <ol className="space-y-3 border-l-2 border-line pl-4" aria-label="Maintenance history">
        {e.history.map((h) => (
          <li key={h.id} className="relative text-sm">
            <span className="absolute top-1.5 -left-[1.4rem] size-2.5 rounded-full border-2 border-white bg-accent" aria-hidden />
            <p className="font-medium text-ink">{h.summary}</p>
            <p className="text-xs text-ink-muted">
              {formatDateTime(h.occurred_at)}{h.actor && ` · ${h.actor.full_name}`}
            </p>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs text-ink-muted">
        Servicing, work orders and breakdowns will appear here as those modules are introduced.
      </p>
    </Card>
  )
}
