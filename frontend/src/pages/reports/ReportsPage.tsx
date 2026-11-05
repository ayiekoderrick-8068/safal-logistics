import { Activity, CircleCheck, Gauge, ShieldAlert, Timer, TriangleAlert, Truck } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { Card, CardHeader } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { StatCard } from '../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States'
import { useApi } from '../../hooks/useApi'
import { formatDuration, formatNumber, formatPercent } from '../../lib/format'
import { fromSearchParams, toQuery, type ReportFilterState } from './filters'
import { ReportFiltersPanel } from './ReportFiltersPanel'
import { BaysTab } from './tabs/BaysTab'
import { DelaysTab } from './tabs/DelaysTab'
import { DispatchTab } from './tabs/DispatchTab'
import { OverviewTab } from './tabs/OverviewTab'
import { RecordsTab } from './tabs/RecordsTab'
import { TurnaroundTab } from './tabs/TurnaroundTab'
import type { CatalogueItem, ReportRun, Summary } from './types'
import { ExportLink, Tabs } from './ui'

type Tab = 'overview' | 'turnaround' | 'delays' | 'bays' | 'dispatch' | 'records'
const TABS: { value: Tab; label: string }[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'turnaround', label: 'Turnaround' },
  { value: 'delays', label: 'Delays' },
  { value: 'bays', label: 'Loading Bays' },
  { value: 'dispatch', label: 'Dispatch & Delivery' },
  { value: 'records', label: 'Records & Export' },
]

export function ReportsPage() {
  const [params, setParams] = useSearchParams()
  const applied = fromSearchParams(params)
  const query = toQuery(applied)
  const tab = (TABS.find((t) => t.value === params.get('tab'))?.value ?? 'overview') as Tab
  const [historyVersion, setHistoryVersion] = useState(0)
  const summary = useApi<Summary>(`/reports/summary?${query}`)
  const catalogue = useApi<CatalogueItem[]>('/reports/catalogue')
  const history = useApi<ReportRun[]>(`/reports/history?limit=8&v=${historyVersion}`)

  const apply = (f: ReportFilterState) => {
    const next = new URLSearchParams(toQuery(f))
    if (tab !== 'overview') next.set('tab', tab)
    setParams(next)
  }
  const setTab = (t: Tab) => {
    const next = new URLSearchParams(params)
    if (t === 'overview') next.delete('tab')
    else next.set('tab', t)
    setParams(next, { replace: true })
  }
  // Downloads happen in the browser; refresh the activity list once the server has logged them.
  const onExported = () => window.setTimeout(() => setHistoryVersion((v) => v + 1), 2500)
  const restricted = summary.error?.status === 403
  const s = summary.data
  const exec = catalogue.data?.find((c) => c.key === 'executive')

  return (
    <>
      <PageHeader
        title="Reports & Export"
        description="Generate, analyse and export operational reports for loading, dispatch, turnaround time and fleet performance."
        actions={exec && <ExportLink href={`/api/reports/export/executive.pdf?${query}`} format="pdf" label="Executive summary PDF" onClick={onExported} />}
      />

      {restricted ? (
        <RestrictedView catalogue={catalogue.data} query={query} onExported={onExported} />
      ) : (
        <>
          <ReportFiltersPanel applied={applied} onApply={apply} />
          {s && (
            <p className="mb-3 text-sm text-ink/70" aria-live="polite">
              Showing {s.applied.map((a) => `${a.label}: ${a.value}`).join(' · ')}
            </p>
          )}
          {summary.error && !s ? (
            <Card><ErrorState message={summary.error.message} onRetry={summary.refetch} /></Card>
          ) : !s ? (
            <Card><LoadingState label="Building report…" /></Card>
          ) : (
            <div className={summary.loading ? 'opacity-70 transition-opacity' : 'transition-opacity'} aria-busy={summary.loading}>
              <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 min-[1900px]:grid-cols-7">
                <StatCard icon={Truck} tone="blue" label="Loads Processed" value={formatNumber(s.kpis.loads_processed)} note="Departed in period" />
                <StatCard icon={CircleCheck} tone="green" label="Completed Dispatches" value={formatNumber(s.kpis.completed_dispatches)}
                  note={`${s.kpis.pending_deliveries} still pending`} />
                <StatCard icon={Activity} tone="green" label="On-Time Delivery" value={formatPercent(s.kpis.on_time_pct)} note="of completed deliveries" />
                <StatCard icon={Timer} tone="teal" label="Avg Turnaround" value={formatDuration(s.kpis.avg_turnaround_minutes)}
                  note={`target ${formatDuration(s.target_minutes)}`} />
                <StatCard icon={TriangleAlert} tone="red" label="Delayed Loads" value={formatNumber(s.kpis.delayed_loads)}
                  note={`${s.kpis.delay_incidents} delay incidents`} />
                <StatCard icon={Gauge} tone="blue" label="Bay Utilization" value={formatPercent(s.kpis.bay_utilization_pct)}
                  note={s.kpis.bay_utilization_pct == null ? 'No occupancy recorded' : 'of operating hours'} />
                <StatCard icon={ShieldAlert} tone="amber" label="Compliance Interruptions" value={formatNumber(s.kpis.compliance_interruptions)}
                  note="Blocked dispatch attempts" />
              </div>
              <Tabs tabs={TABS} value={tab} onChange={setTab} />
              <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
                {tab === 'overview' && <OverviewTab summary={s} query={query} catalogue={catalogue.data} history={history.data} onExported={onExported} />}
                {tab === 'turnaround' && <TurnaroundTab query={query} />}
                {tab === 'delays' && <DelaysTab query={query} />}
                {tab === 'bays' && <BaysTab query={query} />}
                {tab === 'dispatch' && <DispatchTab query={query} />}
                {tab === 'records' && <RecordsTab key={query} query={query} catalogue={catalogue.data} onExported={onExported} />}
              </div>
            </div>
          )}
        </>
      )}
    </>
  )
}

function RestrictedView({ catalogue, query, onExported }: { catalogue: CatalogueItem[] | undefined; query: string; onExported: () => void }) {
  return (
    <Card className="max-w-3xl">
      <CardHeader title="Reports available to your role" subtitle="Operational analytics are limited to operations, fleet and read-only roles." />
      {!catalogue ? <LoadingState /> : catalogue.length === 0 ? <EmptyState title="No reports available" /> : (
        <ul className="divide-y divide-line">
          {catalogue.map((c) => (
            <li key={c.key} className="flex flex-wrap items-center gap-3 py-3">
              <span className="flex-1 font-semibold text-ink">{c.title}</span>
              {c.formats.includes('pdf') && <ExportLink href={`/api/reports/export/${c.key}.pdf?${query}`} format="pdf" label="PDF" onClick={onExported} />}
              {c.formats.includes('csv') && <ExportLink href={`/api/reports/export/${c.key}.csv?${query}`} format="csv" label="CSV" onClick={onExported} />}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
