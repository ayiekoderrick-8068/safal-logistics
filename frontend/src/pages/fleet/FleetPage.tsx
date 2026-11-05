import clsx from 'clsx'
import { CircleCheck, Plus, Search, ShieldAlert, Truck, UserPlus, Wrench } from 'lucide-react'
import { useState } from 'react'
import { useAuth } from '../../auth/context'
import { btnPrimary, btnSecondary } from '../../components/ui/buttons'
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
import { formatDate, formatNumber, formatPercent } from '../../lib/format'
import type { FleetSummary, Meta, Page, Truck as TruckT, TruckDetail } from '../../lib/types'
import { DriverFormModal } from './DriverFormModal'
import { TruckDetailPanel } from './TruckDetailPanel'
import { TruckFormModal } from './TruckFormModal'

const PAGE_SIZE = 8
const STATUS_OPTIONS = [
  { value: '', label: 'Status: All' },
  { value: 'available', label: 'Available' },
  { value: 'loading', label: 'Loading' },
  { value: 'in_transit', label: 'In Transit' },
  { value: 'maintenance', label: 'Maintenance' },
  { value: 'out_of_service', label: 'Out of Service' },
]
const COMPLIANCE_TEXT = {
  valid: 'text-ink',
  expiring: 'font-semibold text-amber-700',
  overdue: 'font-semibold text-red-600',
  missing: 'text-ink-muted',
}

type Dialog = { kind: 'truck'; truck?: TruckT } | { kind: 'driver' } | null

export function FleetPage() {
  const { hasRole } = useAuth()
  const toast = useToast()
  const canEdit = hasRole('fleet_manager')
  const canSchedule = hasRole('operations')

  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [version, setVersion] = useState(0)
  const q = useDebounced(query.trim())

  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (q) params.set('q', q)
  if (status) params.set('status', status)
  const list = useApi<Page<TruckT>>(`/trucks?${params}`)
  const summary = useApi<FleetSummary>(`/trucks/summary?v=${version}`)
  const meta = useApi<Meta>('/meta')

  const selectedId = selected ?? list.data?.items[0]?.id ?? null
  const reload = () => setVersion((v) => v + 1)
  const s = summary.data

  return (
    <>
      <PageHeader
        title="Fleet Management"
        description="Track truck availability, drivers, maintenance and compliance."
        actions={canEdit && (
          <>
            <button type="button" className={btnSecondary} onClick={() => setDialog({ kind: 'driver' })}>
              <UserPlus className="size-4" aria-hidden /> Add Driver
            </button>
            <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'truck' })}>
              <Plus className="size-4" aria-hidden /> Add Truck
            </button>
          </>
        )}
      />
      {meta.data?.sample_data && <SampleDataBanner />}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard icon={Truck} tone="blue" label="Total Trucks" value={formatNumber(s?.total)} note="Registered in fleet" />
        <StatCard icon={CircleCheck} tone="green" label="Available" value={formatNumber(s?.available)}
          note={s?.availability_pct != null ? `${formatPercent(s.availability_pct)} fleet availability` : undefined} />
        <StatCard icon={Truck} tone="teal" label="In Transit" value={formatNumber(s?.in_transit)}
          note={s ? `${s.loading} loading at bays` : undefined} />
        <StatCard icon={Wrench} tone="amber" label="Under Maintenance" value={formatNumber(s?.maintenance)}
          note={s ? `${s.out_of_service} out of service` : undefined} />
        <StatCard icon={ShieldAlert} tone="red" label="Compliance Due" value={formatNumber(s?.compliance_due)}
          note="Expired or due within 30 days" />
      </div>

      <div className="mt-4 flex flex-col gap-3 md:flex-row">
        <label className="relative flex-1">
          <span className="sr-only">Search trucks</span>
          <Search className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-ink-muted" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setOffset(0) }}
            placeholder="Search by registration, make or driver…"
            className="h-11 w-full rounded-xl border border-white bg-white pr-4 pl-12 text-ink shadow-sm placeholder:text-ink-muted"
          />
        </label>
        <FilterSelect label="Filter by status" value={status} options={STATUS_OPTIONS}
          onChange={(v) => { setStatus(v); setOffset(0) }} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader title="Fleet Register" />
          {list.error && !list.data ? (
            <ErrorState message={list.error.message} onRetry={list.refetch} />
          ) : !list.data ? (
            <LoadingState />
          ) : list.data.items.length === 0 ? (
            <EmptyState title={q || status ? 'No trucks match your filters' : 'No trucks registered yet'}>
              {canEdit && !q && !status && 'Use “Add Truck” to register the first vehicle.'}
            </EmptyState>
          ) : (
            <>
              <div className="-mx-2 overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-sm whitespace-nowrap">
                  <thead>
                    <tr className="bg-surface-muted text-ink">
                      {['Truck No.', 'Driver', 'Route (last)', 'Status', 'Next Compliance Expiry'].map((h) => (
                        <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {list.data.items.map((t) => (
                      <tr key={t.id}
                        className={clsx('border-b border-line last:border-0', t.id === selectedId && 'bg-sky-50/70')}>
                        <td className="px-3 py-2.5">
                          <button type="button" onClick={() => setSelected(t.id)} aria-pressed={t.id === selectedId}
                            className="flex items-center gap-3 font-semibold text-ink hover:text-primary">
                            <span className="grid size-8 place-items-center rounded-lg bg-surface-muted text-primary">
                              <Truck className="size-4.5" aria-hidden />
                            </span>
                            {t.registration}
                          </button>
                        </td>
                        <td className="px-3 py-2.5">{t.driver?.label ?? <span className="text-ink-muted">Unassigned</span>}</td>
                        <td className="px-3 py-2.5">{t.last_route ?? <span className="text-ink-muted">—</span>}</td>
                        <td className="px-3 py-2.5"><StatusBadge status={t.status} /></td>
                        <td className={clsx('px-3 py-2.5', COMPLIANCE_TEXT[t.compliance.status])}>
                          {t.compliance.next_expiry ? formatDate(t.compliance.next_expiry) : 'No documents'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun="trucks" onChange={setOffset} />
            </>
          )}
        </Card>

        {selectedId != null && (
          <TruckDetailPanel truckId={selectedId} version={version} canEdit={canEdit} canSchedule={canSchedule}
            onEdit={(t: TruckDetail) => setDialog({ kind: 'truck', truck: t })} />
        )}
      </div>

      {dialog?.kind === 'truck' && (
        <TruckFormModal
          truck={dialog.truck}
          onClose={() => setDialog(null)}
          onSaved={(t) => {
            setDialog(null)
            setSelected(t.id)
            reload()
            toast.success(dialog.truck ? `${t.registration} updated` : `${t.registration} registered`)
          }}
        />
      )}
      {dialog?.kind === 'driver' && (
        <DriverFormModal
          onClose={() => setDialog(null)}
          onSaved={(d) => {
            setDialog(null)
            reload()
            toast.success(`Driver ${d.full_name} added`)
          }}
        />
      )}
    </>
  )
}
