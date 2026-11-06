import clsx from 'clsx'
import { CalendarClock, CircleCheck, CircleOff, Plus, Search, TriangleAlert, Wrench } from 'lucide-react'
import { useRef, useState } from 'react'
import { btnPrimary } from '../../../components/ui/buttons'
import { Card, CardHeader } from '../../../components/ui/Card'
import { FilterSelect } from '../../../components/ui/FilterSelect'
import { FormError } from '../../../components/ui/Form'
import { PageHeader } from '../../../components/ui/PageHeader'
import { Pagination } from '../../../components/ui/Pagination'
import { StatCard } from '../../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { useToast } from '../../../components/ui/toastContext'
import { useApi } from '../../../hooks/useApi'
import { useDebounced } from '../../../hooks/useDebounced'
import { api, ApiError } from '../../../lib/api'
import { formatDate, formatNumber } from '../../../lib/format'
import {
  CATEGORY_LABELS,
  EQUIPMENT_STATUS_LABELS,
  serviceText,
  useMaintenanceAccess,
  type Equipment,
  type EquipmentOptions,
  type EquipmentSummary,
} from '../../../lib/maintenance'
import type { Page } from '../../../lib/types'
import { ArchiveEquipmentModal } from './ArchiveEquipmentModal'
import { EquipmentDetailPanel } from './EquipmentDetailPanel'
import { EquipmentFormModal } from './EquipmentFormModal'
import { equipmentTone } from './tones'

const PAGE_SIZE = 10
const opts = (all: string, entries: Record<string, string>) => [
  { value: '', label: all },
  ...Object.entries(entries).map(([value, label]) => ({ value, label })),
]
const CATEGORY_OPTIONS = opts('Category: All', CATEGORY_LABELS)
const STATUS_OPTIONS = opts('Status: All', EQUIPMENT_STATUS_LABELS)
const SERVICE_OPTIONS = opts('Service: All', {
  overdue: 'Service overdue', due_soon: 'Due within 14 days', not_scheduled: 'Not scheduled',
})
const VIEW_OPTIONS = [
  { value: 'active', label: 'View: Active' },
  { value: 'archived', label: 'View: Archived' },
]
const SERVICE_TEXT: Record<Equipment['service_state'], string> = {
  overdue: 'font-semibold text-red-600',
  due_soon: 'font-semibold text-amber-700',
  scheduled: 'text-ink',
  not_scheduled: 'text-ink-muted',
}

type Dialog = { kind: 'form'; equipment?: Equipment } | { kind: 'archive'; equipment: Equipment } | null

export function EquipmentPage() {
  const toast = useToast()
  const { can } = useMaintenanceAccess()
  const canManage = can('equipment.manage')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [service, setService] = useState('')
  const [facility, setFacility] = useState('')
  const [view, setView] = useState('active')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [version, setVersion] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)
  const detailRef = useRef<HTMLDivElement>(null)
  const q = useDebounced(query.trim())
  const archived = view === 'archived'

  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (q) params.set('q', q)
  if (category) params.set('category', category)
  if (status) params.set('status', status)
  if (service) params.set('service', service)
  if (facility) params.set('facility', facility)
  if (archived) params.set('archived', 'true')
  const list = useApi<Page<Equipment>>(`/maintenance/equipment?${params}`)
  const summary = useApi<EquipmentSummary>(`/maintenance/equipment/summary?v=${version}`)
  const options = useApi<EquipmentOptions>(`/maintenance/equipment/options?v=${version}`)
  const facilityOptions = [{ value: '', label: 'Facility: All' }, ...(options.data?.facilities ?? []).map((f) => ({ value: f, label: f }))]

  const items = list.data?.items ?? []
  const selectedId = selected && items.some((e) => e.id === selected) ? selected : (items[0]?.id ?? null)
  const reload = () => setVersion((v) => v + 1)
  const filtered = !!(q || category || status || service || facility)
  const resetPage = <T,>(set: (v: T) => void) => (v: T) => { set(v); setOffset(0) }
  const s = summary.data

  function select(id: number) {
    setSelected(id)
    // Below the two-column layout the details sit under the list: bring them into view.
    if (window.matchMedia?.('(max-width: 1279px)').matches) {
      requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    }
  }

  async function restore(e: Equipment) {
    setActionError(null)
    try {
      await api(`/maintenance/equipment/${e.id}/restore`, { method: 'POST' })
      toast.success(`${e.code} restored to the active register`)
      setView('active')
      reload()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not restore the equipment.')
    }
  }

  return (
    <>
      <PageHeader
        title="Equipment Register"
        description="Every maintained asset: where it is, who looks after it and when it is next serviced."
        actions={canManage && (
          <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'form' })}>
            <Plus className="size-4" aria-hidden /> Add Equipment
          </button>
        )}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard icon={Wrench} tone="blue" label="Registered Equipment" value={formatNumber(s?.total)}
          note={s ? `${s.archived} archived` : undefined} />
        <StatCard icon={CircleCheck} tone="green" label="Operational" value={formatNumber(s?.operational)} />
        <StatCard icon={Wrench} tone="amber" label="Under Maintenance" value={formatNumber(s?.under_maintenance)} />
        <StatCard icon={CircleOff} tone="red" label="Out of Service" value={formatNumber(s?.out_of_service)} />
        <StatCard icon={s?.service_overdue ? TriangleAlert : CalendarClock} tone={s?.service_overdue ? 'red' : 'teal'}
          label="Service Overdue" value={formatNumber(s?.service_overdue)}
          note={s ? `${s.service_due_soon} due within ${s.due_soon_days} days` : undefined} />
      </div>

      <div className="mt-4 flex flex-col gap-3">
        <label className="relative">
          <span className="sr-only">Search equipment</span>
          <Search className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-ink-muted" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setOffset(0) }}
            placeholder="Search by ID, name, serial, make, model or location…"
            className="h-11 w-full rounded-xl border border-white bg-white pr-4 pl-12 text-ink shadow-sm placeholder:text-ink-muted"
          />
        </label>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <FilterSelect label="Filter by category" value={category} options={CATEGORY_OPTIONS} onChange={resetPage(setCategory)} />
          <FilterSelect label="Filter by status" value={status} options={STATUS_OPTIONS} onChange={resetPage(setStatus)} />
          <FilterSelect label="Filter by service" value={service} options={SERVICE_OPTIONS} onChange={resetPage(setService)} />
          <FilterSelect label="Filter by facility" value={facility} options={facilityOptions} onChange={resetPage(setFacility)} />
          <FilterSelect label="Register view" value={view} options={VIEW_OPTIONS} onChange={resetPage(setView)} />
        </div>
      </div>

      {actionError && <div className="mt-4"><FormError message={actionError} /></div>}

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader title={archived ? 'Archived Equipment' : 'Equipment'}
            subtitle={list.data ? `${formatNumber(list.data.total)} ${list.data.total === 1 ? 'asset' : 'assets'}` : undefined} />
          {list.error && !list.data ? (
            <ErrorState message={list.error.message} onRetry={list.refetch} />
          ) : !list.data ? (
            <LoadingState />
          ) : items.length === 0 ? (
            <EmptyState title={filtered ? 'No equipment matches your filters' : archived ? 'No archived equipment' : 'No equipment registered yet'}>
              {canManage && !filtered && !archived && 'Use “Add Equipment” to register the first asset.'}
            </EmptyState>
          ) : (
            <>
              {/* Phones: one tappable card per asset. */}
              <ul className="space-y-2 md:hidden">
                {items.map((e) => (
                  <li key={e.id}>
                    <button type="button" onClick={() => select(e.id)} aria-pressed={e.id === selectedId}
                      className={clsx('w-full rounded-xl border p-3 text-left transition',
                        e.id === selectedId ? 'border-accent bg-sky-50/70' : 'border-line bg-white hover:bg-surface-muted')}>
                      <span className="flex items-start justify-between gap-2">
                        <span className="min-w-0">
                          <span className="block font-mono text-sm font-bold text-ink">{e.code}</span>
                          <span className="block truncate text-sm text-ink">{e.name}</span>
                        </span>
                        <StatusBadge status={e.status} label={EQUIPMENT_STATUS_LABELS[e.status]} tone={equipmentTone(e.status)} />
                      </span>
                      <span className="mt-1.5 flex justify-between gap-2 text-xs">
                        <span className="truncate text-ink-muted">{[e.facility, e.location].filter(Boolean).join(' · ')}</span>
                        <span className={clsx('shrink-0', SERVICE_TEXT[e.service_state])}>{serviceText(e)}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>

              <div className="relative -mx-2 hidden overflow-x-auto md:block">
                <table className="w-full min-w-[600px] text-left text-sm whitespace-nowrap">
                  <thead>
                    <tr className="bg-surface-muted text-ink">
                      <th scope="col" className="rounded-l-xl px-3 py-2.5 font-semibold">Equipment ID</th>
                      <th scope="col" className="px-3 py-2.5 font-semibold">Equipment</th>
                      <th scope="col" className="px-3 py-2.5 font-semibold">Status</th>
                      {/* Technician is in the detail panel; the column only fits on very wide screens. */}
                      <th scope="col" className="hidden px-3 py-2.5 font-semibold 2xl:table-cell">Technician</th>
                      <th scope="col" className="rounded-r-xl px-3 py-2.5 font-semibold">Next service</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((e) => (
                      <tr key={e.id} className={clsx('border-b border-line last:border-0', e.id === selectedId && 'bg-sky-50/70')}>
                        <td className="px-3 py-2.5">
                          <button type="button" onClick={() => select(e.id)} aria-pressed={e.id === selectedId}
                            className="font-mono font-semibold text-ink hover:text-primary">
                            {e.code}
                          </button>
                        </td>
                        {/* Wraps (the rest of the row stays on one line) so the table fits beside the details. */}
                        <td className="px-3 py-2.5 whitespace-normal">
                          <p className="font-medium text-ink">{e.name}</p>
                          <p className="text-xs text-ink-muted">
                            {[CATEGORY_LABELS[e.category], e.facility, e.location].filter(Boolean).join(' · ')}
                          </p>
                        </td>
                        <td className="px-3 py-2.5">
                          <StatusBadge status={e.status} label={EQUIPMENT_STATUS_LABELS[e.status]} tone={equipmentTone(e.status)} />
                        </td>
                        <td className="hidden px-3 py-2.5 2xl:table-cell">
                          {e.assigned_technician?.full_name ?? <span className="text-ink-muted">Unassigned</span>}
                        </td>
                        <td className="px-3 py-2.5">
                          <p className={SERVICE_TEXT[e.service_state]}>{serviceText(e)}</p>
                          {e.next_service_on && <p className="text-xs text-ink-muted">{formatDate(e.next_service_on)}</p>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun="assets" onChange={setOffset} />
            </>
          )}
        </Card>

        <div ref={detailRef} className="scroll-mt-20">
          {selectedId != null && (
            <EquipmentDetailPanel
              equipmentId={selectedId}
              version={version}
              canManage={canManage}
              onEdit={(e) => setDialog({ kind: 'form', equipment: e })}
              onArchive={(e) => setDialog({ kind: 'archive', equipment: e })}
              onRestore={restore}
            />
          )}
        </div>
      </div>

      {dialog?.kind === 'form' && (
        <EquipmentFormModal
          equipment={dialog.equipment}
          onClose={() => setDialog(null)}
          onSaved={(e) => {
            setDialog(null)
            setSelected(e.id)
            reload()
            toast.success(dialog.equipment ? `${e.code} updated` : `${e.code} registered`)
          }}
        />
      )}
      {dialog?.kind === 'archive' && (
        <ArchiveEquipmentModal
          equipment={dialog.equipment}
          onClose={() => setDialog(null)}
          onDone={(e) => {
            setDialog(null)
            reload()
            toast.success(`${e.code} archived`)
          }}
        />
      )}
    </>
  )
}
