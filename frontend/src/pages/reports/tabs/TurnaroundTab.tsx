import { useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardHeader } from '../../../components/ui/Card'
import { FilterSelect } from '../../../components/ui/FilterSelect'
import { StatCard } from '../../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { useApi } from '../../../hooks/useApi'
import { formatDayLabel, formatDuration, formatNumber, formatPercent } from '../../../lib/format'
import { CircleCheck, Hourglass, Timer, Truck } from 'lucide-react'
import type { GroupStats, Turnaround } from '../types'
import { DataTable, Note, type Col } from '../ui'

const COMPONENTS = [
  ['waiting', 'Arrival → loading start (waiting)'],
  ['loading', 'Loading duration'],
  ['post_load', 'Loading finish → departure'],
  ['turnaround', 'Yard turnaround (arrival → departure)'],
  ['delivery', 'Dispatch → delivery (not part of turnaround)'],
] as const

const groupCols: Col<GroupStats>[] = [
  { header: 'Name', cell: (r) => <span className="font-semibold text-ink">{r.label}</span> },
  { header: 'Loads', cell: (r) => r.loads },
  { header: 'Average', cell: (r) => formatDuration(r.avg_minutes) },
  { header: 'Median', cell: (r) => formatDuration(r.median_minutes) },
  { header: 'Min', cell: (r) => formatDuration(r.min_minutes) },
  { header: 'Max', cell: (r) => formatDuration(r.max_minutes) },
  { header: 'Avg loading', cell: (r) => formatDuration(r.avg_loading_minutes) },
  { header: 'Within target', cell: (r) => formatPercent(r.within_target_pct) },
]

export function TurnaroundTab({ query }: { query: string }) {
  const { data, error, refetch } = useApi<Turnaround>(`/reports/turnaround?${query}`)
  const [grain, setGrain] = useState<'daily' | 'weekly'>('daily')
  const [dim, setDim] = useState<'by_bay' | 'by_route' | 'by_truck'>('by_bay')
  if (error && !data) return <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
  if (!data) return <Card><LoadingState label="Calculating turnaround…" /></Card>
  const t = data.components.turnaround
  const series = data[grain].map((p) => ({ ...p, avg: p.avg_minutes == null ? null : +(p.avg_minutes / 60).toFixed(2),
    range: p.min_minutes == null ? null : [+(p.min_minutes / 60).toFixed(2), +(p.max_minutes! / 60).toFixed(2)] }))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={Timer} tone="blue" label="Average turnaround" value={formatDuration(t.avg)} note={`median ${formatDuration(t.median)}`} />
        <StatCard icon={Hourglass} tone="teal" label="Fastest / slowest" value={`${formatDuration(t.min)} – ${formatDuration(t.max)}`} note="completed loads" />
        <StatCard icon={CircleCheck} tone="green" label="Within target" value={formatPercent(data.within_target_pct)} note={`target ${formatDuration(data.target_minutes)} (bays may override)`} />
        <StatCard icon={Truck} tone="amber" label="Completed loads" value={formatNumber(data.completed_loads)} note={`${data.ongoing_loads} still on site (excluded)`} />
      </div>
      <Card>
        <CardHeader title="Turnaround Components" subtitle="Calculated from recorded timestamps; incomplete steps are excluded from each measure." />
        <DataTable caption="Duration statistics" empty="No completed loads match these filters."
          rows={COMPONENTS.map(([k, label]) => ({ label, ...data.components[k] }))}
          cols={[
            { header: 'Measure', cell: (r) => <span className="font-semibold text-ink">{r.label}</span> },
            { header: 'Records', cell: (r) => r.count },
            { header: 'Average', cell: (r) => formatDuration(r.avg) },
            { header: 'Median', cell: (r) => formatDuration(r.median) },
            { header: 'Minimum', cell: (r) => formatDuration(r.min) },
            { header: 'Maximum', cell: (r) => formatDuration(r.max) },
          ]} />
      </Card>
      <Card>
        <CardHeader title="Turnaround Trend vs Target"
          subtitle="Average yard turnaround (line) with the min–max range (shaded)."
          action={<FilterSelect label="Trend granularity" value={grain} onChange={(v) => setGrain(v as 'daily' | 'weekly')}
            options={[{ value: 'daily', label: 'By day' }, { value: 'weekly', label: 'By week (Mon)' }]} />} />
        {data.completed_loads === 0 ? <EmptyState title="No completed loads in this period" /> : (
          <div className="h-64" role="img" aria-label="Average turnaround hours per period against target">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={series} margin={{ top: 10, right: 12, left: -6, bottom: 0 }}>
                <CartesianGrid stroke="#e6eef3" vertical={false} />
                <XAxis dataKey="period" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={12}
                  tickFormatter={(v: string) => (grain === 'weekly' ? `wk ${formatDayLabel(v).date}` : formatDayLabel(v).date)} />
                <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={42} tickFormatter={(v: number) => `${v} h`}
                  domain={[0, (max: number) => Math.max(Math.ceil(data.target_minutes / 60 + 1), Math.ceil(max))]} />
                <Tooltip formatter={(v, n) => (Array.isArray(v) ? [`${v[0]}–${v[1]} h`, n] : v == null ? ['No loads', n] : [`${v} h`, n])} />
                <Area dataKey="range" name="Min–max" fill="#cfe6fb" stroke="none" connectNulls isAnimationActive={false} />
                <ReferenceLine y={data.target_minutes / 60} stroke="#0e8fa8" strokeDasharray="6 4"
                  label={{ value: `Target ${(data.target_minutes / 60).toFixed(1)} h`, position: 'insideTopRight', fontSize: 11, fill: '#0e8fa8' }} />
                <Line dataKey="avg" name="Average" stroke="#1d6fd8" strokeWidth={2.5} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
      <Card>
        <CardHeader title="Turnaround Performance by Dimension" subtitle="Slowest average first."
          action={<FilterSelect label="Group turnaround by" value={dim} onChange={(v) => setDim(v as typeof dim)}
            options={[{ value: 'by_bay', label: 'By loading bay' }, { value: 'by_route', label: 'By route' }, { value: 'by_truck', label: 'By truck' }]} />} />
        <DataTable cols={groupCols} rows={data[dim]} empty="No completed loads match these filters." caption="Turnaround by dimension" />
        <Note>Loads that were never dispatched appear as “Not dispatched” in the route view.</Note>
      </Card>
    </div>
  )
}
