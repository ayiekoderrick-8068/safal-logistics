import { CircleCheck, Clock, Send, TriangleAlert } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardHeader } from '../../../components/ui/Card'
import { StatCard } from '../../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { useApi } from '../../../hooks/useApi'
import { formatDuration, formatNumber, formatPercent } from '../../../lib/format'
import type { DispatchPerf } from '../types'
import { DataTable, Note } from '../ui'

const BUCKET_COLORS = ['#16a34a', '#65c466', '#f8c95a', '#f59e0b', '#f97316', '#ef4444']

export function DispatchTab({ query }: { query: string }) {
  const { data, error, refetch } = useApi<DispatchPerf>(`/reports/dispatch?${query}`)
  if (error && !data) return <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
  if (!data) return <Card><LoadingState label="Analysing deliveries…" /></Card>
  const routes = data.by_route.map((r) => ({
    ...r, planned: r.avg_planned_minutes == null ? null : +(r.avg_planned_minutes / 60).toFixed(2),
    actual: r.avg_actual_minutes == null ? null : +(r.avg_actual_minutes / 60).toFixed(2),
  }))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={Send} tone="blue" label="Dispatched" value={formatNumber(data.dispatched)}
          note={`${data.dispatched_trucks} trucks · ${data.scheduled_loads} loads scheduled`} />
        <StatCard icon={CircleCheck} tone="green" label="Completed deliveries" value={formatNumber(data.completed)}
          note={`${data.on_time} on time · ${data.late} late`} />
        <StatCard icon={TriangleAlert} tone="amber" label="On-time rate" value={formatPercent(data.on_time_pct)}
          note={`${data.pending} pending excluded`} />
        <StatCard icon={Clock} tone="teal" label="Avg delivery duration" value={formatDuration(data.avg_delivery_minutes)}
          note={`planned ${formatDuration(data.avg_planned_minutes)}`} />
      </div>
      {data.dispatched === 0 ? <Card><EmptyState title="No dispatches match these filters" /></Card> : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <Card className="xl:col-span-5">
            <CardHeader title="Delivery Delay Distribution" subtitle="Completed deliveries by arrival vs expected time." />
            <div className="h-64" role="img" aria-label="Completed deliveries by lateness band">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.delay_distribution} layout="vertical" margin={{ top: 4, right: 16, left: 30, bottom: 0 }}>
                  <CartesianGrid stroke="#e6eef3" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="bucket" width={110} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip formatter={(v) => [`${v} deliveries`, 'Deliveries']} />
                  <Bar dataKey="count" name="Deliveries" radius={[0, 4, 4, 0]} isAnimationActive={false}
                    shape={(props: unknown) => {
                      const p = props as { x: number; y: number; width: number; height: number; index: number }
                      return <rect x={p.x} y={p.y} width={p.width} height={p.height} rx={4} fill={BUCKET_COLORS[p.index]} />
                    }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <Note>On time = delivered at or before the deadline (expected arrival + {data.grace_minutes} min grace).</Note>
          </Card>
          <Card className="xl:col-span-7">
            <CardHeader title="Planned vs Actual Delivery Time" subtitle="Average per route, completed deliveries (hours)." />
            <div className="h-64" role="img" aria-label="Planned and actual average delivery hours by route">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={routes} margin={{ top: 4, right: 4, left: -10, bottom: 0 }}>
                  <CartesianGrid stroke="#e6eef3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} interval={0} />
                  <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v} h`} />
                  <Tooltip formatter={(v, n) => [v == null ? 'No deliveries' : `${v} h`, n]} />
                  <Legend verticalAlign="top" height={28} iconSize={10} wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="planned" name="Planned" fill="#9ed3f5" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="actual" name="Actual" fill="#1d6fd8" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>
      )}
      <Card>
        <CardHeader title="Performance by Route" />
        <DataTable caption="Route performance" empty="No dispatches match these filters." rows={data.by_route} minWidth={860} cols={[
          { header: 'Route', cell: (r) => <span className="font-semibold text-ink">{r.label}</span> },
          { header: 'Dispatches', cell: (r) => r.dispatches },
          { header: 'Completed', cell: (r) => r.completed },
          { header: 'Pending', cell: (r) => r.pending },
          { header: 'On time', cell: (r) => formatPercent(r.on_time_pct) },
          { header: 'Avg planned', cell: (r) => formatDuration(r.avg_planned_minutes) },
          { header: 'Avg actual', cell: (r) => formatDuration(r.avg_actual_minutes) },
          { header: 'Avg vs expected', cell: (r) => r.avg_lateness_minutes == null ? '—'
            : r.avg_lateness_minutes > 0 ? <span className="font-semibold text-red-600">+{r.avg_lateness_minutes} min</span>
            : <span className="text-emerald-700">{Math.abs(r.avg_lateness_minutes)} min early</span> },
        ]} />
        <Note>Pending deliveries (still in transit) are reported separately and never counted as on time or late.</Note>
      </Card>
    </div>
  )
}
