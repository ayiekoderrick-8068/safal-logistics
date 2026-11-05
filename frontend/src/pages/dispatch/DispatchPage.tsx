import { CalendarDays, CircleCheck, Clock, MapPin, Plus, Timer, TriangleAlert, Truck } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useAuth } from '../../auth/context'
import { btnPrimary, btnSecondary, btnSmallGhost, btnSmallPrimary } from '../../components/ui/buttons'
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
import {
  DELAY_CAUSE_LABELS,
  describeChange,
  formatDate,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
} from '../../lib/format'
import { formatClock } from '../../lib/time'
import type { Dispatch, DispatchOverview, Meta, Page, Route } from '../../lib/types'
import { StatusDonut } from '../overview/charts'
import { todayIn } from '../overview/period'
import { DeliverModal, FlagDelayModal, NewDispatchModal, RouteModal } from './DispatchModals'

const PAGE_SIZE = 8
const STATUS_OPTIONS = [
  { value: '', label: 'Status: All' },
  { value: 'in_transit', label: 'In Transit' },
  { value: 'delivered', label: 'Delivered' },
  { value: 'delayed', label: 'Delayed' },
]
const DONUT_COLORS = { delivered: '#16a34a', in_transit: '#3b82f6', pending: '#f59e0b', delayed: '#ef4444', cancelled: '#94a3b8' }

type Dialog =
  | { kind: 'new'; scheduleId?: number }
  | { kind: 'route' }
  | { kind: 'deliver'; dispatch: Dispatch }
  | { kind: 'flag'; dispatch: Dispatch }
  | null

function dispatchBadge(d: Dispatch) {
  if (d.status === 'in_transit' && (d.is_delayed || d.is_overdue)) return <StatusBadge status="delayed" />
  if (d.status === 'delivered' && d.is_delayed) return <StatusBadge status="delayed" label="Delivered late" />
  return <StatusBadge status={d.status} />
}

function PerfBar({ icon, label, value, pct, color }: { icon: ReactNode; label: string; value: string; pct: number | null; color: string }) {
  return (
    <li className="flex items-center gap-3 text-sm">
      <span className="text-ink-muted" aria-hidden>{icon}</span>
      <span className="w-40 text-ink">{label}</span>
      <span className="h-2 flex-1 rounded-full bg-surface-muted" aria-hidden>
        <span className="block h-2 rounded-full" style={{ width: `${Math.min(100, pct ?? 0)}%`, background: color }} />
      </span>
      <span className="w-20 text-right font-semibold text-ink">{value}</span>
    </li>
  )
}

export function DispatchPage() {
  const { hasRole } = useAuth()
  const canOps = hasRole('operations')
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const prefill = Number(params.get('schedule')) || undefined

  const [day, setDay] = useState(todayIn())
  const [statusFilter, setStatusFilter] = useState('')
  const [routeFilter, setRouteFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [version, setVersion] = useState(0)
  const [dialog, setDialog] = useState<Dialog>(prefill && canOps ? { kind: 'new', scheduleId: prefill } : null)

  const overview = useApi<DispatchOverview>(`/dispatch/overview?date=${day}&v=${version}`)
  const routes = useApi<Route[]>(`/routes?v=${version}`)
  const meta = useApi<Meta>('/meta')
  const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (statusFilter === 'delayed') q.set('delayed', 'true')
  else if (statusFilter) q.set('status', statusFilter)
  if (routeFilter) q.set('route_id', routeFilter)
  const list = useApi<Page<Dispatch>>(`/dispatches?${q}`)

  const reload = () => setVersion((v) => v + 1)
  const closeDialog = () => {
    setDialog(null)
    if (params.has('schedule')) setParams({}, { replace: true })
  }
  const o = overview.data
  const hasActivity = o ? o.hourly.some((h) => h.delivered + h.in_transit + h.delayed > 0) : false

  return (
    <>
      <PageHeader
        title="Dispatch Management"
        description="Dispatch loaded trucks, track deliveries and flag delays."
        actions={
          <>
            <label className="relative flex items-center">
              <span className="sr-only">Dispatch date</span>
              <CalendarDays className="pointer-events-none absolute left-3.5 size-5 text-primary" aria-hidden />
              <input type="date" value={day} required onChange={(e) => e.target.value && setDay(e.target.value)}
                className="h-11 rounded-xl border border-white bg-white pr-3 pl-11 font-semibold text-ink shadow-sm" />
            </label>
            {canOps && (
              <>
                <button type="button" className={btnSecondary} onClick={() => setDialog({ kind: 'route' })}>
                  <MapPin className="size-4" aria-hidden /> Add Route
                </button>
                <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'new' })}>
                  <Plus className="size-4" aria-hidden /> New Dispatch
                </button>
              </>
            )}
          </>
        }
      />
      {o?.sample_data && <SampleDataBanner />}

      {overview.error && !o ? (
        <Card><ErrorState message={overview.error.message} onRetry={overview.refetch} /></Card>
      ) : !o ? (
        <Card><LoadingState label="Loading dispatch data…" /></Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard icon={Truck} tone="blue" label="Active Dispatches" value={formatNumber(o.active)} note="Pending or on the road" />
            <StatCard icon={MapPin} tone="teal" label="In Transit" value={formatNumber(o.in_transit)}
              note={o.active ? `${formatPercent((o.in_transit / o.active) * 100)} of active` : undefined} />
            <StatCard icon={TriangleAlert} tone="red" label="Delayed Deliveries" value={formatNumber(o.delayed_active)} note="In transit, behind ETA" />
            <StatCard icon={CircleCheck} tone="green" label="Delivered" value={formatNumber(o.delivered_today)}
              trend={describeChange(o.delivered_today, o.delivered_previous_day, 'abs', true)} note={`on ${formatDate(o.date)}`} />
            <StatCard icon={Timer} tone="blue" label="On-Time Rate" value={formatPercent(o.on_time_rate_7d)}
              trend={describeChange(o.on_time_rate_7d, o.on_time_rate_prev_7d, 'pp', true)} note="last 7 days" />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-7">
              <CardHeader title="Live Dispatch Overview" subtitle={`Dispatches by departure hour and current status (${formatDate(o.date)}).`} />
              {!hasActivity ? <EmptyState title="No dispatches on this day" /> : (
                <div className="h-60" role="img" aria-label="Dispatches per hour by status">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={o.hourly.map((h) => ({ ...h, label: `${String(h.hour).padStart(2, '0')}:00` }))}
                      margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                      <CartesianGrid stroke="#e6eef3" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                      <Tooltip />
                      <Legend verticalAlign="bottom" height={28} iconSize={10} wrapperStyle={{ fontSize: 13 }} />
                      <Bar dataKey="delivered" name="Delivered" stackId="s" fill="#22a447" isAnimationActive={false} />
                      <Bar dataKey="in_transit" name="In Transit" stackId="s" fill="#2f86eb" isAnimationActive={false} />
                      <Bar dataKey="delayed" name="Delayed" stackId="s" fill="#f8c95a" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
            <Card className="xl:col-span-5">
              <CardHeader title="Delivery Status Breakdown" subtitle={`Dispatches that departed on ${formatDate(o.date)}.`} />
              {o.status_breakdown.length === 0 ? <EmptyState title="No dispatches on this day" /> : (
                <StatusDonut rows={o.status_breakdown} centerLabel="Dispatches" colors={DONUT_COLORS} />
              )}
            </Card>
          </div>
        </>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4">
        <Card className="order-2">
          <CardHeader
            title="Route & Delivery Monitoring"
            action={
              <div className="flex flex-wrap gap-2">
                <FilterSelect label="Filter by status" value={statusFilter} options={STATUS_OPTIONS}
                  onChange={(v) => { setStatusFilter(v); setOffset(0) }} />
                <FilterSelect label="Filter by route" value={routeFilter}
                  options={[{ value: '', label: 'Route: All' }, ...(routes.data ?? []).map((r) => ({ value: String(r.id), label: r.label }))]}
                  onChange={(v) => { setRouteFilter(v); setOffset(0) }} />
              </div>
            }
          />
          {list.error && !list.data ? (
            <ErrorState message={list.error.message} onRetry={list.refetch} />
          ) : !list.data ? (
            <LoadingState />
          ) : list.data.items.length === 0 ? (
            <EmptyState title="No dispatches match">{canOps && 'Dispatch a loaded truck with “New Dispatch”.'}</EmptyState>
          ) : (
            <>
              <div className="-mx-2 overflow-x-auto">
                <table className="w-full min-w-[900px] text-left text-sm whitespace-nowrap">
                  <thead>
                    <tr className="bg-surface-muted text-ink">
                      {['Load', 'Truck No.', 'Route', 'Departure', 'ETA', 'Arrived', 'Turnaround', 'Status', 'Delay', 'Actions'].map((h) => (
                        <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {list.data.items.map((d) => (
                      <tr key={d.id} className="border-b border-line last:border-0">
                        <td className="px-3 py-2.5 text-ink-muted">{d.load_ref}</td>
                        <td className="px-3 py-2.5">
                          <span className="block font-semibold text-ink">{d.truck.label}</span>
                          <span className="block text-xs text-ink-muted">{d.driver_name ?? 'No driver'}</span>
                        </td>
                        <td className="px-3 py-2.5">{d.route.label}</td>
                        <td className="px-3 py-2.5">{formatDateTime(d.dispatched_at)}</td>
                        <td className="px-3 py-2.5">{formatClock(d.expected_arrival_at)}</td>
                        <td className="px-3 py-2.5">{formatClock(d.actual_arrival_at)}</td>
                        <td className="px-3 py-2.5">{formatDuration(d.turnaround_minutes)}</td>
                        <td className="px-3 py-2.5">{dispatchBadge(d)}</td>
                        <td className="px-3 py-2.5">
                          {d.delay_minutes > 0 ? <span className="font-semibold text-red-600">+{d.delay_minutes} min</span> : '–'}
                          {d.delay_cause && <span className="block text-xs text-ink-muted">{DELAY_CAUSE_LABELS[d.delay_cause]}</span>}
                        </td>
                        <td className="px-3 py-2.5">
                          {canOps && d.status === 'in_transit' && (
                            <div className="flex gap-1.5">
                              <button type="button" className={btnSmallPrimary} onClick={() => setDialog({ kind: 'deliver', dispatch: d })}>
                                <CircleCheck className="size-3.5" aria-hidden /> Delivered
                              </button>
                              <button type="button" className={btnSmallGhost} onClick={() => setDialog({ kind: 'flag', dispatch: d })}>
                                Flag delay
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun="dispatches" onChange={setOffset} />
            </>
          )}
        </Card>

        <div className="order-1 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader title="Dispatch Alerts" subtitle="Trucks behind ETA and late deliveries." />
            {!o || o.alerts.length === 0 ? <EmptyState title="No delivery delays" /> : (
              <ul className="space-y-2.5">
                {o.alerts.map((d) => (
                  <li key={d.id} className="flex items-start gap-3 rounded-xl border border-red-100 bg-red-50 p-3 text-sm">
                    <TriangleAlert className="mt-0.5 size-5 shrink-0 text-red-600" aria-hidden />
                    <div className="min-w-0">
                      <p className="font-semibold text-ink">
                        {d.truck.label} – {d.status === 'delivered' ? 'Delivered late' : d.is_overdue ? 'Missed ETA' : 'Delay reported'}
                      </p>
                      <p className="text-xs text-ink-muted">
                        {d.route.label} · {d.delay_minutes} min{d.delay_cause ? ` · ${DELAY_CAUSE_LABELS[d.delay_cause]}` : ''}
                      </p>
                    </div>
                    <StatusBadge status="delayed" />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Dispatch Performance" subtitle="Deliveries completed in the last 7 days." />
            {!o ? <LoadingState /> : (
              <ul className="space-y-4">
                <PerfBar icon={<CircleCheck className="size-5 text-emerald-600" />} label="On-time deliveries"
                  value={formatPercent(o.on_time_rate_7d)} pct={o.on_time_rate_7d} color="#22a447" />
                <PerfBar icon={<TriangleAlert className="size-5 text-red-500" />} label="Delayed deliveries"
                  value={formatPercent(o.delayed_rate_7d)} pct={o.delayed_rate_7d} color="#ef4444" />
                <PerfBar icon={<Clock className="size-5 text-sky-600" />} label="Avg delivery duration"
                  value={formatDuration(o.avg_delivery_minutes_7d)}
                  pct={o.avg_delivery_minutes_7d == null ? null : (o.avg_delivery_minutes_7d / 600) * 100} color="#2f86eb" />
              </ul>
            )}
          </Card>
        </div>
      </div>

      {dialog?.kind === 'new' && (
        <NewDispatchModal scheduleId={dialog.scheduleId} onClose={closeDialog}
          onSaved={(d) => { closeDialog(); reload(); toast.success(`${d.load_ref}: ${d.truck.label} dispatched`) }} />
      )}
      {dialog?.kind === 'route' && (
        <RouteModal onClose={closeDialog} onSaved={(r) => { closeDialog(); reload(); toast.success(`Route ${r.label} added`) }} />
      )}
      {dialog?.kind === 'deliver' && (
        <DeliverModal dispatch={dialog.dispatch} graceMinutes={meta.data?.delay_grace_minutes ?? 15} onClose={closeDialog}
          onSaved={(d) => { closeDialog(); reload(); toast.success(`${d.load_ref} delivered${d.is_delayed ? ' (late)' : ''}`) }} />
      )}
      {dialog?.kind === 'flag' && (
        <FlagDelayModal dispatch={dialog.dispatch} onClose={closeDialog}
          onSaved={(d) => { closeDialog(); reload(); toast.success(`${d.load_ref} flagged as delayed`) }} />
      )}
    </>
  )
}
