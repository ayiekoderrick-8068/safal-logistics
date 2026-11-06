import clsx from 'clsx'
import { CalendarCheck, CalendarClock, CalendarPlus, CircleCheck, ClipboardCheck, Plus, Search, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { btnPrimary, btnSecondary, btnSmallGhost, btnSmallPrimary } from '../../../components/ui/buttons'
import { Card } from '../../../components/ui/Card'
import { PageHeader } from '../../../components/ui/PageHeader'
import { Pagination } from '../../../components/ui/Pagination'
import { StatCard } from '../../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { useToast } from '../../../components/ui/toastContext'
import { useApi } from '../../../hooks/useApi'
import { useDebounced } from '../../../hooks/useDebounced'
import { formatDate, formatNumber, formatPercent } from '../../../lib/format'
import {
  dueText,
  intervalText,
  notifyMaintenanceChanged,
  TASK_STATE_LABELS,
  useMaintenanceAccess,
  type MaintenancePlan,
  type MaintenanceTask,
  type PmSummary,
} from '../../../lib/maintenance'
import type { Page } from '../../../lib/types'
import { taskTone } from '../equipment/tones'
import {
  CancelTaskModal,
  CompleteTaskModal,
  PlanFormModal,
  RescheduleTaskModal,
  ResumePlanModal,
  ScheduleServiceModal,
  StopPlanModal,
} from './PmModals'

const PAGE_SIZE = 12
const VIEWS = [
  ['overdue', 'Overdue'],
  ['due_today', 'Due today'],
  ['upcoming', 'Upcoming'],
  ['open', 'All open'],
  ['completed', 'Completed'],
  ['cancelled', 'Cancelled'],
] as const
type View = (typeof VIEWS)[number][0]

type Dialog =
  | { kind: 'complete' | 'cancel' | 'reschedule'; task: MaintenanceTask }
  | { kind: 'plan'; plan?: MaintenancePlan }
  | { kind: 'stop' | 'resume'; plan: MaintenancePlan }
  | { kind: 'schedule' }
  | null

export function PreventivePage() {
  const toast = useToast()
  const { can } = useMaintenanceAccess()
  const canPlan = can('plans.manage')
  const canWork = can('work_orders.work')
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'plans' ? 'plans' : 'tasks'
  const view = (VIEWS.some(([v]) => v === params.get('view')) ? params.get('view') : 'open') as View
  const [mine, setMine] = useState(false)
  const [showInactive, setShowInactive] = useState(false)
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [version, setVersion] = useState(0)
  const q = useDebounced(query.trim())
  const reload = () => setVersion((v) => v + 1)
  const go = (next: Record<string, string>) => {
    setOffset(0)
    setParams({ tab, view, ...next }, { replace: true })
  }

  const summary = useApi<PmSummary>(`/maintenance/pm/summary?v=${version}`)
  const s = summary.data
  const listParams = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (q) listParams.set('q', q)
  // One request per tab: useApi keeps the last data while reloading, so sharing one hook would
  // briefly hand task rows to the plan cards (and vice versa) when switching tabs.
  const taskParams = new URLSearchParams(listParams)
  taskParams.set('view', view)
  if (mine) taskParams.set('mine', 'true')
  const planParams = new URLSearchParams(listParams)
  if (showInactive) planParams.set('active', 'false')
  const tasks = useApi<Page<MaintenanceTask>>(tab === 'tasks' ? `/maintenance/tasks?${taskParams}` : null)
  const plans = useApi<Page<MaintenancePlan>>(tab === 'plans' ? `/maintenance/plans?${planParams}` : null)
  const list = tab === 'tasks' ? tasks : plans
  const done = (message: string) => {
    setDialog(null)
    reload()
    notifyMaintenanceChanged()
    toast.success(message)
  }
  const compliance = s?.compliance

  return (
    <>
      <PageHeader
        title="Preventive Maintenance"
        description="Recurring service plans, the tasks they generate and how reliably they are done on time."
        actions={canPlan && (
          <>
            <button type="button" className={btnSecondary} onClick={() => setDialog({ kind: 'schedule' })}>
              <CalendarPlus className="size-4" aria-hidden /> Schedule service
            </button>
            <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'plan' })}>
              <Plus className="size-4" aria-hidden /> New plan
            </button>
          </>
        )}
      />

      {/* Two columns on phones so technicians reach their tasks without a long scroll. */}
      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-5">
        <StatCard compact icon={TriangleAlert} tone="red" label="Overdue" value={formatNumber(s?.overdue)} note="Past due, not completed" />
        <StatCard compact icon={CalendarClock} tone="amber" label="Due Today" value={formatNumber(s?.due_today)} />
        <StatCard compact icon={CalendarCheck} tone="blue" label="Next 7 Days" value={formatNumber(s?.due_next_7_days)}
          note={s ? `${s.open} open in total` : undefined} />
        <StatCard compact icon={CircleCheck} tone="green" label="On-time PM"
          value={compliance ? (compliance.pct == null ? '—' : formatPercent(compliance.pct)) : '…'}
          note={compliance ? (compliance.due === 0
            ? `No tasks fell due in the last ${compliance.window_days} days`
            : `${compliance.completed_on_time} of ${compliance.due} on time · last ${compliance.window_days} days`) : undefined} />
        <StatCard compact icon={ClipboardCheck} tone="teal" label="Active Plans" value={formatNumber(s?.active_plans)}
          note={s ? `${s.completed_last_30_days} completed in 30 days` : undefined} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2" role="tablist" aria-label="Preventive maintenance views">
        {(['tasks', 'plans'] as const).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => { setOffset(0); setParams({ tab: t, view }, { replace: true }) }}
            className={clsx('h-10 rounded-xl px-4 font-semibold', tab === t ? 'bg-primary text-white shadow' : 'bg-white text-ink hover:bg-surface-muted')}>
            {t === 'tasks' ? 'Tasks' : 'Plans'}
          </button>
        ))}
        <label className="relative ml-auto w-full sm:w-72">
          <span className="sr-only">Search {tab}</span>
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-ink-muted" aria-hidden />
          <input type="search" value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0) }}
            placeholder="Equipment ID, name or task…"
            className="h-10 w-full rounded-xl border border-white bg-white pr-3 pl-10 text-sm text-ink shadow-sm placeholder:text-ink-muted" />
        </label>
      </div>

      <Card className="mt-3">
        {tab === 'tasks' ? (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {VIEWS.map(([v, label]) => {
              const count = v === 'overdue' ? s?.overdue : v === 'due_today' ? s?.due_today : undefined
              return (
                <button key={v} type="button" onClick={() => go({ view: v })} aria-pressed={view === v}
                  className={clsx('inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold',
                    view === v ? 'border-primary bg-primary text-white' : 'border-line bg-white text-ink hover:bg-surface-muted')}>
                  {label}
                  {count ? <span className={clsx('rounded-full px-1.5 text-xs', view === v ? 'bg-white/25' : 'bg-red-100 text-red-700')}>{count}</span> : null}
                </button>
              )
            })}
            <label className="ml-auto inline-flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setOffset(0) }} className="size-4" />
              Assigned to me
            </label>
          </div>
        ) : (
          <div className="mb-4 flex justify-end">
            <label className="inline-flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={showInactive} onChange={(e) => { setShowInactive(e.target.checked); setOffset(0) }} className="size-4" />
              Show stopped plans
            </label>
          </div>
        )}

        {list.error && !list.data ? (
          <ErrorState message={list.error.message} onRetry={list.refetch} />
        ) : !list.data || list.loading && list.data.items.length === 0 ? (
          <LoadingState />
        ) : list.data.items.length === 0 ? (
          <EmptyState title={tab === 'plans'
            ? (showInactive ? 'No stopped plans' : 'No preventive plans yet')
            : view === 'overdue' ? 'Nothing is overdue' : 'No tasks in this view'}>
            {tab === 'plans' && canPlan && !showInactive && 'Use “New plan” to schedule recurring servicing for an asset.'}
          </EmptyState>
        ) : (
          <>
            <ul className="grid gap-3 lg:grid-cols-2">
              {tab === 'tasks'
                ? tasks.data?.items.map((t) => (
                  <TaskCard key={t.id} task={t} canPlan={canPlan} canWork={canWork} open={(kind) => setDialog({ kind, task: t })} />
                ))
                : plans.data?.items.map((p) => (
                  <PlanCard key={p.id} plan={p} canPlan={canPlan}
                    onEdit={() => setDialog({ kind: 'plan', plan: p })}
                    onToggle={() => setDialog({ kind: p.is_active ? 'stop' : 'resume', plan: p })} />
                ))}
            </ul>
            <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun={tab} onChange={setOffset} />
          </>
        )}
      </Card>

      {dialog?.kind === 'complete' && <CompleteTaskModal task={dialog.task} onClose={() => setDialog(null)}
        onDone={(t) => done(`${t.equipment.code}: ${t.title} completed`)} />}
      {dialog?.kind === 'cancel' && <CancelTaskModal task={dialog.task} onClose={() => setDialog(null)}
        onDone={(t) => done(`${t.equipment.code}: service cancelled`)} />}
      {dialog?.kind === 'reschedule' && <RescheduleTaskModal task={dialog.task} onClose={() => setDialog(null)}
        onDone={(t) => done(`${t.equipment.code}: due ${formatDate(t.due_on)}`)} />}
      {dialog?.kind === 'schedule' && <ScheduleServiceModal onClose={() => setDialog(null)}
        onDone={(t) => done(`Service scheduled for ${t.equipment.code}`)} />}
      {dialog?.kind === 'plan' && <PlanFormModal plan={dialog.plan} onClose={() => setDialog(null)}
        onDone={(p) => done(dialog.plan ? `Plan “${p.title}” saved` : `Plan created; first task due ${formatDate(p.next_task?.due_on ?? p.start_on)}`)} />}
      {dialog?.kind === 'stop' && <StopPlanModal plan={dialog.plan} onClose={() => setDialog(null)}
        onDone={(p) => done(`Plan “${p.title}” stopped`)} />}
      {dialog?.kind === 'resume' && <ResumePlanModal plan={dialog.plan} onClose={() => setDialog(null)}
        onDone={(p) => done(`Plan “${p.title}” resumed`)} />}
    </>
  )
}

function TaskCard({ task: t, canPlan, canWork, open }: {
  task: MaintenanceTask
  canPlan: boolean
  canWork: boolean
  open: (kind: 'complete' | 'cancel' | 'reschedule') => void
}) {
  const isOpen = t.status === 'scheduled'
  return (
    <li className={clsx('flex flex-col rounded-2xl border bg-white p-4',
      t.state === 'overdue' ? 'border-red-200' : t.state === 'due_today' ? 'border-amber-200' : 'border-line')}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-sm font-bold text-ink">{t.equipment.code}</p>
          <p className="text-sm text-ink-muted">{t.equipment.name}</p>
        </div>
        <StatusBadge status={t.state} label={TASK_STATE_LABELS[t.state]} tone={taskTone(t.state)} />
      </div>
      <p className="mt-2 font-semibold text-ink">{t.title}</p>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <dt className="text-ink-muted">Due</dt>
        <dd className="text-right">
          {formatDate(t.due_on)}
          {isOpen && <span className={clsx('block text-xs font-semibold', t.state === 'overdue' ? 'text-red-600' : t.state === 'due_today' ? 'text-amber-700' : 'text-ink-muted')}>{dueText(t)}</span>}
        </dd>
        <dt className="text-ink-muted">Technician</dt>
        <dd className="text-right">{t.assigned_technician?.full_name ?? <span className="text-ink-muted">Unassigned</span>}</dd>
        {t.status === 'completed' && (
          <>
            <dt className="text-ink-muted">Completed</dt>
            <dd className="text-right">
              {formatDate(t.completed_on!)}{' '}
              <span className={t.completed_on_time ? 'text-emerald-700' : 'font-semibold text-amber-700'}>
                ({t.completed_on_time ? 'on time' : 'late'})
              </span>
              {t.completed_by && <span className="block text-xs text-ink-muted">by {t.completed_by.full_name}</span>}
            </dd>
          </>
        )}
      </dl>
      {t.work_notes && <p className="mt-2 rounded-xl bg-surface-muted px-3 py-2 text-sm whitespace-pre-line text-ink">{t.work_notes}</p>}
      {t.cancel_reason && <p className="mt-2 text-sm text-ink-muted">Cancelled: {t.cancel_reason}</p>}
      {!t.plan_id && <p className="mt-1 text-xs text-ink-muted">Once-off service</p>}
      {isOpen && (canWork || canPlan) && (
        <div className="mt-auto flex flex-wrap gap-2 pt-3">
          {canWork && (
            <button type="button" className={`${btnSmallPrimary} h-10 px-4 text-sm`} onClick={() => open('complete')}>
              <CircleCheck className="size-4" aria-hidden /> Complete
            </button>
          )}
          {canPlan && (
            <>
              <button type="button" className={`${btnSmallGhost} h-10 px-3 text-sm`} onClick={() => open('reschedule')}>Reschedule</button>
              <button type="button" className={`${btnSmallGhost} h-10 px-3 text-sm`} onClick={() => open('cancel')}>Cancel</button>
            </>
          )}
        </div>
      )}
    </li>
  )
}

function PlanCard({ plan: p, canPlan, onEdit, onToggle }: {
  plan: MaintenancePlan
  canPlan: boolean
  onEdit: () => void
  onToggle: () => void
}) {
  const nxt = p.next_task
  return (
    <li className="flex flex-col rounded-2xl border border-line bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-sm font-bold text-ink">{p.equipment.code}</p>
          <p className="text-sm text-ink-muted">{p.equipment.name}</p>
        </div>
        {p.is_active
          ? nxt && <StatusBadge status={nxt.state} label={TASK_STATE_LABELS[nxt.state]} tone={taskTone(nxt.state)} />
          : <StatusBadge status="stopped" label="Stopped" tone="slate" />}
      </div>
      <p className="mt-2 font-semibold text-ink">{p.title}</p>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <dt className="text-ink-muted">Schedule</dt>
        <dd className="text-right">
          {intervalText(p.interval_value, p.interval_unit)}
          <span className="block text-xs text-ink-muted">from the {p.schedule_basis === 'due_date' ? 'due date' : 'completion date'}</span>
        </dd>
        <dt className="text-ink-muted">Next due</dt>
        <dd className="text-right">{nxt ? <>{formatDate(nxt.due_on)}<span className="block text-xs text-ink-muted">{dueText(nxt)}</span></> : '—'}</dd>
        <dt className="text-ink-muted">Last done</dt>
        <dd className="text-right">{p.last_completed_on ? formatDate(p.last_completed_on) : <span className="text-ink-muted">Not yet</span>}</dd>
        <dt className="text-ink-muted">Technician</dt>
        <dd className="text-right">{p.assigned_technician?.full_name ?? <span className="text-ink-muted">Unassigned</span>}</dd>
      </dl>
      {canPlan && (
        <div className="mt-auto flex gap-2 pt-3">
          {p.is_active && <button type="button" className={`${btnSmallGhost} h-10 px-3 text-sm`} onClick={onEdit}>Edit</button>}
          <button type="button" className={`${btnSmallGhost} h-10 px-3 text-sm`} onClick={onToggle}>{p.is_active ? 'Stop plan' : 'Resume plan'}</button>
        </div>
      )}
    </li>
  )
}
