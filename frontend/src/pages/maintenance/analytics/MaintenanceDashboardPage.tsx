import { CalendarClock, CircleCheck, ClipboardList, Clock, TriangleAlert, Wrench } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { Card, CardHeader } from '../../../components/ui/Card'
import { FilterSelect } from '../../../components/ui/FilterSelect'
import { PageHeader } from '../../../components/ui/PageHeader'
import { StatCard } from '../../../components/ui/StatCard'
import { ErrorState, LoadingState } from '../../../components/ui/States'
import { useApi } from '../../../hooks/useApi'
import { formatDateTime, formatDayLabel, formatDuration, formatNumber, formatPercent } from '../../../lib/format'
import { FAULT_LABELS, type MaintenanceDashboard } from '../../../lib/maintenance'
import { STATUS } from './chartColors'
import { ChartCard, DailyColumns, HBars, SegmentedBar } from './charts'
import { ReliabilityMetrics } from './Metrics'

const PERIODS = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
]

export function MaintenanceDashboardPage() {
  const [days, setDays] = useState('30')
  const { data: d, error, refetch, loading } = useApi<MaintenanceDashboard>(`/maintenance/dashboard?days=${days}`)

  return (
    <>
      <PageHeader
        title="Maintenance Dashboard"
        description="Equipment health, schedules, work orders and breakdowns, from live records."
        actions={<FilterSelect label="Reporting period" value={days} options={PERIODS} onChange={setDays} />}
      />
      {error && !d ? <ErrorState message={error.message} onRetry={refetch} /> : !d?.kpis ? <LoadingState /> : (
        // Previous render stays (dimmed) while a new period loads: no skeleton flash.
        <div className={loading ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
          <Body d={d} />
        </div>
      )}
    </>
  )
}

function Body({ d }: { d: MaintenanceDashboard }) {
  const k = d.kpis
  const period = `Last ${d.window_days} days`
  const wo = d.work_orders
  const pipeline = [
    { label: 'Open', value: wo.open },
    { label: 'Assigned', value: wo.assigned },
    { label: 'In progress', value: wo.in_progress },
    { label: 'Awaiting parts', value: wo.awaiting_parts },
    { label: `Completed (${d.window_days} d)`, value: wo.completed_in_window },
  ]
  const trend = d.downtime_trend.map((p) => ({ label: formatDayLabel(p.day).date, value: p.downtime_minutes }))
  const health = [
    { name: 'Operational', value: k.operational, color: STATUS.good },
    { name: 'Under maintenance', value: k.under_maintenance, color: STATUS.warning, dark: true },
    { name: 'Out of service', value: k.out_of_service, color: STATUS.critical },
  ]

  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <StatCard compact icon={Wrench} tone="blue" label="Registered Equipment" value={formatNumber(k.equipment_total)}
          note={`${k.operational} operational · ${k.under_maintenance} under maintenance`} />
        <StatCard compact icon={ClipboardList} tone="amber" label="Open Work Orders" value={formatNumber(k.open_work_orders)} />
        <StatCard compact icon={TriangleAlert} tone="red" label="Overdue Tasks" value={formatNumber(k.overdue_tasks)}
          note={`${k.overdue_pm_tasks} preventive · ${k.overdue_work_orders} work orders`} />
        <StatCard compact icon={CalendarClock} tone="teal" label="Scheduled PM" value={formatNumber(k.scheduled_pm_next_30_days)} note="Due in the next 30 days" />
        <StatCard compact icon={Clock} tone="red" label="Equipment Downtime" value={formatDuration(k.downtime_minutes)} note={period} />
        <StatCard compact icon={CircleCheck} tone="green" label="Completion Rate"
          value={k.completion_rate_pct == null ? '—' : formatPercent(k.completion_rate_pct)}
          note={k.completion_sample ? `Of ${k.completion_sample} work orders raised · ${period.toLowerCase()}` : 'Insufficient data: no work orders raised'} />
        <StatCard compact icon={Wrench} tone="amber" label="Under Maintenance" value={formatNumber(k.under_maintenance)} />
        <StatCard compact icon={TriangleAlert} tone="red" label="Out of Service" value={formatNumber(k.out_of_service)} />
      </div>

      <h2 className="mt-6 mb-3 text-lg font-bold text-ink">Reliability · {period.toLowerCase()}</h2>
      <ReliabilityMetrics m={d.metrics} />

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ChartCard title="Equipment health" subtitle="Active equipment by status"
          table={{ columns: ['Status', 'Equipment'], rows: health.map((h) => [h.name, h.value]) }}>
          <SegmentedBar parts={health} label="Equipment health" />
        </ChartCard>
        <Card>
          <CardHeader title="Maintenance schedule" subtitle="Open preventive tasks" />
          <ul className="grid grid-cols-3 gap-2 text-center">
            {[
              ['Overdue', d.schedule.overdue, 'overdue', 'text-red-700'],
              ['Due today', d.schedule.due_today, 'due_today', 'text-amber-700'],
              ['Next 7 days', d.schedule.next_7_days, 'upcoming', 'text-ink'],
            ].map(([label, n, view, tone]) => (
              <li key={label as string}>
                <Link to={`/maintenance/preventive?view=${view}`} className="block rounded-xl bg-surface-muted px-2 py-3 hover:bg-sky-50">
                  <span className={`block text-2xl font-bold ${tone}`}>{n}</span>
                  <span className="text-xs text-ink-muted">{label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
        <ChartCard title="Work order overview" subtitle="Current pipeline"
          table={{ columns: ['Stage', 'Work orders'], rows: pipeline.map((p) => [p.label, p.value]) }}>
          <HBars items={pipeline} empty="No work orders yet." />
        </ChartCard>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <ChartCard title="Downtime trend" subtitle={`Minutes of stopped equipment per day · ${period.toLowerCase()}`}
          table={{ columns: ['Day', 'Downtime'], rows: d.downtime_trend.map((p) => [p.day, formatDuration(p.downtime_minutes)]) }}>
          <DailyColumns data={trend} format={(v) => (v >= 60 ? `${Math.round(v / 60)} h` : `${v}`)} />
        </ChartCard>
        <ChartCard title="Most frequently failing" subtitle={period}
          table={{ columns: ['Equipment', 'Breakdowns', 'Downtime'], rows: d.top_failing.map((t) => [t.code, t.breakdowns, formatDuration(t.downtime_minutes)]) }}>
          <HBars empty="No breakdowns in this period."
            items={d.top_failing.map((t) => ({ label: t.code, sub: t.name, value: t.breakdowns, note: `${formatDuration(t.downtime_minutes)} down` }))} />
        </ChartCard>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <ChartCard title="Common fault categories" subtitle={period}
          table={{ columns: ['Category', 'Breakdowns', 'Downtime'], rows: d.fault_categories.map((c) => [FAULT_LABELS[c.category], c.breakdowns, formatDuration(c.downtime_minutes)]) }}>
          <HBars empty="No breakdowns in this period."
            items={d.fault_categories.map((c) => ({ label: FAULT_LABELS[c.category], value: c.breakdowns, note: `${formatDuration(c.downtime_minutes)} down` }))} />
        </ChartCard>
        <Card>
          <CardHeader title="Recent activity" subtitle="Servicing, breakdowns, work orders and status changes" />
          {d.recent_activity.length === 0 ? <p className="text-sm text-ink-muted">No maintenance activity yet.</p> : (
            <ol className="divide-y divide-line text-sm" aria-label="Recent activity">
              {d.recent_activity.map((a) => (
                <li key={a.id} className="flex items-start justify-between gap-3 py-2">
                  <span className="min-w-0">
                    <Link to={`/maintenance/equipment`} className="font-mono text-xs font-semibold text-primary hover:underline">{a.equipment.code}</Link>
                    <span className="block text-ink">{a.summary}</span>
                  </span>
                  <span className="shrink-0 text-right text-xs text-ink-muted">
                    {formatDateTime(a.occurred_at)}{a.actor && <span className="block">{a.actor}</span>}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
      <details className="mt-4 rounded-2xl bg-white/70 px-4 py-3 text-sm text-ink">
        <summary className="cursor-pointer font-semibold">How these figures are calculated</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-muted">{d.definitions.map((x) => <li key={x}>{x}</li>)}</ul>
      </details>
    </>
  )
}
