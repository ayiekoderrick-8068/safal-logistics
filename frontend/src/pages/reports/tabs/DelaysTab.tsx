import { CircleCheck, Clock, Repeat, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardHeader } from '../../../components/ui/Card'
import { FilterSelect } from '../../../components/ui/FilterSelect'
import { StatCard } from '../../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { useApi } from '../../../hooks/useApi'
import { DELAY_CAUSE_LABELS, formatDateTime, formatDayLabel, formatDuration, formatNumber } from '../../../lib/format'
import { StatusDonut } from '../../overview/charts'
import type { DelayGroup, Delays } from '../types'
import { DataTable, Note, type Col } from '../ui'

const CAUSE_COLORS: Record<string, string> = {
  loading_congestion: '#1d6fd8', vehicle_breakdown: '#ef4444', documentation: '#f59e0b',
  equipment_breakdown: '#8b5cf6', truck_unavailability: '#0ea5a4', traffic: '#64748b', other: '#22b8d6',
}
const groupCols: Col<DelayGroup>[] = [
  { header: 'Name', cell: (r) => <span className="font-semibold text-ink">{r.label ?? '—'}</span> },
  { header: 'Incidents', cell: (r) => r.count },
  { header: 'Open', cell: (r) => r.open },
  { header: 'Reported impact', cell: (r) => formatDuration(r.impact_minutes) },
]

export function DelaysTab({ query }: { query: string }) {
  const { data, error, refetch } = useApi<Delays>(`/reports/delays?${query}`)
  const [grain, setGrain] = useState<'daily' | 'weekly'>('daily')
  const [dim, setDim] = useState<'by_bay' | 'by_route' | 'by_truck'>('by_bay')
  if (error && !data) return <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
  if (!data) return <Card><LoadingState label="Analysing delays…" /></Card>
  const causes = data.by_cause.map((c) => ({ ...c, label: DELAY_CAUSE_LABELS[c.cause] ?? c.cause }))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={TriangleAlert} tone="red" label="Delay incidents" value={formatNumber(data.total)} note={`${data.open} open · ${data.resolved} resolved`} />
        <StatCard icon={Clock} tone="amber" label="Reported impact" value={formatDuration(data.impact_minutes)} note={`avg ${formatDuration(data.avg_impact_minutes)} per incident`} />
        <StatCard icon={CircleCheck} tone="green" label="Avg resolution time" value={formatDuration(data.avg_resolution_minutes)} note="started → resolved" />
        <StatCard icon={Repeat} tone="blue" label="Repeat patterns" value={formatNumber(data.repeat_patterns.length)} note="same truck & category, 2+ times" />
      </div>
      {data.total === 0 ? <Card><EmptyState title="No delay incidents match these filters">Delays recorded on the Delay Reports page appear here.</EmptyState></Card> : (
        <>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-7">
              <CardHeader title="Delays by Category" subtitle="Number of incidents and reported impact (minutes)." />
              <div className="h-64" role="img" aria-label="Delay incidents and impact minutes by category">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={causes} margin={{ top: 4, right: 4, left: -10, bottom: 0 }}>
                    <CartesianGrid stroke="#e6eef3" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} interval={0} />
                    <YAxis yAxisId="n" allowDecimals={false} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis yAxisId="m" orientation="right" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}m`} />
                    <Tooltip formatter={(v, n) => (n === 'Impact (min)' ? [`${v} min`, n] : [v, n])} />
                    <Legend verticalAlign="top" height={28} iconSize={10} wrapperStyle={{ fontSize: 12 }} />
                    <Bar yAxisId="n" dataKey="count" name="Incidents" fill="#1d6fd8" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                    <Bar yAxisId="m" dataKey="impact_minutes" name="Impact (min)" fill="#f8b630" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card className="xl:col-span-5">
              <CardHeader title="Delay Distribution" subtitle="Share of incidents by category." />
              <StatusDonut rows={data.by_cause.map((c) => ({ status: c.cause, count: c.count }))} centerLabel="Delays"
                colors={CAUSE_COLORS} labels={DELAY_CAUSE_LABELS} />
            </Card>
          </div>
          <Card>
            <CardHeader title="Delay Trend" subtitle="Incidents started per period."
              action={<FilterSelect label="Delay trend granularity" value={grain} onChange={(v) => setGrain(v as 'daily' | 'weekly')}
                options={[{ value: 'daily', label: 'By day' }, { value: 'weekly', label: 'By week (Mon)' }]} />} />
            <div className="h-56" role="img" aria-label="Delay incidents per period">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data[grain]} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                  <CartesianGrid stroke="#e6eef3" vertical={false} />
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={12}
                    tickFormatter={(v: string) => formatDayLabel(v).date} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip formatter={(v, n) => [n === 'Impact' ? `${v} min` : v, n]} />
                  <Line dataKey="count" name="Incidents" stroke="#ef4444" strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-7">
              <CardHeader title="Most Affected" subtitle="Each incident counted once."
                action={<FilterSelect label="Group delays by" value={dim} onChange={(v) => setDim(v as typeof dim)}
                  options={[{ value: 'by_bay', label: 'Loading bays' }, { value: 'by_route', label: 'Routes' }, { value: 'by_truck', label: 'Vehicles' }]} />} />
              <DataTable cols={groupCols} rows={data[dim]} empty="No incidents linked to this dimension." caption="Delays by dimension" minWidth={420} />
            </Card>
            <Card className="xl:col-span-5">
              <CardHeader title="Top Recurring Causes" subtitle="Repeat patterns and average resolution by category." />
              <DataTable minWidth={360} caption="Recurring causes" empty="No recurring causes."
                rows={data.by_cause} cols={[
                  { header: 'Category', cell: (r) => DELAY_CAUSE_LABELS[r.cause] ?? r.cause },
                  { header: 'Incidents', cell: (r) => r.count },
                  { header: 'Avg resolution', cell: (r) => formatDuration(r.avg_resolution_minutes) },
                ]} />
              {data.repeat_patterns.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm">
                  {data.repeat_patterns.map((p) => (
                    <li key={`${p.truck}-${p.cause}`} className="rounded-lg bg-amber-50 px-3 py-1.5 text-amber-900">
                      <strong>{p.truck}</strong> – {DELAY_CAUSE_LABELS[p.cause]} ×{p.count}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
          <Card>
            <CardHeader title="Recent Operational Incidents" />
            <DataTable caption="Recent incidents" empty="No incidents." rows={data.recent} minWidth={900} cols={[
              { header: 'Started', cell: (r) => formatDateTime(r.started_at) },
              { header: 'Truck', cell: (r) => <span className="font-semibold text-ink">{r.truck ?? '—'}</span> },
              { header: 'Operation', cell: (r) => r.load_ref ? `${r.load_ref} · ${r.route ?? ''}` : `Loading · ${r.bay ?? ''}` },
              { header: 'Category', cell: (r) => DELAY_CAUSE_LABELS[r.cause] ?? r.cause },
              { header: 'Duration', cell: (r) => `${formatDuration(r.duration_minutes)}${r.ongoing ? ' (ongoing)' : ''}` },
              { header: 'Impact', cell: (r) => `${r.impact_minutes} min` },
              { header: 'Status', cell: (r) => <StatusBadge status={r.status} /> },
            ]} />
            <Note>Duration = resolved − started (or now for ongoing incidents). Impact = delay minutes reported on the incident.</Note>
          </Card>
        </>
      )}
    </div>
  )
}
