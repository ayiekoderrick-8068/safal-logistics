import clsx from 'clsx'
import { CalendarDays, Clock, Plus, Send, Timer, TriangleAlert, Warehouse, X } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useAuth } from '../../auth/context'
import { btnPrimary, btnSecondary, btnSmallGhost, btnSmallPrimary } from '../../components/ui/buttons'
import { Card, CardHeader } from '../../components/ui/Card'
import { ConfirmModal } from '../../components/ui/ConfirmModal'
import { FilterSelect } from '../../components/ui/FilterSelect'
import { PageHeader } from '../../components/ui/PageHeader'
import { Pagination } from '../../components/ui/Pagination'
import { SampleDataBanner } from '../../components/ui/SampleDataBanner'
import { StatCard } from '../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useToast } from '../../components/ui/toastContext'
import { useApi } from '../../hooks/useApi'
import { api } from '../../lib/api'
import { describeChange, formatDate, formatDuration, formatNumber } from '../../lib/format'
import { formatClock } from '../../lib/time'
import type { Bay, LoadingOverview, Page, Schedule } from '../../lib/types'
import { StatusDonut } from '../overview/charts'
import { todayIn } from '../overview/period'
import { BayModal } from './BayModal'
import { EventModal } from './EventModal'
import { EVENT_LABELS, nextEvent, type ScheduleEvent } from './events'
import { ScheduleModal } from './ScheduleModal'

const PAGE_SIZE = 8
const STATUS_OPTIONS = [
  { value: '', label: 'Status: All' },
  ...['scheduled', 'arrived', 'loading', 'loaded', 'departed', 'cancelled'].map((s) => ({
    value: s, label: s[0].toUpperCase() + s.slice(1),
  })),
]
const BAY_COLORS = { in_use: '#16a34a', available: '#3b82f6', reserved: '#f59e0b', inactive: '#ef4444' }
const BAY_STATE_LABEL = { in_use: 'In use', available: 'Available', reserved: 'Reserved', inactive: 'Out of service' }

type Dialog =
  | { kind: 'schedule'; truckId?: number }
  | { kind: 'bay' }
  | { kind: 'event'; schedule: Schedule; event: ScheduleEvent }
  | { kind: 'cancel'; schedule: Schedule }
  | null

export function LoadingBaysPage() {
  const { hasRole } = useAuth()
  const canOps = hasRole('operations')
  const toast = useToast()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const prefillTruck = Number(params.get('truck')) || undefined

  const [day, setDay] = useState(todayIn())
  const [bayFilter, setBayFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [version, setVersion] = useState(0)
  const [dialog, setDialog] = useState<Dialog>(prefillTruck && canOps ? { kind: 'schedule', truckId: prefillTruck } : null)

  const overview = useApi<LoadingOverview>(`/loading/overview?date=${day}&v=${version}`)
  const bays = useApi<Bay[]>(`/bays?v=${version}`)
  const q = new URLSearchParams({ date: day, limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (bayFilter) q.set('bay_id', bayFilter)
  if (statusFilter) q.set('status', statusFilter)
  const schedules = useApi<Page<Schedule>>(`/schedules?${q}`)

  const reload = () => setVersion((v) => v + 1)
  const closeDialog = () => {
    setDialog(null)
    if (params.has('truck')) setParams({}, { replace: true })
  }
  const o = overview.data
  const board = o?.bay_board ?? []
  const counts = (['in_use', 'available', 'reserved', 'inactive'] as const).map((state) => ({
    status: state, count: board.filter((b) => b.state === state).length,
  }))
  const utilisation = board.length ? Math.round((counts[0].count / board.length) * 100) : 0

  return (
    <>
      <PageHeader
        title="Loading Bays & Scheduling"
        description="Book loading bays, record loading times and monitor bay utilisation."
        actions={
          <>
            <label className="relative flex items-center">
              <span className="sr-only">Schedule date</span>
              <CalendarDays className="pointer-events-none absolute left-3.5 size-5 text-primary" aria-hidden />
              <input type="date" value={day} required
                onChange={(e) => { if (e.target.value) { setDay(e.target.value); setOffset(0) } }}
                className="h-11 rounded-xl border border-white bg-white pr-3 pl-11 font-semibold text-ink shadow-sm" />
            </label>
            {canOps && (
              <>
                <button type="button" className={btnSecondary} onClick={() => setDialog({ kind: 'bay' })}>
                  <Plus className="size-4" aria-hidden /> Add Bay
                </button>
                <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'schedule' })}>
                  <Plus className="size-4" aria-hidden /> Schedule Loading
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
        <Card><LoadingState label="Loading bay operations…" /></Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard icon={Warehouse} tone="blue" label="Active Bays" value={formatNumber(o.active_bays)}
              note={`of ${o.total_bays} bays`} />
            <StatCard icon={CalendarDays} tone="green" label="Scheduled Loads" value={formatNumber(o.scheduled_count)}
              note={`${o.completed_count} loaded · ${formatDate(o.date)}`} />
            <StatCard icon={Clock} tone="teal" label="Average Loading Time" value={formatDuration(o.avg_loading_minutes)}
              trend={describeChange(o.avg_loading_minutes, o.avg_loading_minutes_previous_day, 'abs', false)}
              note={o.avg_loading_minutes == null ? 'No loads finished' : 'min vs previous day'} />
            <StatCard icon={Timer} tone="blue" label="Avg Turnaround" value={formatDuration(o.avg_turnaround_minutes)}
              note={o.avg_turnaround_minutes == null ? 'No departures yet' : 'arrival → departure'} />
            <StatCard icon={TriangleAlert} tone="red" label="Delayed Loads" value={formatNumber(o.late_count)}
              note="Missed start or overrunning" />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-7">
              <CardHeader title="Loading Schedule Performance" subtitle={`Scheduled vs. completed loads by hour (${formatDate(o.date)}).`} />
              {o.scheduled_count === 0 ? (
                <EmptyState title="No loads scheduled for this day" />
              ) : (
                <div className="h-60" role="img" aria-label="Loads scheduled and completed per hour">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={o.hourly.map((h) => ({ ...h, label: `${String(h.hour).padStart(2, '0')}:00` }))}
                      margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                      <CartesianGrid stroke="#e6eef3" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                      <Tooltip />
                      <Legend verticalAlign="top" align="right" height={28} iconSize={10} wrapperStyle={{ fontSize: 13 }} />
                      <Bar dataKey="scheduled" name="Scheduled" fill="#b6dcf7" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                      <Bar dataKey="completed" name="Completed" fill="#1d7fe0" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
            <Card className="xl:col-span-5">
              <CardHeader title="Bay Utilization" subtitle="Current loading bay status distribution." />
              {board.length === 0 ? (
                <EmptyState title="No loading bays yet">{canOps && 'Use “Add Bay” to create one.'}</EmptyState>
              ) : (
                <StatusDonut rows={counts} centerValue={`${utilisation}%`} centerLabel="Utilization" colors={BAY_COLORS}
                  labels={BAY_STATE_LABEL} />
              )}
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader title="Loading Bay Status" subtitle="Live state of every bay." />
            {board.length === 0 ? <EmptyState title="No loading bays yet" /> : (
                <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {board.map((b) => (
                    <li key={b.bay.id} className="rounded-xl border border-line p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-2 font-bold text-ink">
                          <Warehouse className="size-4.5 text-primary" aria-hidden /> {b.bay.name}
                        </span>
                        <StatusBadge status={b.state} label={BAY_STATE_LABEL[b.state]} />
                      </div>
                      {b.schedule ? (
                        <>
                          <p className="mt-2 truncate text-sm text-ink">
                            <span className="font-semibold">{b.schedule.truck.label}</span>
                            {b.schedule.driver_name && <span className="text-ink-muted"> · {b.schedule.driver_name}</span>}
                          </p>
                          <p className="text-xs text-ink-muted">
                            {b.state === 'reserved' ? 'Booked ' : 'Window '}
                            {formatClock(b.schedule.scheduled_start)}–{formatClock(b.schedule.scheduled_end)} · {b.schedule.status}
                          </p>
                          {b.progress_pct != null && (
                            <div className="mt-2 flex items-center gap-2">
                              <div className="h-2 flex-1 rounded-full bg-surface-muted"
                                role="progressbar" aria-valuenow={b.progress_pct} aria-valuemin={0} aria-valuemax={100}
                                aria-label={`${b.bay.name} booking progress`}>
                                <div className="h-2 rounded-full bg-primary" style={{ width: `${b.progress_pct}%` }} />
                              </div>
                              <span className="text-xs font-semibold text-ink">{b.progress_pct}%</span>
                            </div>
                          )}
                        </>
                      ) : (
                        <p className="mt-2 text-sm text-ink-muted">{b.state === 'inactive' ? 'Not in service' : 'No truck at bay'}</p>
                      )}
                    </li>
                  ))}
                </ul>
            )}
          </Card>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="Upcoming Loads" subtitle={formatDate(o.date)} />
              {o.upcoming.length === 0 ? <EmptyState title="Nothing else booked" /> : (
                <ul className="divide-y divide-line">
                  {o.upcoming.map((s) => (
                    <li key={s.id} className="flex items-center gap-3 py-2.5 text-sm">
                      <span className="rounded-lg bg-surface-muted px-2 py-1 font-semibold text-ink">{formatClock(s.scheduled_start)}</span>
                      <span className="min-w-0">
                        <span className="block font-semibold text-ink">{s.truck.label}</span>
                        <span className="block truncate text-xs text-ink-muted">{s.bay.label}{s.driver_name ? ` · ${s.driver_name}` : ''}</span>
                      </span>
                      <span className="ml-auto"><StatusBadge status={s.is_late ? 'late' : s.status} label={s.is_late ? 'Late' : undefined} /></span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <CardHeader title="Recent Delays & Alerts" subtitle="Loads that missed their start or are overrunning." />
              {o.late.length === 0 ? <EmptyState title="No loading delays" /> : (
                <ul className="space-y-2.5">
                  {o.late.map((s) => (
                    <li key={s.id} className="flex items-start gap-3 rounded-xl border border-red-100 bg-red-50 p-3 text-sm">
                      <TriangleAlert className="mt-0.5 size-5 shrink-0 text-red-600" aria-hidden />
                      <div className="min-w-0">
                        <p className="font-semibold text-ink">
                          {s.truck.label} – {s.status === 'scheduled' ? 'Missed start' : s.status === 'arrived' || s.status === 'loading' ? 'Overrunning' : 'Arrived late'}
                        </p>
                        <p className="text-xs text-ink-muted">{s.bay.label} · {s.late_minutes} min behind schedule</p>
                      </div>
                      <span className="ml-auto"><StatusBadge status="delayed" /></span>
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
            title="Loading Schedule"
            action={
              <div className="flex flex-wrap gap-2">
                <FilterSelect label="Filter by bay" value={bayFilter}
                  options={[{ value: '', label: 'Bay: All' }, ...(bays.data ?? []).map((b) => ({ value: String(b.id), label: b.name }))]}
                  onChange={(v) => { setBayFilter(v); setOffset(0) }} />
                <FilterSelect label="Filter by status" value={statusFilter} options={STATUS_OPTIONS}
                  onChange={(v) => { setStatusFilter(v); setOffset(0) }} />
              </div>
            }
          />
          {schedules.error && !schedules.data ? (
            <ErrorState message={schedules.error.message} onRetry={schedules.refetch} />
          ) : !schedules.data ? (
            <LoadingState />
          ) : schedules.data.items.length === 0 ? (
            <EmptyState title="No bookings match">{canOps && 'Use “Schedule Loading” to book a bay.'}</EmptyState>
          ) : (
            <>
              <div className="-mx-2 overflow-x-auto">
                <table className="w-full min-w-[860px] text-left text-sm whitespace-nowrap">
                  <thead>
                    <tr className="bg-surface-muted text-ink">
                      {['Truck No.', 'Bay', 'Scheduled', 'Arrived', 'Loading', 'Turnaround', 'Status', 'Action'].map((h) => (
                        <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {schedules.data.items.map((s) => {
                      const next = nextEvent(s.status)
                      return (
                        <tr key={s.id} className="border-b border-line last:border-0">
                          <td className="px-3 py-2.5">
                            <span className="block font-semibold text-ink">{s.truck.label}</span>
                            <span className="block text-xs text-ink-muted">{s.driver_name ?? 'No driver'}</span>
                          </td>
                          <td className="px-3 py-2.5">{s.bay.label}</td>
                          <td className="px-3 py-2.5">{formatClock(s.scheduled_start)} – {formatClock(s.scheduled_end)}</td>
                          <td className="px-3 py-2.5">{formatClock(s.arrival_at)}</td>
                          <td className="px-3 py-2.5">
                            {s.loading_started_at
                              ? `${formatClock(s.loading_started_at)} – ${s.loading_finished_at ? formatClock(s.loading_finished_at) : 'in progress'}`
                              : '—'}
                            {s.loading_minutes != null && <span className="block text-xs text-ink-muted">{formatDuration(s.loading_minutes)}</span>}
                          </td>
                          <td className={clsx('px-3 py-2.5', s.within_target === false && 'font-semibold text-red-600',
                            s.within_target && 'font-semibold text-emerald-700')}>
                            {formatDuration(s.turnaround_minutes)}
                            {s.turnaround_minutes != null && (
                              <span className="block text-xs font-normal text-ink-muted">target {formatDuration(s.target_minutes)}</span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <StatusBadge status={s.status} />
                            {s.is_late && <span className="mt-0.5 block text-xs font-semibold text-red-600">Late {s.late_minutes} min</span>}
                          </td>
                          <td className="px-3 py-2.5">
                            {canOps && (
                              <div className="flex items-center gap-1.5">
                                {next && (
                                  <button type="button" className={btnSmallPrimary}
                                    onClick={() => setDialog({ kind: 'event', schedule: s, event: next })}>
                                    {EVENT_LABELS[next].action}
                                  </button>
                                )}
                                {s.status === 'loaded' && (
                                  <button type="button" className={btnSmallPrimary} onClick={() => navigate(`/dispatch?schedule=${s.id}`)}>
                                    <Send className="size-3.5" aria-hidden /> Dispatch
                                  </button>
                                )}
                                {(s.status === 'scheduled' || s.status === 'arrived') && (
                                  <button type="button" className={btnSmallGhost} aria-label={`Cancel booking for ${s.truck.label}`}
                                    onClick={() => setDialog({ kind: 'cancel', schedule: s })}>
                                    <X className="size-3.5" aria-hidden />
                                  </button>
                                )}
                                {['scheduled', 'arrived', 'loading', 'loaded'].includes(s.status) && (
                                  <button type="button" className={btnSmallGhost} aria-label={`Report delay for ${s.truck.label}`}
                                    onClick={() => navigate(`/delays?report=schedule:${s.id}`)}>
                                    <TriangleAlert className="size-3.5" aria-hidden /> Delay
                                  </button>
                                )}
                                {s.load_ref && <span className="text-xs text-ink-muted">{s.load_ref}</span>}
                              </div>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <Pagination total={schedules.data.total} limit={PAGE_SIZE} offset={offset} noun="loads" onChange={setOffset} />
            </>
          )}
        </Card>

      {dialog?.kind === 'schedule' && (
        <ScheduleModal truckId={dialog.truckId} onClose={closeDialog}
          onSaved={(s) => { closeDialog(); reload(); toast.success(`${s.truck.label} booked at ${s.bay.label}`) }} />
      )}
      {dialog?.kind === 'bay' && (
        <BayModal onClose={closeDialog} onSaved={(b) => { closeDialog(); reload(); toast.success(`${b.name} added`) }} />
      )}
      {dialog?.kind === 'event' && (
        <EventModal schedule={dialog.schedule} event={dialog.event} onClose={closeDialog}
          onSaved={(s) => { closeDialog(); reload(); toast.success(`${s.truck.label}: ${EVENT_LABELS[dialog.event].field.toLowerCase()} recorded`) }} />
      )}
      {dialog?.kind === 'cancel' && (
        <ConfirmModal title="Cancel booking?" confirmLabel="Cancel booking" onClose={closeDialog}
          message={`${dialog.schedule.truck.label} at ${dialog.schedule.bay.label}, ${formatClock(dialog.schedule.scheduled_start)}. The bay slot will be released.`}
          onConfirm={async () => {
            await api(`/schedules/${dialog.schedule.id}/cancel`, { method: 'POST' })
            closeDialog(); reload(); toast.success('Booking cancelled')
          }} />
      )}
    </>
  )
}
