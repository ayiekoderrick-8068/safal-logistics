import {
  CalendarDays,
  CircleCheck,
  Gauge,
  RefreshCw,
  Timer,
  TriangleAlert,
  Truck,
} from 'lucide-react'
import { Link } from 'react-router'
import { useState } from 'react'
import { Card, CardHeader } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SampleDataBanner } from '../../components/ui/SampleDataBanner'
import { StatCard } from '../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useApi } from '../../hooks/useApi'
import {
  describeChange,
  formatDate,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
  humanize,
} from '../../lib/format'
import type { DashboardOverview } from '../../lib/types'
import { statusColor } from '../../lib/statusColors'
import { PerformanceTrendChart, StatusDonut } from './charts'
import { PERIODS, periodRange, type PeriodValue } from './period'

export function OverviewPage() {
  const [period, setPeriod] = useState<PeriodValue>('7')
  const { start, end } = periodRange(Number(period))
  const { data, error, loading, refetch } = useApi<DashboardOverview>(
    `/dashboard/overview?start=${start}&end=${end}`,
  )

  return (
    <>
      <PageHeader
        title="Operations Overview"
        description="Loading, dispatch and fleet performance across LogiTrack operations."
        actions={
          <>
            <label className="relative flex items-center">
              <span className="sr-only">Reporting period</span>
              <CalendarDays className="pointer-events-none absolute left-3.5 size-5 text-primary" aria-hidden />
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value as PeriodValue)}
                className="h-11 appearance-none rounded-xl border border-white bg-white pr-10 pl-11 font-semibold text-ink shadow-sm"
              >
                {PERIODS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-3.5 text-ink" aria-hidden>▾</span>
            </label>
            <button
              type="button"
              onClick={refetch}
              disabled={loading}
              className="flex h-11 items-center gap-2 rounded-xl bg-primary px-5 font-semibold text-white shadow-md hover:bg-primary-hover disabled:opacity-70"
            >
              <RefreshCw className={loading ? 'size-4 animate-spin' : 'size-4'} aria-hidden /> Refresh
            </button>
          </>
        }
      />

      {error && !data ? (
        <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
      ) : !data ? (
        <Card><LoadingState label="Loading operations data…" /></Card>
      ) : (
        <OverviewContent data={data} stale={loading} />
      )}
    </>
  )
}

function OverviewContent({ data, stale }: { data: DashboardOverview; stale: boolean }) {
  const k = data.kpis
  const noActivity = k.loads_processed.current === 0 && data.recent_dispatches.length === 0

  return (
    <div className={stale ? 'opacity-70 transition-opacity' : 'transition-opacity'} aria-busy={stale}>
      {data.sample_data && <SampleDataBanner />}
      <p className="mb-3 text-sm text-ink/70">
        {formatDate(data.period_start)} – {formatDate(data.period_end)} · compared with{' '}
        {formatDate(data.previous_period_start)} – {formatDate(data.previous_period_end)} (arrows show
        change vs that period)
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard icon={Truck} tone="blue" label="Loads Processed"
          value={formatNumber(k.loads_processed.current)}
          trend={describeChange(k.loads_processed.current, k.loads_processed.previous, 'pct', true)} />
        <StatCard icon={Timer} tone="teal" label="Avg Turnaround Time"
          value={formatDuration(k.avg_turnaround_minutes.current)}
          trend={describeChange(k.avg_turnaround_minutes.current, k.avg_turnaround_minutes.previous, 'pct', false)}
          note={k.avg_turnaround_minutes.current == null ? 'No completed loads' : `target ${formatDuration(data.turnaround_target_minutes)}`} />
        <StatCard icon={CircleCheck} tone="green" label="On-Time Delivery"
          value={formatPercent(k.on_time_delivery_pct.current)}
          trend={describeChange(k.on_time_delivery_pct.current, k.on_time_delivery_pct.previous, 'pp', true)}
          note={k.on_time_delivery_pct.current == null ? 'No deliveries' : undefined} />
        <StatCard icon={TriangleAlert} tone="red" label="Delay Incidents"
          value={formatNumber(k.delay_incidents.current)}
          trend={describeChange(k.delay_incidents.current, k.delay_incidents.previous, 'abs', false)}
          note={`${data.open_delay_incidents} open`} />
        <StatCard icon={Gauge} tone="blue" label="Bay Utilization"
          value={formatPercent(k.bay_utilization_pct.current)}
          trend={describeChange(k.bay_utilization_pct.current, k.bay_utilization_pct.previous, 'pp', true)}
          note={k.bay_utilization_pct.current == null ? 'No active bays' : undefined} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader
            title="Operational Performance Trend"
            subtitle={`${formatPercent(k.within_target_pct.current)} of loads within turnaround target`}
          />
          {noActivity ? (
            <EmptyState title="No loading activity recorded for this period">
              Completed loading schedules will appear here once trucks are recorded departing a bay.
            </EmptyState>
          ) : (
            <PerformanceTrendChart trend={data.trend} targetMinutes={data.turnaround_target_minutes} />
          )}
        </Card>

        <Card className="xl:col-span-5">
          <CardHeader
            title="Dispatches by Status"
            subtitle={`${data.delayed_dispatches} flagged as delayed this period`}
          />
          {data.dispatch_status.length === 0 ? (
            <EmptyState title="No dispatches in this period" />
          ) : (
            <StatusDonut rows={data.dispatch_status} centerLabel="Dispatches" />
          )}
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader title="Recent Dispatches" subtitle="Latest trucks dispatched from the depot." />
          {data.recent_dispatches.length === 0 ? (
            <EmptyState title="No dispatches recorded yet" />
          ) : (
            <div className="-mx-2 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm whitespace-nowrap">
                <thead>
                  <tr className="bg-surface-muted text-ink">
                    {['Load ID', 'Truck No.', 'Route', 'Dispatched', 'Arrival', 'Status'].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.recent_dispatches.map((d) => (
                    <tr key={d.id} className="border-b border-line last:border-0">
                      <td className="px-3 py-2.5">{d.load_ref}</td>
                      <td className="px-3 py-2.5 font-semibold">{d.truck_registration}</td>
                      <td className="px-3 py-2.5">{d.route}</td>
                      <td className="px-3 py-2.5">{formatDateTime(d.dispatched_at)}</td>
                      <td className="px-3 py-2.5">
                        {d.actual_arrival_at
                          ? formatDateTime(d.actual_arrival_at)
                          : <span className="text-ink-muted">ETA {formatDateTime(d.expected_arrival_at)}</span>}
                      </td>
                      <td className="px-3 py-2.5">
                        {d.is_delayed && d.status !== 'delivered'
                          ? <StatusBadge status="delayed" />
                          : <StatusBadge status={d.status} label={d.is_delayed ? 'Delivered late' : undefined} />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="flex flex-col gap-4 xl:col-span-5">
          <Card>
            <CardHeader title="Fleet Status" subtitle={`${data.fleet_total} registered trucks`} />
            {data.fleet_total === 0 ? (
              <EmptyState title="No trucks registered yet" />
            ) : (
              <FleetStatus rows={data.fleet_status} total={data.fleet_total} />
            )}
          </Card>
          <Card>
            <CardHeader
              title="Compliance Alerts"
              subtitle="Documents expired or expiring within 30 days."
              action={<Link to="/compliance" className="rounded-lg border border-line px-3 py-1 text-sm font-semibold text-ink hover:bg-surface-muted">View all</Link>}
            />
            {data.expiry_alerts.length === 0 ? (
              <EmptyState title="No upcoming expiries" />
            ) : (
              <ul className="divide-y divide-line">
                {data.expiry_alerts.map((a) => (
                  <li key={`${a.truck_registration}-${a.doc_type}`} className="flex items-center gap-3 py-2.5 text-sm">
                    <CalendarDays className="size-4.5 shrink-0 text-primary" aria-hidden />
                    <span className="font-semibold text-ink">
                      {a.truck_registration} <span className="font-normal">– {humanize(a.doc_type)}</span>
                    </span>
                    <span className="ml-auto text-ink-muted">{formatDate(a.expires_on)}</span>
                    <span
                      className={
                        a.days_remaining < 0
                          ? 'w-24 rounded-lg bg-red-100 px-2 py-0.5 text-center text-xs font-semibold text-red-700'
                          : 'w-24 rounded-lg bg-amber-100 px-2 py-0.5 text-center text-xs font-semibold text-amber-800'
                      }
                    >
                      {a.days_remaining < 0
                        ? `Overdue ${-a.days_remaining}d`
                        : a.days_remaining === 0 ? 'Today' : `${a.days_remaining} days`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function FleetStatus({ rows, total }: { rows: { status: string; count: number }[]; total: number }) {
  return (
    <>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-muted" aria-hidden>
        {rows.map((r) => (
          <div key={r.status} style={{ width: `${(r.count / total) * 100}%`, background: statusColor(r.status) }} />
        ))}
      </div>
      <ul className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {rows.map((r) => (
          <li key={r.status} className="flex items-center gap-2">
            <span className="size-3 rounded-full" style={{ background: statusColor(r.status) }} aria-hidden />
            {humanize(r.status)}
            <span className="ml-auto font-semibold">{r.count}</span>
          </li>
        ))}
      </ul>
    </>
  )
}
