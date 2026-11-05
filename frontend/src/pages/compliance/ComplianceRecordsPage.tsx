import clsx from 'clsx'
import {
  CalendarDays,
  CircleAlert,
  CircleCheck,
  ClipboardList,
  Clock,
  Eye,
  FileCheck2,
  Minus,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useAuth } from '../../auth/context'
import { btnPrimary, btnSecondary, btnSmallGhost } from '../../components/ui/buttons'
import { Card, CardHeader } from '../../components/ui/Card'
import { FilterSelect } from '../../components/ui/FilterSelect'
import { PageHeader } from '../../components/ui/PageHeader'
import { Pagination } from '../../components/ui/Pagination'
import { SampleDataBanner } from '../../components/ui/SampleDataBanner'
import { StatCard } from '../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useToast } from '../../components/ui/toastContext'
import { useApi } from '../../hooks/useApi'
import { useDebounced } from '../../hooks/useDebounced'
import { DOC_LABELS, formatDate, formatNumber, formatPercent } from '../../lib/format'
import type { ComplianceOverview, DocState, Page, VehicleCompliance } from '../../lib/types'
import { StatusDonut } from '../overview/charts'
import { DocumentFormModal } from './DocumentFormModal'
import { RequirementsModal } from './RequirementsModal'
import { VehicleDocumentsModal } from './VehicleDocumentsModal'

const PAGE_SIZE = 8
const COLUMNS = ['insurance', 'licence', 'inspection', 'roadworthy'] as const
const STATUS_LABEL = { compliant: 'Compliant', expiring: 'Expiring Soon', non_compliant: 'Non-Compliant' }
const FLEET_COLORS = { compliant: '#16a34a', expiring: '#f59e0b', non_compliant: '#ef4444' }

function DocCell({ state, expires, mandatory }: { state: DocState; expires: string | null; mandatory: boolean }) {
  const icon = {
    valid: <CircleCheck className="size-4.5 text-emerald-600" aria-hidden />,
    expiring: <Clock className="size-4.5 text-amber-500" aria-hidden />,
    expired: <TriangleAlert className="size-4.5 text-red-600" aria-hidden />,
    missing: <CircleAlert className="size-4.5 text-red-600" aria-hidden />,
    not_required: <Minus className="size-4.5 text-slate-400" aria-hidden />,
  }[state]
  const text = expires ? formatDate(expires) : state === 'missing' ? 'Missing' : 'Not required'
  return (
    <span className={clsx('inline-flex items-center gap-1.5',
      state === 'expired' || state === 'missing' ? 'font-semibold text-red-600' : state === 'expiring' ? 'font-semibold text-amber-700' : 'text-ink',
      state === 'not_required' && 'text-ink-muted')}>
      {icon}
      {text}
      <span className="sr-only">({state.replace('_', ' ')}{mandatory ? ', mandatory' : ''})</span>
    </span>
  )
}

export function ComplianceRecordsPage() {
  const { hasRole } = useAuth()
  const canEdit = hasRole('compliance', 'fleet_manager')
  const canEditRules = hasRole('compliance')
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [docType, setDocType] = useState('')
  const [offset, setOffset] = useState(0)
  const [version, setVersion] = useState(0)
  const [dialog, setDialog] = useState<'add' | 'rules' | null>(null)
  const viewing = Number(params.get('truck')) || null
  const q = useDebounced(query.trim())

  const overview = useApi<ComplianceOverview>(`/compliance/overview?v=${version}`)
  const qs = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (q) qs.set('q', q)
  if (status) qs.set('status', status)
  if (docType) qs.set('doc_type', docType)
  const vehicles = useApi<Page<VehicleCompliance>>(`/compliance/vehicles?${qs}`)
  const reload = () => setVersion((v) => v + 1)
  const openTruck = (id: number | null) => setParams(id ? { truck: String(id) } : {}, { replace: !id })
  const o = overview.data

  return (
    <>
      <PageHeader
        title="Compliance Records"
        description="Manage vehicle compliance, documents, inspections and renewals to keep operations on the move."
        actions={
          <>
            <button type="button" className={btnSecondary} onClick={() => setDialog('rules')}>
              <Settings2 className="size-4" aria-hidden /> Requirements
            </button>
            {canEdit && (
              <button type="button" className={btnPrimary} onClick={() => setDialog('add')}>
                <Plus className="size-4" aria-hidden /> Add Compliance Record
              </button>
            )}
          </>
        }
      />
      {o?.sample_data && <SampleDataBanner />}

      {overview.error && !o ? (
        <Card><ErrorState message={overview.error.message} onRetry={overview.refetch} /></Card>
      ) : !o ? (
        <Card><LoadingState label="Loading compliance data…" /></Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard icon={ShieldCheck} tone="green" label="Compliant Vehicles" value={formatNumber(o.compliant_vehicles)}
              note={o.compliant_pct != null ? `${formatPercent(o.compliant_pct)} of fleet` : 'No vehicles'} />
            <StatCard icon={Clock} tone="amber" label="Expiring ≤ 30 Days" value={formatNumber(o.expiring_documents)}
              note={`${o.expiring_vehicles} vehicles affected`} />
            <StatCard icon={TriangleAlert} tone="red" label="Non-Compliant Vehicles" value={formatNumber(o.non_compliant_vehicles)}
              note={`${o.expired_documents} expired · ${o.missing_documents} missing`} />
            <StatCard icon={ClipboardList} tone="blue" label="Documents on Record" value={formatNumber(o.documents_on_record)}
              note={`+${o.documents_added_30d} in last 30 days`} />
            <StatCard icon={FileCheck2} tone="teal" label="Inspections Due" value={formatNumber(o.inspections_due_30d)}
              note="Next 30 days" />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-5">
              <CardHeader title="Document Expiry Overview" subtitle="Current documents by type and status." />
              {o.total_vehicles === 0 ? <EmptyState title="No vehicles registered" /> : (
                <div className="h-60" role="img" aria-label="Documents by type: valid, expiring, expired and missing">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={o.by_type.map((t) => ({ ...t, label: DOC_LABELS[t.doc_type].replace(' certificate', '') }))}
                      margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                      <CartesianGrid stroke="#e6eef3" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} interval={0} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                      <Tooltip />
                      <Legend verticalAlign="top" height={28} iconSize={10} wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey="valid" name="Valid (> reminder)" stackId="s" fill="#1fa045" isAnimationActive={false} />
                      <Bar dataKey="expiring" name="Expiring" stackId="s" fill="#f8b630" isAnimationActive={false} />
                      <Bar dataKey="expired" name="Expired" stackId="s" fill="#ef4444" isAnimationActive={false} />
                      <Bar dataKey="missing" name="Missing (mandatory)" stackId="s" fill="#94a3b8" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
            <Card className="xl:col-span-4">
              <CardHeader title="Fleet Compliance Status" subtitle="Vehicles by overall status." />
              {o.total_vehicles === 0 ? <EmptyState title="No vehicles registered" /> : (
                <StatusDonut
                  rows={(['compliant', 'expiring', 'non_compliant'] as const).map((s) => ({
                    status: s, count: s === 'compliant' ? o.compliant_vehicles : s === 'expiring' ? o.expiring_vehicles : o.non_compliant_vehicles,
                  }))}
                  centerValue={formatPercent(o.compliant_pct)} centerLabel="Compliant" colors={FLEET_COLORS} labels={STATUS_LABEL} />
              )}
            </Card>
            <Card className="xl:col-span-3">
              <CardHeader title="Upcoming Renewals" subtitle="Expired or due within 60 days." />
              {o.upcoming.length === 0 ? <EmptyState title="No renewals due" /> : (
                <ul className="divide-y divide-line">
                  {o.upcoming.map((u) => (
                    <li key={u.document_id}>
                      <button type="button" onClick={() => openTruck(u.truck.id)}
                        className="flex w-full items-center gap-2 py-2.5 text-left text-sm hover:bg-surface-muted/60">
                        <CalendarDays className="size-4 shrink-0 text-primary" aria-hidden />
                        <span className="min-w-0 flex-1">
                          <span className="block font-semibold text-ink">{u.truck.label}</span>
                          <span className="block truncate text-xs text-ink-muted">{DOC_LABELS[u.doc_type]} · {formatDate(u.expires_on)}</span>
                        </span>
                        <span className={clsx('rounded-lg px-2 py-0.5 text-xs font-semibold whitespace-nowrap',
                          u.days_remaining < 0 ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-800')}>
                          {u.days_remaining < 0 ? `${-u.days_remaining}d overdue` : `${u.days_remaining} days`}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}

      <Card className="mt-4">
        <CardHeader
          title="Vehicle Compliance Records"
          subtitle="Compliance status, expiry dates and documents for each vehicle."
          action={
            <div className="flex flex-wrap gap-2">
              <FilterSelect label="Filter by status" value={status} onChange={(v) => { setStatus(v); setOffset(0) }}
                options={[{ value: '', label: 'All Statuses' }, ...Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))]} />
              <FilterSelect label="Filter by document issue" value={docType} onChange={(v) => { setDocType(v); setOffset(0) }}
                options={[{ value: '', label: 'All Document Types' }, ...['insurance', 'licence', 'inspection', 'roadworthy', 'speed_governor']
                  .map((t) => ({ value: t, label: `Issue: ${DOC_LABELS[t]}` }))]} />
              <label className="relative">
                <span className="sr-only">Search vehicles</span>
                <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-ink-muted" aria-hidden />
                <input type="search" value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0) }}
                  placeholder="Search truck or driver…"
                  className="h-11 w-60 rounded-xl border border-line bg-white pr-3 pl-10 text-ink shadow-sm placeholder:text-ink-muted" />
              </label>
            </div>
          }
        />
        {vehicles.error && !vehicles.data ? (
          <ErrorState message={vehicles.error.message} onRetry={vehicles.refetch} />
        ) : !vehicles.data ? (
          <LoadingState />
        ) : vehicles.data.items.length === 0 ? (
          <EmptyState title="No vehicles match" />
        ) : (
          <>
            <div className="-mx-2 overflow-x-auto">
              <table className="w-full min-w-[980px] text-left text-sm whitespace-nowrap">
                <thead>
                  <tr className="bg-surface-muted text-ink">
                    {['Truck No.', 'Driver', 'Insurance', 'Licence', 'Inspection', 'Roadworthy', 'Status', 'Actions'].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {vehicles.data.items.map((v) => (
                    <tr key={v.truck.id} className="border-b border-line last:border-0">
                      <td className="px-3 py-2.5 font-semibold text-ink">{v.truck.label}</td>
                      <td className="px-3 py-2.5">{v.driver_name ?? <span className="text-ink-muted">Unassigned</span>}</td>
                      {COLUMNS.map((c) => {
                        const item = v.items.find((i) => i.doc_type === c)!
                        return <td key={c} className="px-3 py-2.5"><DocCell state={item.state} expires={item.expires_on} mandatory={item.mandatory} /></td>
                      })}
                      <td className="px-3 py-2.5">
                        <StatusBadge status={v.status} label={STATUS_LABEL[v.status]} />
                        {!v.eligible && <span className="mt-0.5 block text-xs font-semibold text-red-600">Dispatch blocked</span>}
                      </td>
                      <td className="px-3 py-2.5">
                        <button type="button" className={btnSmallGhost} onClick={() => openTruck(v.truck.id)}
                          aria-label={`View documents for ${v.truck.label}`}>
                          <Eye className="size-3.5" aria-hidden /> Documents
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination total={vehicles.data.total} limit={PAGE_SIZE} offset={offset} noun="vehicles" onChange={setOffset} />
          </>
        )}
      </Card>

      {viewing && (
        <VehicleDocumentsModal truckId={viewing} canEdit={canEdit} onClose={() => openTruck(null)} onChanged={reload} />
      )}
      {dialog === 'add' && (
        <DocumentFormModal mode="add" onClose={() => setDialog(null)}
          onSaved={(d, fileError) => {
            setDialog(null)
            reload()
            toast.success(`${DOC_LABELS[d.doc_type]} recorded for ${d.truck.label}`)
            if (fileError) openTruck(d.truck.id)
          }} />
      )}
      {dialog === 'rules' && <RequirementsModal canEdit={canEditRules} onClose={() => setDialog(null)} onSaved={reload} />}
    </>
  )
}
