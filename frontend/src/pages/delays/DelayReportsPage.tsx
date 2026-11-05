import { CircleCheck, Clock, Hourglass, Plus, Search, Timer, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useAuth } from '../../auth/context'
import { btnPrimary, btnSmallGhost } from '../../components/ui/buttons'
import { Card, CardHeader } from '../../components/ui/Card'
import { FilterSelect } from '../../components/ui/FilterSelect'
import { PageHeader } from '../../components/ui/PageHeader'
import { Pagination } from '../../components/ui/Pagination'
import { SampleDataBanner } from '../../components/ui/SampleDataBanner'
import { StatCard } from '../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useToast } from '../../components/ui/toastContext'
import { useApi } from '../../hooks/useApi'
import { useDebounced } from '../../hooks/useDebounced'
import { DELAY_CAUSE_LABELS, formatDateTime, formatDuration, formatNumber } from '../../lib/format'
import type { Incident, IncidentSummary, Page } from '../../lib/types'
import { StatusDonut } from '../overview/charts'
import { ReportDelayModal, UpdateIncidentModal, type ReportPreset } from './IncidentModals'

const PAGE_SIZE = 10
const CAUSE_COLORS: Record<string, string> = {
  loading_congestion: '#1d6fd8', vehicle_breakdown: '#ef4444', documentation: '#f59e0b',
  equipment_breakdown: '#8b5cf6', truck_unavailability: '#0ea5a4', traffic: '#64748b', other: '#22b8d6',
}
const STATUS_OPTIONS = [
  { value: '', label: 'Status: All' },
  { value: 'unresolved', label: 'Unresolved' },
  { value: 'open', label: 'Open' },
  { value: 'investigating', label: 'Investigating' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'resolved', label: 'Resolved' },
]

function parsePreset(value: string | null): ReportPreset | undefined {
  const m = value?.match(/^(schedule|dispatch):(\d+)$/)
  return m ? { source: m[1] === 'schedule' ? 'loading' : 'dispatch', id: Number(m[2]) } : undefined
}

export function DelayReportsPage() {
  const { hasRole } = useAuth()
  const canEdit = hasRole('operations', 'fleet_manager', 'compliance')
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const preset = parsePreset(params.get('report'))
  const [status, setStatus] = useState('')
  const [cause, setCause] = useState('')
  const [source, setSource] = useState('')
  const [mine, setMine] = useState(false)
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [version, setVersion] = useState(0)
  const [reporting, setReporting] = useState(!!preset && canEdit)
  const [editing, setEditing] = useState<Incident | null>(null)
  const q = useDebounced(query.trim())

  const summary = useApi<IncidentSummary>(`/incidents/summary?v=${version}`)
  const unresolved = useApi<Page<Incident>>(`/incidents?status=unresolved&limit=5&v=${version}`)
  const qs = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (status) qs.set('status', status)
  if (cause) qs.set('cause', cause)
  if (source) qs.set('source', source)
  if (mine) qs.set('mine', 'true')
  if (q) qs.set('q', q)
  const list = useApi<Page<Incident>>(`/incidents?${qs}`)
  const reload = () => setVersion((v) => v + 1)
  const s = summary.data
  const resetPage = () => setOffset(0)

  return (
    <>
      <PageHeader
        title="Delay Reports"
        description="Report, assign and resolve loading and dispatch delays, and track recurring causes."
        actions={canEdit && (
          <button type="button" className={btnPrimary} onClick={() => setReporting(true)}>
            <Plus className="size-4" aria-hidden /> Report Delay
          </button>
        )}
      />
      {s?.sample_data && <SampleDataBanner />}

      {summary.error && !s ? (
        <Card><ErrorState message={summary.error.message} onRetry={summary.refetch} /></Card>
      ) : !s ? (
        <Card><LoadingState label="Loading delay data…" /></Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard icon={TriangleAlert} tone="red" label="Unresolved Delays" value={formatNumber(s.unresolved)}
              note={`${s.unassigned} unassigned`} />
            <StatCard icon={CircleCheck} tone="green" label="Resolved" value={formatNumber(s.resolved_7d)} note="Last 7 days" />
            <StatCard icon={Timer} tone="blue" label="Avg Resolution Time" value={formatDuration(s.avg_resolution_minutes_30d)}
              note="Start → resolution, 30 days" />
            <StatCard icon={Clock} tone="amber" label="Delay Impact" value={formatDuration(s.impact_minutes_7d)}
              note="Reported impact, 7 days" />
            <StatCard icon={Hourglass} tone="teal" label="Oldest Unresolved" value={formatDuration(s.oldest_unresolved_minutes)}
              note={s.oldest_unresolved_minutes == null ? 'Nothing open' : 'Since the delay started'} />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-5">
              <CardHeader title="Delay Causes" subtitle="Incidents by category, last 30 days." />
              {s.by_cause_30d.length === 0 ? <EmptyState title="No delays reported in 30 days" /> : (
                <StatusDonut rows={s.by_cause_30d.map((c) => ({ status: c.cause, count: c.count }))}
                  centerLabel="Delays" colors={CAUSE_COLORS} labels={DELAY_CAUSE_LABELS} />
              )}
            </Card>
            <Card className="xl:col-span-7">
              <CardHeader title="Unresolved Incidents" subtitle="Most recent first." />
              {!unresolved.data ? <LoadingState /> : unresolved.data.items.length === 0 ? (
                <EmptyState title="All delays resolved" />
              ) : (
                <ul className="space-y-2.5">
                  {unresolved.data.items.map((i) => (
                    <li key={i.id} className="flex items-start gap-3 rounded-xl border border-red-100 bg-red-50 p-3 text-sm">
                      <TriangleAlert className="mt-0.5 size-5 shrink-0 text-red-600" aria-hidden />
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-ink">{i.truck?.label} – {DELAY_CAUSE_LABELS[i.cause]}</p>
                        <p className="truncate text-xs text-ink-muted">
                          {i.operation} · {formatDuration(i.duration_minutes)} ongoing · {i.assigned_to ? i.assigned_to.label : 'Unassigned'}
                        </p>
                      </div>
                      {canEdit && (
                        <button type="button" className={btnSmallGhost} onClick={() => setEditing(i)}>Update</button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}

      <Card className="mt-4">
        <CardHeader
          title="Delay Incidents"
          action={
            <div className="flex flex-wrap items-center gap-2">
              <FilterSelect label="Filter by status" value={status} options={STATUS_OPTIONS} onChange={(v) => { setStatus(v); resetPage() }} />
              <FilterSelect label="Filter by category" value={cause} onChange={(v) => { setCause(v); resetPage() }}
                options={[{ value: '', label: 'Category: All' }, ...Object.entries(DELAY_CAUSE_LABELS).map(([value, label]) => ({ value, label }))]} />
              <FilterSelect label="Filter by operation" value={source} onChange={(v) => { setSource(v); resetPage() }}
                options={[{ value: '', label: 'Operation: All' }, { value: 'loading', label: 'Loading' }, { value: 'dispatch', label: 'Dispatch' }]} />
              <label className="flex h-11 items-center gap-2 rounded-xl border border-line bg-white px-3 text-sm font-semibold text-ink shadow-sm">
                <input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); resetPage() }} className="size-4 accent-[#0e6481]" />
                Assigned to me
              </label>
              <label className="relative">
                <span className="sr-only">Search delays</span>
                <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-ink-muted" aria-hidden />
                <input type="search" value={query} onChange={(e) => { setQuery(e.target.value); resetPage() }}
                  placeholder="Truck, load or text…"
                  className="h-11 w-52 rounded-xl border border-line bg-white pr-3 pl-10 text-ink shadow-sm placeholder:text-ink-muted" />
              </label>
            </div>
          }
        />
        {list.error && !list.data ? (
          <ErrorState message={list.error.message} onRetry={list.refetch} />
        ) : !list.data ? (
          <LoadingState />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="No delay incidents match" />
        ) : (
          <>
            <div className="-mx-2 overflow-x-auto">
              <table className="w-full min-w-[1000px] text-left text-sm whitespace-nowrap">
                <thead>
                  <tr className="bg-surface-muted text-ink">
                    {['Started', 'Truck No.', 'Operation', 'Category', 'Duration', 'Impact', 'Assigned to', 'Status', 'Actions'].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((i) => (
                    <tr key={i.id} className="border-b border-line last:border-0">
                      <td className="px-3 py-2.5">{formatDateTime(i.started_at)}</td>
                      <td className="px-3 py-2.5 font-semibold text-ink">{i.truck?.label ?? '—'}</td>
                      <td className="max-w-64 truncate px-3 py-2.5" title={i.operation}>{i.operation}</td>
                      <td className="px-3 py-2.5">{DELAY_CAUSE_LABELS[i.cause]}</td>
                      <td className="px-3 py-2.5">
                        {formatDuration(i.duration_minutes)}
                        {i.is_ongoing && <span className="block text-xs font-semibold text-red-600">Ongoing</span>}
                      </td>
                      <td className="px-3 py-2.5">{i.impact_minutes ? `+${i.impact_minutes} min` : '–'}</td>
                      <td className="px-3 py-2.5">{i.assigned_to?.label ?? <span className="text-ink-muted">Unassigned</span>}</td>
                      <td className="px-3 py-2.5"><StatusBadge status={i.status} /></td>
                      <td className="px-3 py-2.5">
                        {canEdit && (
                          <button type="button" className={btnSmallGhost} onClick={() => setEditing(i)}
                            aria-label={`Update delay ${i.id} for ${i.truck?.label ?? 'operation'}`}>
                            {i.status === 'resolved' ? 'View / reopen' : 'Update'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun="incidents" onChange={setOffset} />
          </>
        )}
      </Card>

      {reporting && (
        <ReportDelayModal preset={preset}
          onClose={() => { setReporting(false); if (params.has('report')) setParams({}, { replace: true }) }}
          onSaved={(i) => {
            setReporting(false)
            if (params.has('report')) setParams({}, { replace: true })
            reload()
            toast.success(`Delay reported for ${i.truck?.label ?? 'operation'}`)
          }} />
      )}
      {editing && (
        <UpdateIncidentModal incident={editing} onClose={() => setEditing(null)}
          onSaved={(i) => { setEditing(null); reload(); toast.success(`Delay #${i.id} ${i.status === 'resolved' ? 'resolved' : 'updated'}`) }} />
      )}
    </>
  )
}
