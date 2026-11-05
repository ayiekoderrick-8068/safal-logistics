import { useState } from 'react'
import { Card, CardHeader } from '../../../components/ui/Card'
import { FilterSelect } from '../../../components/ui/FilterSelect'
import { Pagination } from '../../../components/ui/Pagination'
import { ErrorState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { useApi } from '../../../hooks/useApi'
import { DELAY_CAUSE_LABELS, formatDateTime, formatDuration } from '../../../lib/format'
import type { CatalogueItem, RecordsPage } from '../types'
import { DataTable, ExportLink, type Col } from '../ui'

type Kind = 'turnaround' | 'schedules' | 'dispatches' | 'delays'
type Row = Record<string, unknown>
const PAGE = 15

const s = (v: unknown) => (v == null || v === '' ? '—' : String(v))
const t = (v: unknown) => formatDateTime(v as string | null)
const d = (v: unknown) => formatDuration(v as number | null)

const COLUMNS: Record<Kind, Col<Row>[]> = {
  turnaround: [
    { header: 'Truck', cell: (r) => <span className="font-semibold text-ink">{s(r.truck)}</span> },
    { header: 'Bay', cell: (r) => s(r.bay) },
    { header: 'Route', cell: (r) => s(r.route) },
    { header: 'Arrival', cell: (r) => t(r.arrival_at) },
    { header: 'Departure', cell: (r) => t(r.departed_at) },
    { header: 'Waiting', cell: (r) => d(r.waiting_minutes) },
    { header: 'Loading', cell: (r) => d(r.loading_minutes) },
    { header: 'Turnaround', cell: (r) => <span className={r.within_target === false ? 'font-semibold text-red-600' : 'font-semibold text-emerald-700'}>{d(r.turnaround_minutes)}</span> },
    { header: 'Delivery', cell: (r) => r.delivery_outcome ? <StatusBadge status={r.delivery_outcome === 'on_time' ? 'delivered' : r.delivery_outcome === 'late' ? 'delayed' : 'in_transit'} label={String(r.delivery_outcome).replace('_', ' ')} /> : '—' },
  ],
  schedules: [
    { header: 'Truck', cell: (r) => <span className="font-semibold text-ink">{s(r.truck)}</span> },
    { header: 'Bay', cell: (r) => s(r.bay) },
    { header: 'Scheduled', cell: (r) => t(r.scheduled_start) },
    { header: 'Arrival', cell: (r) => t(r.arrival_at) },
    { header: 'Loading', cell: (r) => d(r.loading_minutes) },
    { header: 'Departure', cell: (r) => t(r.departed_at) },
    { header: 'Status', cell: (r) => <StatusBadge status={String(r.status)} /> },
  ],
  dispatches: [
    { header: 'Load', cell: (r) => s(r.load_ref) },
    { header: 'Truck', cell: (r) => <span className="font-semibold text-ink">{s(r.truck)}</span> },
    { header: 'Route', cell: (r) => s(r.route) },
    { header: 'Dispatched', cell: (r) => t(r.dispatched_at) },
    { header: 'Deadline', cell: (r) => t(r.deadline_at) },
    { header: 'Arrived', cell: (r) => t(r.actual_arrival_at) },
    { header: 'Duration', cell: (r) => d(r.delivery_minutes) },
    { header: 'Outcome', cell: (r) => <StatusBadge status={r.outcome === 'on_time' ? 'delivered' : r.outcome === 'late' ? 'delayed' : String(r.status)} label={String(r.outcome).replace('_', ' ')} /> },
  ],
  delays: [
    { header: 'Started', cell: (r) => t(r.started_at) },
    { header: 'Truck', cell: (r) => <span className="font-semibold text-ink">{s(r.truck)}</span> },
    { header: 'Category', cell: (r) => DELAY_CAUSE_LABELS[String(r.cause)] ?? s(r.cause) },
    { header: 'Bay / route', cell: (r) => s(r.route ?? r.bay) },
    { header: 'Duration', cell: (r) => `${d(r.duration_minutes)}${r.ongoing ? ' (ongoing)' : ''}` },
    { header: 'Impact', cell: (r) => `${s(r.impact_minutes)} min` },
    { header: 'Status', cell: (r) => <StatusBadge status={String(r.status)} /> },
  ],
}
const LABELS: Record<Kind, string> = {
  turnaround: 'Loading turnaround records', schedules: 'Loading schedules', dispatches: 'Dispatch records', delays: 'Delay incidents',
}

export function RecordsTab({ query, catalogue, onExported }: { query: string; catalogue: CatalogueItem[] | undefined; onExported: () => void }) {
  const [kind, setKind] = useState<Kind>('turnaround')
  const [offset, setOffset] = useState(0)
  const { data, error, refetch } = useApi<RecordsPage>(`/reports/records?${query}&type=${kind}&limit=${PAGE}&offset=${offset}`)
  const can = (key: string, f: 'csv' | 'pdf') => !!catalogue?.find((c) => c.key === key && c.formats.includes(f))
  const pdfFor: Record<Kind, string> = { turnaround: 'turnaround', schedules: 'bays', dispatches: 'dispatch', delays: 'delays' }
  return (
    <Card>
      <CardHeader title={`Report Results (${LABELS[kind]})`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <FilterSelect label="Record type" value={kind} onChange={(v) => { setKind(v as Kind); setOffset(0) }}
              options={(Object.keys(LABELS) as Kind[]).map((k) => ({ value: k, label: LABELS[k] }))} />
            {can(kind, 'csv') && <ExportLink href={`/api/reports/export/${kind}.csv?${query}`} format="csv" label="Export CSV" onClick={onExported} />}
            {can(pdfFor[kind], 'pdf') && <ExportLink href={`/api/reports/export/${pdfFor[kind]}.pdf?${query}`} format="pdf" label="Export PDF" onClick={onExported} />}
          </div>
        } />
      {error && !data ? <ErrorState message={error.message} onRetry={refetch} /> : !data ? <LoadingState /> : (
        <>
          <DataTable cols={COLUMNS[kind]} rows={data.items} minWidth={900} caption={LABELS[kind]} empty="No records match these filters." />
          <Pagination total={data.total} limit={PAGE} offset={offset} noun="records" onChange={setOffset} />
        </>
      )}
    </Card>
  )
}
