import { Filter, RotateCcw } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { btnPrimary, btnSecondary, inputClass } from '../../components/ui/buttons'
import { Card } from '../../components/ui/Card'
import { FormError } from '../../components/ui/Form'
import { useApi } from '../../hooks/useApi'
import { DELAY_CAUSE_LABELS } from '../../lib/format'
import type { Bay, Driver, Page, Route, Truck } from '../../lib/types'
import { EMPTY_FILTERS, PERIOD_LABELS, validate, type Period, type ReportFilterState } from './filters'

function Select({ id, label, value, onChange, children }: {
  id: string; label: string; value: string; onChange: (v: string) => void; children: ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-semibold text-ink">{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={`${inputClass} h-10 text-sm`}>
        {children}
      </select>
    </div>
  )
}

export function ReportFiltersPanel({ applied, onApply }: {
  applied: ReportFilterState
  onApply: (f: ReportFilterState) => void
}) {
  const [draft, setDraft] = useState(applied)
  // Re-sync the draft only when the *applied* filters actually change (e.g. back/forward
  // navigation). Compare by value: the parent builds a new object on every render.
  const appliedKey = JSON.stringify(applied)
  const [lastApplied, setLastApplied] = useState(appliedKey)
  if (lastApplied !== appliedKey) {
    setLastApplied(appliedKey)
    setDraft(applied)
  }
  const [error, setError] = useState<string | null>(null)
  const trucks = useApi<Page<Truck>>('/trucks?limit=100')
  const drivers = useApi<Driver[]>('/drivers')
  const bays = useApi<Bay[]>('/bays')
  const routes = useApi<Route[]>('/routes')
  const set = (patch: Partial<ReportFilterState>) => setDraft((d) => ({ ...d, ...patch }))

  function submit(e: FormEvent) {
    e.preventDefault()
    const problem = validate(draft)
    setError(problem)
    if (!problem) onApply(draft)
  }

  return (
    <Card className="mb-4">
      <form onSubmit={submit} noValidate aria-label="Report filters">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-ink">Report Filters</h2>
            <p className="text-sm text-ink-muted">Combine a period with any of the filters below. Applies to KPIs, charts, tables and exports.</p>
          </div>
        </div>
        <FormError message={error} />
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8">
          <Select id="f-period" label="Period" value={draft.period} onChange={(v) => set({ period: v as Period })}>
            {Object.entries(PERIOD_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
          {draft.period === 'custom' && (
            <>
              <div>
                <label htmlFor="f-start" className="mb-1 block text-xs font-semibold text-ink">From</label>
                <input id="f-start" type="date" value={draft.start} onChange={(e) => set({ start: e.target.value })}
                  className={`${inputClass} h-10 text-sm`} />
              </div>
              <div>
                <label htmlFor="f-end" className="mb-1 block text-xs font-semibold text-ink">To</label>
                <input id="f-end" type="date" value={draft.end} onChange={(e) => set({ end: e.target.value })}
                  className={`${inputClass} h-10 text-sm`} />
              </div>
            </>
          )}
          <Select id="f-truck" label="Truck" value={draft.truck_id} onChange={(v) => set({ truck_id: v })}>
            <option value="">All trucks</option>
            {trucks.data?.items.map((t) => <option key={t.id} value={t.id}>{t.registration}</option>)}
          </Select>
          <Select id="f-driver" label="Driver" value={draft.driver_id} onChange={(v) => set({ driver_id: v })}>
            <option value="">All drivers</option>
            {drivers.data?.map((d) => <option key={d.id} value={d.id}>{d.full_name}</option>)}
          </Select>
          <Select id="f-bay" label="Loading bay" value={draft.bay_id} onChange={(v) => set({ bay_id: v })}>
            <option value="">All bays</option>
            {bays.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </Select>
          <Select id="f-route" label="Route" value={draft.route_id} onChange={(v) => set({ route_id: v })}>
            <option value="">All routes</option>
            {routes.data?.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </Select>
          <Select id="f-status" label="Dispatch status" value={draft.dispatch_status} onChange={(v) => set({ dispatch_status: v })}>
            <option value="">All statuses</option>
            <option value="in_transit">In transit</option>
            <option value="delivered">Delivered</option>
            <option value="delayed">Flagged delayed</option>
            <option value="pending">Pending</option>
            <option value="cancelled">Cancelled</option>
          </Select>
          <Select id="f-cause" label="Delay category" value={draft.delay_cause} onChange={(v) => set({ delay_cause: v })}>
            <option value="">All categories</option>
            {Object.entries(DELAY_CAUSE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-3">
          <button type="button" className={`${btnSecondary} border-line`}
            onClick={() => { setDraft(EMPTY_FILTERS); setError(null); onApply(EMPTY_FILTERS) }}>
            <RotateCcw className="size-4" aria-hidden /> Clear Filters
          </button>
          <button type="submit" className={btnPrimary}>
            <Filter className="size-4" aria-hidden /> Apply Filters
          </button>
        </div>
      </form>
    </Card>
  )
}
