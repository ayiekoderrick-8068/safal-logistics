import clsx from 'clsx'
import { Clock, Pencil, Plus, Repeat, Search, ShieldCheck, TriangleAlert, Wrench } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { btnPrimary, btnSmallGhost, btnSmallPrimary } from '../../../components/ui/buttons'
import { Card, CardHeader } from '../../../components/ui/Card'
import { PageHeader } from '../../../components/ui/PageHeader'
import { Pagination } from '../../../components/ui/Pagination'
import { StatCard } from '../../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { useToast } from '../../../components/ui/toastContext'
import { useApi } from '../../../hooks/useApi'
import { useDebounced } from '../../../hooks/useDebounced'
import { formatDateTime, formatDuration, formatNumber } from '../../../lib/format'
import {
  FAULT_LABELS,
  notifyMaintenanceChanged,
  SEVERITY_LABELS,
  useMaintenanceAccess,
  WO_STATUS_LABELS,
  type Breakdown,
  type BreakdownSummary,
} from '../../../lib/maintenance'
import type { Page } from '../../../lib/types'
import { priorityTone } from '../equipment/tones'
import { EditBreakdownModal, LogBreakdownModal, RestoreBreakdownModal } from './WorkModals'

const PAGE_SIZE = 10
const VIEWS = [['open', 'Open'], ['restored', 'Restored'], ['all', 'All']] as const
type Dialog = { kind: 'log' } | { kind: 'restore' | 'edit'; bd: Breakdown } | null

export function BreakdownsPage() {
  const toast = useToast()
  const { can } = useMaintenanceAccess()
  const canLog = can('breakdowns.log')
  const [params, setParams] = useSearchParams()
  const view = (VIEWS.find(([v]) => v === params.get('view'))?.[0] ?? (params.get('bd') ? 'all' : 'open'))
  const highlight = Number(params.get('bd')) || null
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [version, setVersion] = useState(0)
  const q = useDebounced(query.trim())

  const search = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (view !== 'all') search.set('open', String(view === 'open'))
  if (q) search.set('q', q)
  const list = useApi<Page<Breakdown>>(`/maintenance/breakdowns?${search}`)
  const summary = useApi<BreakdownSummary>(`/maintenance/breakdowns/summary?v=${version}`)
  const s = summary.data
  const done = (message: string) => {
    setDialog(null)
    setVersion((v) => v + 1)
    notifyMaintenanceChanged()
    toast.success(message)
  }

  return (
    <>
      <PageHeader
        title="Breakdown Logs"
        description="Equipment failures from the moment they happen to restoration, with downtime and recurring faults."
        actions={canLog && (
          <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'log' })}>
            <Plus className="size-4" aria-hidden /> Log breakdown
          </button>
        )}
      />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <StatCard icon={TriangleAlert} tone="red" label="Open Breakdowns" value={formatNumber(s?.open)} note="Not yet restored" />
        <StatCard icon={Wrench} tone="amber" label="Breakdowns" value={formatNumber(s?.breakdowns)}
          note={s ? `Last ${s.window_days} days` : undefined} />
        <StatCard icon={Clock} tone="blue" label="Downtime" value={s ? formatDuration(s.downtime_minutes) : '…'}
          note={s ? `Last ${s.window_days} days, stopped equipment only` : undefined} />
        <StatCard icon={Repeat} tone="teal" label="Repeat Failures" value={formatNumber(s?.repeat_equipment)}
          note="Assets with 2+ breakdowns" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Most frequently failing equipment" subtitle={s ? `Last ${s.window_days} days` : undefined} />
          {!s ? <LoadingState /> : s.top_equipment.length === 0 ? (
            <EmptyState title="No breakdowns recorded in this period" />
          ) : (
            <ol className="space-y-2">
              {s.top_equipment.map((e, i) => (
                <li key={e.equipment.id} className="flex items-center gap-3 text-sm">
                  <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-surface-muted font-bold text-ink">{i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="font-mono font-semibold text-ink">{e.equipment.code}</span>
                    <span className="block truncate text-ink-muted">{e.equipment.name}</span>
                  </span>
                  <span className="text-right">
                    <span className="font-semibold text-ink">{e.breakdowns} breakdown{e.breakdowns === 1 ? '' : 's'}</span>
                    <span className="block text-xs text-ink-muted">{formatDuration(e.downtime_minutes)} down</span>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Card>
        <Card>
          <CardHeader title="Common fault categories" subtitle={s ? `Last ${s.window_days} days` : undefined} />
          {!s ? <LoadingState /> : s.categories.length === 0 ? (
            <EmptyState title="No breakdowns recorded in this period" />
          ) : (
            <ul className="space-y-2.5">
              {s.categories.map((c) => {
                const share = s.breakdowns ? Math.round((c.breakdowns / s.breakdowns) * 100) : 0
                return (
                  <li key={c.category} className="text-sm">
                    <span className="flex justify-between">
                      <span className="font-medium text-ink">{FAULT_LABELS[c.category]}</span>
                      <span className="text-ink-muted">{c.breakdowns} · {formatDuration(c.downtime_minutes)}</span>
                    </span>
                    <span className="mt-1 block h-2 rounded-full bg-surface-muted" aria-hidden>
                      <span className="block h-2 rounded-full bg-accent" style={{ width: `${share}%` }} />
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mt-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {VIEWS.map(([v, label]) => (
            <button key={v} type="button" aria-pressed={view === v}
              onClick={() => { setOffset(0); setParams({ view: v }, { replace: true }) }}
              className={clsx('h-9 rounded-full border px-3.5 text-sm font-semibold',
                view === v ? 'border-primary bg-primary text-white' : 'border-line bg-white text-ink hover:bg-surface-muted')}>
              {label}
            </button>
          ))}
          <label className="relative w-full sm:ml-auto sm:w-72">
            <span className="sr-only">Search breakdowns</span>
            <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-ink-muted" aria-hidden />
            <input type="search" value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0) }}
              placeholder="BD number, equipment or fault…"
              className="h-10 w-full rounded-xl border border-line bg-white pr-3 pl-10 text-sm text-ink placeholder:text-ink-muted" />
          </label>
        </div>
        {list.error && !list.data ? (
          <ErrorState message={list.error.message} onRetry={list.refetch} />
        ) : !list.data ? (
          <LoadingState />
        ) : list.data.items.length === 0 ? (
          <EmptyState title={view === 'open' ? 'No open breakdowns' : 'No breakdowns in this view'}>
            {view === 'open' && 'All recorded failures have been restored.'}
          </EmptyState>
        ) : (
          <>
            <ul className="grid gap-3 lg:grid-cols-2">
              {list.data.items.map((b) => (
                <li key={b.id} className={clsx('flex flex-col rounded-2xl border bg-white p-4',
                  b.is_open ? 'border-red-200' : 'border-line', b.id === highlight && 'ring-2 ring-accent')}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-mono text-sm font-bold text-ink">{b.number}</p>
                      <p className="text-sm text-ink-muted">{b.equipment.code} · {b.equipment.name}</p>
                    </div>
                    <span className="flex gap-1.5">
                      <StatusBadge status={b.severity} label={SEVERITY_LABELS[b.severity]} tone={priorityTone(b.severity)} />
                      {b.is_open
                        ? <StatusBadge status="open" label={b.equipment_down ? 'Down' : 'Open'} tone="red" />
                        : <StatusBadge status="resolved" label="Restored" tone="green" />}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-ink">{b.description}</p>
                  <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                    <dt className="text-ink-muted">Category</dt><dd className="text-right">{FAULT_LABELS[b.category]}</dd>
                    <dt className="text-ink-muted">Failed</dt><dd className="text-right">{formatDateTime(b.started_at)}</dd>
                    <dt className="text-ink-muted">Restored</dt>
                    <dd className="text-right">{b.restored_at ? formatDateTime(b.restored_at) : <span className="font-semibold text-red-600">Not yet</span>}</dd>
                    <dt className="text-ink-muted">Downtime</dt>
                    <dd className="text-right font-semibold">{b.equipment_down ? `${formatDuration(b.downtime_minutes)}${b.is_open ? ' so far' : ''}` : 'Not stopped'}</dd>
                  </dl>
                  {b.possible_cause && <p className="mt-2 text-sm"><span className="text-ink-muted">Possible cause: </span>{b.possible_cause}</p>}
                  {b.actions_taken && <p className="mt-1 text-sm"><span className="text-ink-muted">Actions: </span>{b.actions_taken}</p>}
                  {b.work_orders.length > 0 && (
                    <p className="mt-2 flex flex-wrap gap-2 text-sm">
                      {b.work_orders.map((w) => (
                        <Link key={w.id} to={`/maintenance/work-orders?view=all&wo=${w.id}`}
                          className="rounded-lg bg-surface-muted px-2 py-0.5 font-mono text-xs font-semibold text-primary hover:underline">
                          {w.number} · {WO_STATUS_LABELS[w.status]}
                        </Link>
                      ))}
                    </p>
                  )}
                  {canLog && (
                    <div className="mt-auto flex flex-wrap gap-2 pt-3">
                      {b.is_open && (
                        <button type="button" className={`${btnSmallPrimary} h-10 px-4 text-sm`} onClick={() => setDialog({ kind: 'restore', bd: b })}>
                          <ShieldCheck className="size-4" aria-hidden /> Back in service
                        </button>
                      )}
                      <button type="button" className={`${btnSmallGhost} h-10 px-3 text-sm`} onClick={() => setDialog({ kind: 'edit', bd: b })}>
                        <Pencil className="size-4" aria-hidden /> Update
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
            <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun="breakdowns" onChange={setOffset} />
          </>
        )}
      </Card>

      {dialog?.kind === 'log' && <LogBreakdownModal canRaise={can('work_orders.create')} onClose={() => setDialog(null)}
        onDone={(b) => done(`${b.number} logged${b.work_orders[0] ? ` · ${b.work_orders[0].number} raised` : ''}`)} />}
      {dialog?.kind === 'restore' && <RestoreBreakdownModal bd={dialog.bd} onClose={() => setDialog(null)}
        onDone={(b) => done(`${b.number} restored after ${formatDuration(b.downtime_minutes)}`)} />}
      {dialog?.kind === 'edit' && <EditBreakdownModal bd={dialog.bd} onClose={() => setDialog(null)}
        onDone={(b) => done(`${b.number} updated`)} />}
    </>
  )
}
