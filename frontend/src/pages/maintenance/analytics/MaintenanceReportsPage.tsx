import clsx from 'clsx'
import { Download, FileSpreadsheet, FileText } from 'lucide-react'
import { useState } from 'react'
import { inputClass } from '../../../components/ui/buttons'
import { Card, CardHeader } from '../../../components/ui/Card'
import { FilterSelect } from '../../../components/ui/FilterSelect'
import { PageHeader } from '../../../components/ui/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { useApi } from '../../../hooks/useApi'
import { formatDate, formatDateTime, formatDuration, formatNumber, formatPercent } from '../../../lib/format'
import {
  hoursOrMinutes,
  useMaintenanceAccess,
  type EquipmentAnalyticsRow,
  type EquipmentOptions,
  type MaintenanceKpis,
  type ReportPreview,
} from '../../../lib/maintenance'
import { todayIso } from '../../../lib/time'
import { ReliabilityMetrics } from './Metrics'

const minusDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

function show(v: unknown): string {
  if (v == null || v === '') return '—'
  if (typeof v === 'number') return formatNumber(v)
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return formatDateTime(v)
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) return formatDate(v)
  return String(v)
}

export function MaintenanceReportsPage() {
  const { can } = useMaintenanceAccess()
  const canExport = can('reports.export')
  const today = todayIso()
  const [start, setStart] = useState(minusDays(today, 29))
  const [end, setEnd] = useState(today)
  const [facility, setFacility] = useState('')
  const [key, setKey] = useState('equipment-downtime')
  const invalid = !start || !end || start > end
  const params = new URLSearchParams({ start, end })
  if (facility) params.set('facility', facility)

  const options = useApi<EquipmentOptions>('/maintenance/equipment/options')
  const reports = useApi<{ key: string; title: string; description: string }[]>('/maintenance/reports')
  const analytics = useApi<{ kpis: MaintenanceKpis; equipment: EquipmentAnalyticsRow[] }>(invalid ? null : `/maintenance/analytics?${params}`)
  const preview = useApi<ReportPreview>(invalid ? null : `/maintenance/reports/${key}?${params}`)
  const facilities = [{ value: '', label: 'All facilities' }, ...(options.data?.facilities ?? []).map((f) => ({ value: f, label: f }))]
  const download = (format: string) => `/api/maintenance/reports/${key}?${params}&format=${format}`

  return (
    <>
      <PageHeader title="Maintenance Reports" description="Reliability metrics and maintenance reports with CSV, Excel and PDF export." />

      {/* One filter row scopes every figure and report on the page. */}
      <div className="flex flex-wrap items-end gap-3 rounded-2xl bg-white/80 p-3 shadow-sm">
        <label className="text-sm font-semibold text-ink">From
          <input type="date" value={start} max={end || today} onChange={(e) => setStart(e.target.value)} className={`${inputClass} mt-1 h-10 w-40`} />
        </label>
        <label className="text-sm font-semibold text-ink">To
          <input type="date" value={end} min={start} max={today} onChange={(e) => setEnd(e.target.value)} className={`${inputClass} mt-1 h-10 w-40`} />
        </label>
        <FilterSelect label="Facility" value={facility} options={facilities} onChange={setFacility} />
        {invalid && <p role="alert" className="text-sm font-semibold text-red-700">The start date must be on or before the end date.</p>}
      </div>

      {analytics.error && !analytics.data ? <div className="mt-4"><ErrorState message={analytics.error.message} onRetry={analytics.refetch} /></div>
        : analytics.data && (
          <div className={clsx('mt-4', analytics.loading && 'opacity-60')}>
            <ReliabilityMetrics m={analytics.data.kpis} />
            <Card className="mt-4">
              <CardHeader title="Availability by equipment" subtitle={`${formatDate(analytics.data.kpis.window.start)} – ${formatDate(analytics.data.kpis.window.end)}`} />
              {analytics.data.equipment.length === 0 ? <EmptyState title="No equipment in scope" /> : (
                <div className="-mx-2 overflow-x-auto">
                  <table className="w-full min-w-[760px] text-left text-sm">
                    <thead>
                      <tr className="bg-surface-muted text-ink">
                        {['Equipment', 'Availability', 'Downtime', 'Failures', 'MTBF', 'MTTR', 'PM compliance'].map((h) => (
                          <th key={h} scope="col" className="px-3 py-2 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {analytics.data.equipment.map((r) => (
                        <tr key={r.equipment_id} className="border-b border-line last:border-0">
                          <td className="px-3 py-2"><span className="font-mono font-semibold">{r.code}</span><span className="block text-xs text-ink-muted">{r.name}</span></td>
                          <td className="px-3 py-2 tabular-nums">{r.availability_pct == null ? '—' : formatPercent(r.availability_pct)}</td>
                          <td className="px-3 py-2 tabular-nums">{formatDuration(r.downtime_minutes)}</td>
                          <td className="px-3 py-2 tabular-nums">{r.failures}</td>
                          <td className="px-3 py-2 tabular-nums">{r.mtbf_hours == null ? <span className="text-ink-muted" title="No failures in the period">n/a</span> : hoursOrMinutes(r.mtbf_hours)}</td>
                          <td className="px-3 py-2 tabular-nums">{r.mttr_minutes == null ? <span className="text-ink-muted">n/a</span> : formatDuration(r.mttr_minutes)}</td>
                          <td className="px-3 py-2 tabular-nums">{r.pm_compliance_pct == null ? <span className="text-ink-muted">n/a</span> : `${formatPercent(r.pm_compliance_pct)} (${r.pm_on_time}/${r.pm_due})`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="mt-2 text-xs text-ink-muted">n/a = insufficient data for that asset in this period (no failures, repairs or due tasks).</p>
            </Card>
          </div>
        )}

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card className="self-start">
          <CardHeader title="Reports" />
          <ul className="space-y-1" role="listbox" aria-label="Reports">
            {reports.data?.map((r) => (
              <li key={r.key}>
                <button type="button" role="option" aria-selected={r.key === key} onClick={() => setKey(r.key)}
                  className={clsx('w-full rounded-xl px-3 py-2 text-left text-sm', r.key === key ? 'bg-sky-50 font-semibold text-primary ring-1 ring-accent' : 'text-ink hover:bg-surface-muted')}>
                  {r.title}
                  <span className="block text-xs font-normal text-ink-muted">{r.description}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title={preview.data?.title ?? 'Report'}
            subtitle={preview.data ? `${formatNumber(preview.data.total)} row${preview.data.total === 1 ? '' : 's'}${preview.data.total > preview.data.rows.length ? ` · preview shows ${preview.data.rows.length}` : ''}` : undefined}
            action={canExport ? (
              <span className="flex flex-wrap gap-2">
                <a href={download('csv')} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-semibold text-ink hover:bg-surface-muted"><Download className="size-4" aria-hidden /> CSV</a>
                <a href={download('xlsx')} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-semibold text-ink hover:bg-surface-muted"><FileSpreadsheet className="size-4" aria-hidden /> Excel</a>
                <a href={download('pdf')} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-semibold text-white hover:bg-primary-hover"><FileText className="size-4" aria-hidden /> PDF</a>
              </span>
            ) : <span className="text-xs text-ink-muted">Your role can view but not export reports.</span>} />
          {invalid ? null : preview.error && !preview.data ? <ErrorState message={preview.error.message} onRetry={preview.refetch} />
            : !preview.data ? <LoadingState /> : preview.data.rows.length === 0 ? (
              <EmptyState title="No records for this period" />
            ) : (
              <div className={clsx('-mx-2 max-h-[32rem] overflow-auto', preview.loading && 'opacity-60')}>
                <table className="w-full text-left text-sm whitespace-nowrap">
                  <thead className="sticky top-0">
                    <tr className="bg-surface-muted text-ink">
                      {preview.data.columns.map((c) => <th key={c.key} scope="col" className="px-3 py-2 font-semibold">{c.label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.data.rows.map((r, i) => (
                      <tr key={i} className="border-b border-line last:border-0">
                        {preview.data!.columns.map((c) => <td key={c.key} className="max-w-[22rem] truncate px-3 py-1.5" title={show(r[c.key])}>{show(r[c.key])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        </Card>
      </div>
    </>
  )
}
