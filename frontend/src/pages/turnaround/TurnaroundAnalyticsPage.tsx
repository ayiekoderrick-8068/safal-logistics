import { CalendarDays, CircleCheck, Target, Timer, TriangleAlert, Truck, Warehouse } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardHeader } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SampleDataBanner } from '../../components/ui/SampleDataBanner'
import { StatCard } from '../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useApi } from '../../hooks/useApi'
import {
  DELAY_CAUSE_LABELS,
  describeChange,
  formatDate,
  formatDayLabel,
  formatDuration,
  formatNumber,
  formatPercent,
} from '../../lib/format'
import type { TurnaroundAnalytics } from '../../lib/types'
import { StatusDonut } from '../overview/charts'
import { PERIODS, periodRange, type PeriodValue } from '../overview/period'

const CAUSE_COLORS: Record<string, string> = {
  loading_congestion: '#1d6fd8', vehicle_breakdown: '#ef4444', documentation: '#f59e0b',
  equipment_breakdown: '#8b5cf6', truck_unavailability: '#0ea5a4', traffic: '#64748b', other: '#22b8d6',
}
const BAY_STATUS = { within: 'Within Target', above: 'Above Target', no_data: 'No loads' }

export function TurnaroundAnalyticsPage() {
  const [period, setPeriod] = useState<PeriodValue>('7')
  const { start, end } = periodRange(Number(period))
  const { data, error, loading, refetch } = useApi<TurnaroundAnalytics>(`/analytics/turnaround?start=${start}&end=${end}`)

  return (
    <>
      <PageHeader
        title="Turnaround-Time Analytics"
        description="Measure loading turnaround, identify delay causes and improve operational efficiency."
        actions={
          <label className="relative flex items-center">
            <span className="sr-only">Analysis period</span>
            <CalendarDays className="pointer-events-none absolute left-3.5 size-5 text-primary" aria-hidden />
            <select value={period} onChange={(e) => setPeriod(e.target.value as PeriodValue)}
              className="h-11 appearance-none rounded-xl border border-white bg-white pr-10 pl-11 font-semibold text-ink shadow-sm">
              {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
            <span className="pointer-events-none absolute right-3.5 text-ink" aria-hidden>▾</span>
          </label>
        }
      />
      {error && !data ? <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
        : !data ? <Card><LoadingState label="Calculating turnaround…" /></Card>
        : <Content data={data} stale={loading} />}
    </>
  )
}

function Content({ data, stale }: { data: TurnaroundAnalytics; stale: boolean }) {
  const k = data.kpis
  const trend = data.trend.map((p) => ({
    day: p.day, hours: p.avg_turnaround_minutes == null ? null : +(p.avg_turnaround_minutes / 60).toFixed(1),
  }))
  const targetH = data.target_minutes / 60
  const hasTrend = trend.some((t) => t.hours != null)
  const totalDelays = data.causes.reduce((s, c) => s + c.count, 0)

  return (
    <div className={stale ? 'opacity-70' : undefined} aria-busy={stale}>
      {data.sample_data && <SampleDataBanner />}
      <p className="mb-3 text-sm text-ink/70">
        {formatDate(data.period_start)} – {formatDate(data.period_end)} · compared with {formatDate(data.previous_period_start)} – {formatDate(data.previous_period_end)}
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard icon={Timer} tone="blue" label="Avg Turnaround Time" value={formatDuration(k.avg_turnaround_minutes.current)}
          trend={describeChange(k.avg_turnaround_minutes.current, k.avg_turnaround_minutes.previous, 'pct', false)}
          note={k.avg_turnaround_minutes.current == null ? 'No completed loads' : 'vs prior period'} />
        <StatCard icon={Target} tone="teal" label="Target Turnaround" value={formatDuration(data.target_minutes)} note="Global target (bays may override)" />
        <StatCard icon={CircleCheck} tone="green" label="Within Target" value={formatPercent(k.within_target_pct.current)}
          trend={describeChange(k.within_target_pct.current, k.within_target_pct.previous, 'pp', true)} />
        <StatCard icon={TriangleAlert} tone="red" label="Delay Incidents" value={formatNumber(k.delay_incidents.current)}
          trend={describeChange(k.delay_incidents.current, k.delay_incidents.previous, 'abs', false)} />
        <StatCard icon={Truck} tone="blue" label="Loads Processed" value={formatNumber(k.loads_processed.current)}
          trend={describeChange(k.loads_processed.current, k.loads_processed.previous, 'pct', true)} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader title="Turnaround Time Trend" subtitle="Average time from truck arrival to departure." />
          {!hasTrend ? <EmptyState title="No completed loads in this period" /> : (
            <div className="h-64" role="img" aria-label={`Daily average turnaround in hours against a ${targetH.toFixed(1)} hour target`}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={trend} margin={{ top: 24, right: 12, left: -8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="taFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#1d6fd8" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#1d6fd8" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#e6eef3" vertical={false} />
                  <XAxis dataKey="day" tick={{ fontSize: 12 }} axisLine={false} tickLine={false}
                    tickFormatter={(v: string) => `${formatDayLabel(v).weekday} ${formatDayLabel(v).date}`} />
                  <YAxis tick={{ fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v} h`}
                    domain={[0, (max: number) => Math.max(Math.ceil(targetH + 1), Math.ceil(max + 0.5))]} />
                  <Tooltip formatter={(v) => (v == null ? 'No loads' : `${v} h`)} labelFormatter={(v) => formatDate(String(v))} />
                  <ReferenceLine y={targetH} stroke="#0e8fa8" strokeDasharray="6 4"
                    label={{ value: `Target (${targetH.toFixed(1)} h)`, position: 'insideTopRight', fontSize: 11, fill: '#0e8fa8' }} />
                  <Area type="monotone" dataKey="hours" stroke="none" fill="url(#taFill)" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="hours" name="Actual turnaround" stroke="#1d6fd8" strokeWidth={2.5}
                    dot={{ r: 4, fill: '#fff', strokeWidth: 2 }} connectNulls isAnimationActive={false}>
                    <LabelList dataKey="hours" position="top" fontSize={11} formatter={(v) => (v == null ? '' : `${v} h`)} />
                  </Line>
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card className="xl:col-span-5">
          <CardHeader title="Delay Causes" subtitle="Incidents that started in this period." />
          {totalDelays === 0 ? <EmptyState title="No delays recorded" /> : (
            <StatusDonut rows={data.causes.map((c) => ({ status: c.cause, count: c.count }))} centerLabel="Delays"
              colors={CAUSE_COLORS} labels={DELAY_CAUSE_LABELS} />
          )}
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-12">
          <CardHeader title="Loading Turnaround by Bay" subtitle="Average turnaround, loading time and utilisation per bay." />
          {data.bays.length === 0 ? <EmptyState title="No loading bays" /> : (
            <div className="-mx-2 overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm whitespace-nowrap">
                <thead>
                  <tr className="bg-surface-muted text-ink">
                    {['Loading Bay', 'Loads', 'Avg Turnaround', 'Target', 'Utilization', 'Status'].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.bays.map((b) => (
                    <tr key={b.bay.id} className="border-b border-line last:border-0">
                      <td className="px-3 py-2.5 font-semibold text-ink">
                        <span className="flex items-center gap-2"><Warehouse className="size-4.5 text-primary" aria-hidden />{b.bay.name}</span>
                      </td>
                      <td className="px-3 py-2.5">{b.loads}</td>
                      <td className="px-3 py-2.5">
                        {formatDuration(b.avg_turnaround_minutes)}
                        {b.avg_loading_minutes != null && <span className="block text-xs text-ink-muted">loading {formatDuration(b.avg_loading_minutes)}</span>}
                      </td>
                      <td className="px-3 py-2.5">≤ {formatDuration(b.bay.effective_target_minutes)}</td>
                      <td className="px-3 py-2.5">{formatPercent(b.utilization_pct)}</td>
                      <td className="px-3 py-2.5">
                        <StatusBadge status={b.status === 'within' ? 'completed' : b.status === 'above' ? 'expiring' : 'not_required'}
                          label={BAY_STATUS[b.status]} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card className="xl:col-span-12">
          <CardHeader title="Recent Delay Incidents" subtitle="Latest loading or dispatch delays and their causes."
            action={<Link to="/delays" className="rounded-lg border border-line px-3 py-1 text-sm font-semibold text-ink hover:bg-surface-muted">View All</Link>} />
          {data.recent_incidents.length === 0 ? <EmptyState title="No delays in this period" /> : (
            <div className="-mx-2 overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm whitespace-nowrap">
                <thead>
                  <tr className="bg-surface-muted text-ink">
                    {['Truck No.', 'Operation', 'Duration', 'Cause', 'Status'].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.recent_incidents.map((i) => (
                    <tr key={i.id} className="border-b border-line last:border-0">
                      <td className="px-3 py-2.5 font-semibold text-ink">{i.truck?.label ?? '—'}</td>
                      <td className="max-w-48 truncate px-3 py-2.5" title={i.operation}>{i.operation}</td>
                      <td className="px-3 py-2.5 font-semibold text-red-600">+{formatDuration(i.duration_minutes)}</td>
                      <td className="px-3 py-2.5">{DELAY_CAUSE_LABELS[i.cause]}</td>
                      <td className="px-3 py-2.5"><StatusBadge status={i.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
