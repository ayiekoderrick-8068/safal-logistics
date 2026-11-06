import clsx from 'clsx'
import { CircleCheck, ClipboardList, Hourglass, PackageSearch, Pause, Pencil, Play, Plus, Search, TriangleAlert, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useAuth } from '../../../auth/context'
import { btnPrimary, btnSmallGhost, btnSmallPrimary } from '../../../components/ui/buttons'
import { Card, CardHeader } from '../../../components/ui/Card'
import { FormError } from '../../../components/ui/Form'
import { PageHeader } from '../../../components/ui/PageHeader'
import { Pagination } from '../../../components/ui/Pagination'
import { StatCard } from '../../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { useToast } from '../../../components/ui/toastContext'
import { useApi } from '../../../hooks/useApi'
import { useDebounced } from '../../../hooks/useDebounced'
import { ApiError } from '../../../lib/api'
import { formatDate, formatDateTime, formatDuration, formatNumber } from '../../../lib/format'
import {
  notifyMaintenanceChanged,
  PRIORITY_LABELS,
  send,
  useMaintenanceAccess,
  WO_STATUS_LABELS,
  WO_TYPE_LABELS,
  type WorkOrder,
  type WorkOrderDetail,
  type WorkOrderStatus,
  type WorkOrderSummary,
} from '../../../lib/maintenance'
import type { Page } from '../../../lib/types'
import { priorityTone, woTone } from '../equipment/tones'
import { CancelWorkOrderModal, CompleteWorkOrderModal, EditWorkOrderModal, NewWorkOrderModal } from './WorkModals'

const PAGE_SIZE = 10
const VIEWS: [string, string, Record<string, string>][] = [
  ['active', 'Active', { active: 'true' }],
  ['open', 'Open', { status: 'open' }],
  ['assigned', 'Assigned', { status: 'assigned' }],
  ['in_progress', 'In progress', { status: 'in_progress' }],
  ['awaiting_parts', 'Awaiting parts', { status: 'awaiting_parts' }],
  ['overdue', 'Overdue', { overdue: 'true' }],
  ['completed', 'Completed', { status: 'completed' }],
  ['cancelled', 'Cancelled', { status: 'cancelled' }],
  ['all', 'All', {}],
]

type Dialog = { kind: 'new' } | { kind: 'edit' | 'complete' | 'cancel'; wo: WorkOrder } | null

export function WorkOrdersPage() {
  const toast = useToast()
  const { user } = useAuth()
  const { can } = useMaintenanceAccess()
  const canCreate = can('work_orders.create')
  const canAssign = can('work_orders.assign')
  const canWork = can('work_orders.work')
  const [params, setParams] = useSearchParams()
  const view = VIEWS.find(([v]) => v === params.get('view')) ?? VIEWS[0]
  const [mine, setMine] = useState(false)
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number | null>(Number(params.get('wo')) || null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [version, setVersion] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)
  const detailRef = useRef<HTMLDivElement>(null)
  const q = useDebounced(query.trim())

  const search = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version), ...view[2] })
  if (q) search.set('q', q)
  if (mine) search.set('mine', 'true')
  const list = useApi<Page<WorkOrder>>(`/maintenance/work-orders?${search}`)
  const summary = useApi<WorkOrderSummary>(`/maintenance/work-orders/summary?v=${version}`)
  const s = summary.data
  const items = list.data?.items ?? []
  const selectedId = selected && items.some((w) => w.id === selected) ? selected : (items[0]?.id ?? null)

  const refresh = (message?: string) => {
    setDialog(null)
    setVersion((v) => v + 1)
    notifyMaintenanceChanged()
    if (message) toast.success(message)
  }
  function select(id: number) {
    setSelected(id)
    if (window.matchMedia?.('(max-width: 1279px)').matches) {
      requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    }
  }
  async function move(wo: WorkOrder, to: WorkOrderStatus, label: string) {
    setActionError(null)
    try {
      await send(`/maintenance/work-orders/${wo.id}/transition`, { to })
      refresh(`${wo.number}: ${label}`)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not update the work order.')
    }
  }

  return (
    <>
      <PageHeader
        title="Work Orders"
        description="Plan, assign and complete maintenance work, with a full status history."
        actions={canCreate && (
          <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'new' })}>
            <Plus className="size-4" aria-hidden /> New work order
          </button>
        )}
      />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-5">
        <StatCard icon={ClipboardList} tone="amber" label="Open" value={formatNumber(s?.open)}
          note={s ? `${s.assigned} assigned` : undefined} />
        <StatCard icon={Play} tone="blue" label="In Progress" value={formatNumber(s?.in_progress)} />
        <StatCard icon={PackageSearch} tone="amber" label="Awaiting Parts" value={formatNumber(s?.awaiting_parts)} />
        <StatCard icon={TriangleAlert} tone="red" label="Overdue" value={formatNumber(s?.overdue)}
          note={s ? `${s.critical_open} critical open` : undefined} />
        <StatCard icon={CircleCheck} tone="green" label="Completed" value={formatNumber(s?.completed_last_30_days)} note="Last 30 days" />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {VIEWS.map(([v, label]) => (
          <button key={v} type="button" aria-pressed={view[0] === v}
            onClick={() => { setOffset(0); setParams({ view: v }, { replace: true }) }}
            className={clsx('h-9 rounded-full border px-3.5 text-sm font-semibold',
              view[0] === v ? 'border-primary bg-primary text-white' : 'border-white bg-white text-ink hover:bg-surface-muted')}>
            {label}
          </button>
        ))}
        <label className="inline-flex items-center gap-2 px-2 text-sm text-ink">
          <input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setOffset(0) }} className="size-4" />
          Assigned to me
        </label>
        <label className="relative w-full lg:ml-auto lg:w-72">
          <span className="sr-only">Search work orders</span>
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-ink-muted" aria-hidden />
          <input type="search" value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0) }}
            placeholder="WO number, equipment or fault…"
            className="h-10 w-full rounded-xl border border-white bg-white pr-3 pl-10 text-sm text-ink shadow-sm placeholder:text-ink-muted" />
        </label>
      </div>

      {actionError && <div className="mt-4"><FormError message={actionError} /></div>}

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <Card>
          <CardHeader title={view[1] === 'All' ? 'All work orders' : `${view[1]} work orders`}
            subtitle={list.data ? `${formatNumber(list.data.total)} found` : undefined} />
          {list.error && !list.data ? (
            <ErrorState message={list.error.message} onRetry={list.refetch} />
          ) : !list.data ? (
            <LoadingState />
          ) : items.length === 0 ? (
            <EmptyState title="No work orders in this view">
              {canCreate && view[0] === 'active' && !q && 'Use “New work order”, or log a breakdown to raise a repair.'}
            </EmptyState>
          ) : (
            <>
              <ul className="space-y-2">
                {items.map((w) => (
                  <li key={w.id}>
                    <button type="button" onClick={() => select(w.id)} aria-pressed={w.id === selectedId}
                      className={clsx('w-full rounded-xl border p-3 text-left transition',
                        w.id === selectedId ? 'border-accent bg-sky-50/70' : 'border-line bg-white hover:bg-surface-muted')}>
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-bold text-ink">{w.number}</span>
                        <StatusBadge status={w.status} label={WO_STATUS_LABELS[w.status]} tone={woTone(w.status)} />
                        <StatusBadge status={w.priority} label={PRIORITY_LABELS[w.priority]} tone={priorityTone(w.priority)} />
                        {w.overdue && <StatusBadge status="overdue" label="Overdue" tone="red" />}
                      </span>
                      <span className="mt-1 block truncate text-sm text-ink">{w.fault_description}</span>
                      <span className="mt-1 flex flex-wrap justify-between gap-x-3 text-xs text-ink-muted">
                        <span>{w.equipment.code} · {w.equipment.name}</span>
                        <span>{w.assigned_technician?.full_name ?? 'Unassigned'}{w.scheduled_on ? ` · due ${formatDate(w.scheduled_on)}` : ''}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun="work orders" onChange={setOffset} />
            </>
          )}
        </Card>

        <div ref={detailRef} className="scroll-mt-20">
          {selectedId != null && (
            <WorkOrderPanel id={selectedId} version={version} selfId={user?.id ?? 0}
              canAssign={canAssign} canWork={canWork}
              onMove={move} onOpen={(kind, wo) => setDialog({ kind, wo })} />
          )}
        </div>
      </div>

      {dialog?.kind === 'new' && <NewWorkOrderModal canAssign={canAssign} selfId={user?.id ?? 0} onClose={() => setDialog(null)}
        onDone={(w) => { setSelected(w.id); refresh(`${w.number} raised`) }} />}
      {dialog?.kind === 'edit' && <EditWorkOrderModal wo={dialog.wo} onClose={() => setDialog(null)}
        onDone={(w) => refresh(`${w.number} updated`)} />}
      {dialog?.kind === 'complete' && <CompleteWorkOrderModal wo={dialog.wo} onClose={() => setDialog(null)}
        onDone={(w) => refresh(`${w.number} completed`)} />}
      {dialog?.kind === 'cancel' && <CancelWorkOrderModal wo={dialog.wo} onClose={() => setDialog(null)}
        onDone={(w) => refresh(`${w.number} cancelled`)} />}
    </>
  )
}

function WorkOrderPanel({ id, version, selfId, canAssign, canWork, onMove, onOpen }: {
  id: number
  version: number
  selfId: number
  canAssign: boolean
  canWork: boolean
  onMove: (wo: WorkOrder, to: WorkOrderStatus, label: string) => void
  onOpen: (kind: 'edit' | 'complete' | 'cancel', wo: WorkOrder) => void
}) {
  const { data: wo, error, refetch } = useApi<WorkOrderDetail>(`/maintenance/work-orders/${id}?v=${version}`)
  if (error && !wo) return <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
  if (!wo) return <Card><LoadingState /></Card>

  const mine = wo.assigned_technician?.id === selfId
  const canProgress = canWork && (mine || canAssign)
  const can = (s: WorkOrderStatus) => wo.allowed_transitions.includes(s)
  const closed = wo.status === 'completed' || wo.status === 'cancelled'
  const big = 'h-10 px-4 text-sm'
  const rows: [string, string | null][] = [
    ['Equipment', `${wo.equipment.code} · ${wo.equipment.name}`],
    ['Type', WO_TYPE_LABELS[wo.maintenance_type]],
    ['Technician', wo.assigned_technician?.full_name ?? 'Unassigned'],
    ['Scheduled', wo.scheduled_on ? formatDate(wo.scheduled_on) : null],
    ['Raised', `${formatDateTime(wo.created_at)}${wo.created_by ? ` · ${wo.created_by.full_name}` : ''}`],
    ['Started', wo.started_at ? formatDateTime(wo.started_at) : null],
    ['Completed', wo.completed_at ? formatDateTime(wo.completed_at) : null],
    ['Repair duration', wo.repair_minutes != null ? formatDuration(wo.repair_minutes) : null],
  ]
  return (
    <Card className="self-start">
      <CardHeader title={<span className="font-mono">{wo.number}</span>} subtitle={wo.fault_description}
        action={<span className="flex gap-1.5">
          <StatusBadge status={wo.status} label={WO_STATUS_LABELS[wo.status]} tone={woTone(wo.status)} />
          <StatusBadge status={wo.priority} label={PRIORITY_LABELS[wo.priority]} tone={priorityTone(wo.priority)} />
        </span>} />

      {!closed && (
        <div className="mb-4 flex flex-wrap gap-2">
          {canProgress && can('in_progress') && (
            <button type="button" className={`${btnSmallPrimary} ${big}`} onClick={() => onMove(wo, 'in_progress', wo.status === 'awaiting_parts' ? 'work resumed' : 'work started')}>
              <Play className="size-4" aria-hidden /> {wo.status === 'awaiting_parts' ? 'Resume' : 'Start work'}
            </button>
          )}
          {canProgress && can('completed') && (
            <button type="button" className={`${btnSmallPrimary} ${big}`} onClick={() => onOpen('complete', wo)}>
              <CircleCheck className="size-4" aria-hidden /> Complete
            </button>
          )}
          {canProgress && can('awaiting_parts') && (
            <button type="button" className={`${btnSmallGhost} ${big}`} onClick={() => onMove(wo, 'awaiting_parts', 'waiting for parts')}>
              <Pause className="size-4" aria-hidden /> Awaiting parts
            </button>
          )}
          {canAssign && (
            <button type="button" className={`${btnSmallGhost} ${big}`} onClick={() => onOpen('edit', wo)}>
              <Pencil className="size-4" aria-hidden /> {wo.assigned_technician ? 'Edit' : 'Assign'}
            </button>
          )}
          {canAssign && can('cancelled') && (
            <button type="button" className={`${btnSmallGhost} ${big}`} onClick={() => onOpen('cancel', wo)}>
              <X className="size-4" aria-hidden /> Cancel
            </button>
          )}
          {!canProgress && canWork && wo.assigned_technician && (
            <p className="text-sm text-ink-muted">Assigned to {wo.assigned_technician.full_name}.</p>
          )}
        </div>
      )}

      {wo.breakdown && (
        <Link to={`/maintenance/breakdowns?bd=${wo.breakdown.id}`}
          className={clsx('mb-4 flex items-center justify-between rounded-xl px-3 py-2.5 text-sm',
            wo.breakdown.is_open ? 'bg-red-50 text-red-800' : 'bg-surface-muted text-ink')}>
          <span>Breakdown <span className="font-mono font-semibold">{wo.breakdown.number}</span></span>
          <span className="font-semibold">{wo.breakdown.is_open ? 'Equipment down' : 'Restored'}</span>
        </Link>
      )}

      <dl className="divide-y divide-line text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 py-2">
            <dt className="shrink-0 text-ink-muted">{k}</dt>
            <dd className="text-right font-medium text-ink">{v ?? <span className="font-normal text-ink-muted">—</span>}</dd>
          </div>
        ))}
      </dl>
      {wo.work_performed && (
        <div className="mt-3 rounded-xl bg-emerald-50 px-3 py-2.5 text-sm">
          <p className="font-semibold text-emerald-900">Work performed</p>
          <p className="mt-0.5 whitespace-pre-line text-ink">{wo.work_performed}</p>
          {wo.completion_notes && <p className="mt-2 whitespace-pre-line text-ink-muted">{wo.completion_notes}</p>}
        </div>
      )}
      {wo.cancel_reason && <p className="mt-3 rounded-xl bg-surface-muted px-3 py-2.5 text-sm text-ink">Cancelled: {wo.cancel_reason}</p>}
      <p className="mt-3 text-xs text-ink-muted">Parts consumed are recorded against work orders once spare-parts inventory is introduced.</p>

      <h3 className="mt-5 mb-2 flex items-center gap-2 text-sm font-bold text-ink">
        <Hourglass className="size-4 text-primary" aria-hidden /> Status history
      </h3>
      <ol className="space-y-3 border-l-2 border-line pl-4" aria-label="Status history">
        {wo.history.map((h) => (
          <li key={h.id} className="relative text-sm">
            <span className="absolute top-1.5 -left-[1.4rem] size-2.5 rounded-full border-2 border-white bg-accent" aria-hidden />
            <p className="font-medium text-ink">{h.summary}</p>
            {h.note && h.note !== h.summary && <p className="text-ink-muted">{h.note}</p>}
            <p className="text-xs text-ink-muted">{formatDateTime(h.occurred_at)}{h.actor && ` · ${h.actor.full_name}`}</p>
          </li>
        ))}
      </ol>
    </Card>
  )
}
