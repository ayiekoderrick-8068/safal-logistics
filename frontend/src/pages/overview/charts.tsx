import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatDayLabel, humanize } from '../../lib/format'
import { statusColor } from '../../lib/statusColors'
import type { DashboardOverview } from '../../lib/types'

const C = {
  turnaround: '#1d6fd8',
  onTime: '#22a447',
  loads: '#9ed3f5',
  target: '#0e8fa8',
}

function DayTick({ x, y, payload }: { x?: number; y?: number; payload?: { value: string } }) {
  if (!payload) return null
  const { weekday, date } = formatDayLabel(payload.value)
  return (
    <text x={x} y={y} textAnchor="middle" fill="#0f2b3d" fontSize={12}>
      <tspan x={x} dy={12}>{weekday}</tspan>
      <tspan x={x} dy={14}>{date}</tspan>
    </text>
  )
}

export function PerformanceTrendChart({
  trend,
  targetMinutes,
}: {
  trend: DashboardOverview['trend']
  targetMinutes: number
}) {
  const data = trend.map((p) => ({
    day: p.day,
    loads: p.loads_processed,
    turnaround: p.avg_turnaround_minutes == null ? null : +(p.avg_turnaround_minutes / 60).toFixed(2),
    onTime: p.on_time_delivery_pct,
  }))
  const dense = data.length > 14

  return (
    <div className="h-72 w-full" role="img" aria-label="Daily loads processed, average turnaround hours and on-time delivery percentage">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 4, left: -6, bottom: 8 }}>
          <CartesianGrid stroke="#e6eef3" vertical={false} />
          <XAxis
            dataKey="day"
            tick={dense ? { fontSize: 11 } : <DayTick />}
            tickFormatter={dense ? (v: string) => formatDayLabel(v).date : undefined}
            height={dense ? 24 : 36}
            interval={dense ? 'preserveStartEnd' : 0}
            axisLine={false}
            tickLine={false}
          />
          <YAxis yAxisId="h" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} width={40}
            domain={[0, (max: number) => Math.max(4, Math.ceil(max))]} tickCount={5} allowDecimals={false}
            tickFormatter={(v: number) => `${v} h`} />
          <YAxis yAxisId="pct" orientation="right" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]}
            tick={{ fontSize: 12 }} tickFormatter={(v: number) => `${v}%`} axisLine={false} tickLine={false} width={44} />
          <YAxis yAxisId="loads" hide allowDecimals={false} domain={[0, (max: number) => Math.ceil(max * 1.25)]} />
          <Tooltip
            labelFormatter={(v) => `${formatDayLabel(String(v)).weekday} ${formatDayLabel(String(v)).date}`}
            formatter={(value, name) => {
              if (value == null) return ['No data', name]
              if (name === 'Turnaround (h)') return [`${value} h`, name]
              if (name === 'On-time delivery') return [`${value}%`, name]
              return [value, name]
            }}
          />
          <Legend verticalAlign="top" height={30} iconSize={10} wrapperStyle={{ fontSize: 13 }} />
          <Bar yAxisId="loads" dataKey="loads" name="Loads processed" fill={C.loads} radius={[6, 6, 0, 0]}
            maxBarSize={44} isAnimationActive={false} />
          <ReferenceLine yAxisId="h" y={targetMinutes / 60} stroke={C.target} strokeDasharray="6 4"
            label={{ value: `Target ${(targetMinutes / 60).toFixed(1)} h`, position: 'insideBottomRight', fontSize: 11, fill: C.target }} />
          <Line yAxisId="h" type="monotone" dataKey="turnaround" name="Turnaround (h)" stroke={C.turnaround}
            strokeWidth={2.5} dot={{ r: 4, fill: '#fff', strokeWidth: 2 }} connectNulls isAnimationActive={false} />
          <Line yAxisId="pct" type="monotone" dataKey="onTime" name="On-time delivery" stroke={C.onTime}
            strokeWidth={2.5} dot={{ r: 4, fill: '#fff', strokeWidth: 2 }} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function StatusDonut({
  rows,
  centerLabel,
}: {
  rows: { status: string; count: number }[]
  centerLabel: string
}) {
  const total = rows.reduce((s, r) => s + r.count, 0)
  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row">
      <div className="relative size-48 shrink-0" role="img" aria-label={`${total} ${centerLabel} by status`}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={rows} dataKey="count" nameKey="status" innerRadius="62%" outerRadius="100%"
              startAngle={90} endAngle={-270} stroke="#fff" strokeWidth={2} isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.status} fill={statusColor(r.status)} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-bold text-ink">{total}</span>
          <span className="text-sm text-ink">{centerLabel}</span>
        </div>
      </div>
      <ul className="w-full space-y-2.5">
        {rows.map((r) => (
          <li key={r.status} className="flex items-center gap-2.5 text-[0.95rem] text-ink">
            <span className="size-3.5 rounded-full" style={{ background: statusColor(r.status) }} aria-hidden />
            <span>{humanize(r.status)}</span>
            <span className="ml-auto font-semibold">
              {r.count} <span className="font-normal text-ink-muted">({((r.count / total) * 100).toFixed(1)}%)</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
