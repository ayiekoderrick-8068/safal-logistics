import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { inputClass } from '../../../components/ui/buttons'
import { Card, CardHeader } from '../../../components/ui/Card'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { useDebounced } from '../../../hooks/useDebounced'
import { useApi } from '../../../hooks/useApi'
import { formatDuration, formatPercent } from '../../../lib/format'
import type { Bays } from '../types'
import { DataTable, Note } from '../ui'

export function BaysTab({ query }: { query: string }) {
  const [hoursInput, setHoursInput] = useState('12')
  const n = Number(hoursInput)
  const valid = Number.isInteger(n) && n >= 1 && n <= 24
  const hours = useDebounced(valid ? n : 12, 400)
  const { data, error, refetch } = useApi<Bays>(`/reports/bays?${query}&hours_per_day=${hours}`)
  if (error && !data) return <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
  if (!data) return <Card><LoadingState label="Analysing loading bays…" /></Card>
  const peaks = data.peak_hours.filter((p) => p.hour >= 5 && p.hour <= 22 || p.arrivals > 0)
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Loading Bay Efficiency"
          subtitle={`Reporting window: ${data.days} day(s) × ${data.hours_per_day} operating hours per day.`}
          action={
            <div>
              <label htmlFor="bay-hours" className="mb-1 block text-xs font-semibold text-ink">Operating hours / day</label>
              <input id="bay-hours" type="number" min={1} max={24} value={hoursInput} onChange={(e) => setHoursInput(e.target.value)}
                aria-invalid={!valid || undefined} className={`${inputClass} h-10 w-28 text-sm`} />
              {!valid && <p className="mt-1 text-xs text-red-600">Enter 1–24</p>}
            </div>
          } />
        <DataTable caption="Bay performance" empty="No active loading bays." rows={data.bays} minWidth={1000} cols={[
          { header: 'Bay', cell: (b) => <span className="font-semibold text-ink">{b.name}</span> },
          { header: 'Loads', cell: (b) => b.loads },
          { header: 'Within target', cell: (b) => b.completed_within_target },
          { header: 'Delayed', cell: (b) => <span className={b.delayed ? 'font-semibold text-red-600' : ''}>{b.delayed}</span> },
          { header: 'Avg waiting', cell: (b) => formatDuration(b.avg_waiting_minutes) },
          { header: 'Avg loading', cell: (b) => formatDuration(b.avg_loading_minutes) },
          { header: 'Avg turnaround', cell: (b) => `${formatDuration(b.avg_turnaround_minutes)} / ${formatDuration(b.target_minutes)}` },
          { header: 'Throughput', cell: (b) => `${b.throughput_per_day} loads/day` },
          { header: 'Occupied', cell: (b) => `${b.occupied_hours} h` },
          { header: 'Utilization', cell: (b) => b.utilization_pct == null ? <span className="text-ink-muted">No occupancy data</span> : (
            <span className="flex items-center gap-2">
              <span className="h-2 w-20 rounded-full bg-surface-muted" aria-hidden>
                <span className="block h-2 rounded-full bg-primary" style={{ width: `${b.utilization_pct}%` }} />
              </span>
              {formatPercent(b.utilization_pct)}
            </span>
          ) },
          { header: 'Peak hour', cell: (b) => b.peak_hour ?? '—' },
        ]} />
        <Note>
          Utilization = recorded occupied bay time (arrival → departure, or now if still on site, clipped to the period) ÷ available time
          (days × operating hours) × 100. Bays without recorded occupancy show no figure instead of 0%. Delayed = completed load over the bay’s target.
        </Note>
      </Card>
      <Card>
        <CardHeader title="Peak Loading Periods" subtitle="Truck arrivals by hour of day (local time), all selected bays." />
        {data.peak_hours.every((p) => p.arrivals === 0) ? <EmptyState title="No arrivals recorded in this period" /> : (
          <div className="h-56" role="img" aria-label="Truck arrivals by hour of day">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={peaks.map((p) => ({ ...p, label: `${String(p.hour).padStart(2, '0')}:00` }))} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="#e6eef3" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v) => [`${v} arrivals`, 'Arrivals']} />
                <Bar dataKey="arrivals" name="Arrivals" fill="#1d7fe0" radius={[4, 4, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
    </div>
  )
}
