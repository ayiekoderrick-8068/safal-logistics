import { FileText } from 'lucide-react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardHeader } from '../../../components/ui/Card'
import { EmptyState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { formatDateTime, formatDayLabel } from '../../../lib/format'
import { StatusDonut } from '../../overview/charts'
import type { CatalogueItem, ReportRun, Summary } from '../types'
import { ExportLink, Note } from '../ui'

const OUTCOME_COLORS = { on_time: '#16a34a', late: '#ef4444', pending: '#f59e0b', cancelled: '#94a3b8' }
const OUTCOME_LABELS = { on_time: 'Delivered on time', late: 'Delivered late', pending: 'In transit / pending', cancelled: 'Cancelled' }

export function OverviewTab({ summary, query, catalogue, history, onExported }: {
  summary: Summary
  query: string
  catalogue: CatalogueItem[] | undefined
  history: ReportRun[] | undefined
  onExported: () => void
}) {
  const data = summary.trend.map((t) => ({
    ...t, hours: t.avg_turnaround_minutes == null ? null : +(t.avg_turnaround_minutes / 60).toFixed(2),
  }))
  const hasData = data.some((d) => d.loads > 0)
  const pdfs = catalogue?.filter((c) => c.formats.includes('pdf')) ?? []
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-8">
        <CardHeader title="Operational Performance Trend"
          subtitle="Completed loads per day, average yard turnaround (h) and on-time delivery (%)." />
        {!hasData ? <EmptyState title="No completed loads match these filters" /> : (
          <div className="h-72" role="img" aria-label="Daily loads, average turnaround hours and on-time delivery percentage">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={data} margin={{ top: 8, right: 4, left: -6, bottom: 0 }}>
                <CartesianGrid stroke="#e6eef3" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={12}
                  tickFormatter={(v: string) => formatDayLabel(v).date} />
                <YAxis yAxisId="h" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={42}
                  domain={[0, (max: number) => Math.max(3, Math.ceil(max))]} tickFormatter={(v: number) => `${v} h`} />
                <YAxis yAxisId="pct" orientation="right" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 11 }}
                  axisLine={false} tickLine={false} width={42} tickFormatter={(v: number) => `${v}%`} />
                <YAxis yAxisId="loads" hide allowDecimals={false} domain={[0, (max: number) => Math.ceil(max * 1.3)]} />
                <Tooltip labelFormatter={(v) => String(v)} formatter={(v, n) => (v == null ? ['No data', n]
                  : n === 'Avg turnaround' ? [`${v} h`, n] : n === 'On-time delivery' ? [`${v}%`, n] : [v, n])} />
                <Legend verticalAlign="top" height={28} iconSize={10} wrapperStyle={{ fontSize: 12 }} />
                <Bar yAxisId="loads" dataKey="loads" name="Loads processed" fill="#9ed3f5" radius={[5, 5, 0, 0]} maxBarSize={36} isAnimationActive={false} />
                <ReferenceLine yAxisId="h" y={summary.target_minutes / 60} stroke="#0e8fa8" strokeDasharray="6 4" />
                <Line yAxisId="h" dataKey="hours" name="Avg turnaround" stroke="#1d6fd8" strokeWidth={2.5} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                <Line yAxisId="pct" dataKey="on_time_pct" name="On-time delivery" stroke="#22a447" strokeWidth={2.5} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
        <Note>Dashed line: turnaround target ({(summary.target_minutes / 60).toFixed(1)} h). Days without completed loads are left blank rather than shown as zero.</Note>
      </Card>
      <Card className="xl:col-span-4">
        <CardHeader title="Dispatches by Outcome" subtitle="Dispatches sent in the period." />
        {summary.dispatch_outcomes.length === 0 ? <EmptyState title="No dispatches in this period" /> : (
          <StatusDonut rows={summary.dispatch_outcomes} centerLabel="Dispatches" colors={OUTCOME_COLORS} labels={OUTCOME_LABELS} />
        )}
      </Card>
      <Card className="xl:col-span-6">
        <CardHeader title="Quick Reports" subtitle="PDF reports for the applied filters." />
        {!catalogue ? <LoadingState /> : pdfs.length === 0 ? <EmptyState title="No reports available for your role" /> : (
          <ul className="divide-y divide-line">
            {pdfs.map((c) => (
              <li key={c.key} className="flex items-center gap-3 py-2.5">
                <FileText className="size-5 text-primary" aria-hidden />
                <span className="flex-1 font-semibold text-ink">{c.title}</span>
                <ExportLink href={`/api/reports/export/${c.key}.pdf?${query}`} format="pdf" label="PDF" onClick={onExported} />
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="xl:col-span-6">
        <CardHeader title="Recent Report Activity" subtitle="Reports you generated (documents are not stored)." />
        {!history ? <LoadingState /> : history.length === 0 ? <EmptyState title="No reports generated yet" /> : (
          <ul className="divide-y divide-line text-sm">
            {history.map((h) => (
              <li key={h.id} className="flex items-center gap-3 py-2">
                <span className="w-12 rounded-md bg-surface-muted px-1.5 py-0.5 text-center text-xs font-bold text-ink uppercase">{h.format}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold text-ink">{h.title}</span>
                  <span className="block truncate text-xs text-ink-muted">
                    {formatDateTime(h.created_at)} · {h.filters.start} – {h.filters.end}
                    {h.row_count != null ? ` · ${h.row_count} rows` : ''}{h.requested_by ? ` · ${h.requested_by}` : ''}
                  </span>
                </span>
                <StatusBadge status={h.status === 'success' ? 'completed' : 'delayed'} label={h.status === 'success' ? 'Generated' : 'Failed'} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
