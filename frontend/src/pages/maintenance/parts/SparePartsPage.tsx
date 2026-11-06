import clsx from 'clsx'
import { Boxes, ClipboardCheck, PackageMinus, PackagePlus, PackageX, Pencil, Plus, Search, Wallet } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { btnPrimary, btnSmallGhost, btnSmallPrimary } from '../../../components/ui/buttons'
import { Card, CardHeader } from '../../../components/ui/Card'
import { PageHeader } from '../../../components/ui/PageHeader'
import { Pagination } from '../../../components/ui/Pagination'
import { StatCard } from '../../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../../components/ui/States'
import { StatusBadge } from '../../../components/ui/StatusBadge'
import { useToast } from '../../../components/ui/toastContext'
import { useApi } from '../../../hooks/useApi'
import { useDebounced } from '../../../hooks/useDebounced'
import { formatDateTime, formatNumber } from '../../../lib/format'
import {
  money,
  moneyCompact,
  MOVEMENT_LABELS,
  notifyMaintenanceChanged,
  qty,
  STOCK_STATE_LABELS,
  useMaintenanceAccess,
  type PartsSummary,
  type SparePart,
  type SparePartDetail,
  type StockState,
} from '../../../lib/maintenance'
import type { Tone } from '../../../lib/statusColors'
import type { Page } from '../../../lib/types'
import { CountStockModal, PartFormModal, ReceiveStockModal } from './PartsModals'

const PAGE_SIZE = 12
const stockTone = (s: StockState): Tone => (s === 'out_of_stock' ? 'red' : s === 'low' ? 'amber' : 'green')
const VIEWS = [['all', 'All parts', ''], ['attention', 'Needs reordering', 'attention'], ['out', 'Out of stock', 'out']] as const
type Dialog = { kind: 'new' } | { kind: 'edit' | 'receive' | 'count'; part: SparePart } | null

export function SparePartsPage() {
  const toast = useToast()
  const { can } = useMaintenanceAccess()
  const canManage = can('parts.manage')
  const [params, setParams] = useSearchParams()
  const view = VIEWS.find(([v]) => v === params.get('view')) ?? VIEWS[0]
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [version, setVersion] = useState(0)
  const detailRef = useRef<HTMLDivElement>(null)
  const q = useDebounced(query.trim())

  const search = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (view[2]) search.set('stock', view[2])
  if (q) search.set('q', q)
  const list = useApi<Page<SparePart>>(`/maintenance/parts?${search}`)
  const summary = useApi<PartsSummary>(`/maintenance/parts/summary?v=${version}`)
  const s = summary.data
  const items = list.data?.items ?? []
  const selectedId = selected && items.some((p) => p.id === selected) ? selected : (items[0]?.id ?? null)
  const done = (message: string, id?: number) => {
    setDialog(null)
    if (id) setSelected(id)
    setVersion((v) => v + 1)
    notifyMaintenanceChanged()
    toast.success(message)
  }
  function select(id: number) {
    setSelected(id)
    if (window.matchMedia?.('(max-width: 1279px)').matches) {
      requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    }
  }

  return (
    <>
      <PageHeader
        title="Spare Parts"
        description="Stores catalogue, stock levels, reorder alerts and every stock movement."
        actions={canManage && (
          <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'new' })}>
            <Plus className="size-4" aria-hidden /> Add part
          </button>
        )}
      />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <StatCard compact icon={Boxes} tone="blue" label="Active Parts" value={formatNumber(s?.active_parts)} />
        <StatCard compact icon={PackageMinus} tone="amber" label="Low Stock" value={formatNumber(s?.low_stock)} note="At or below reorder level" />
        <StatCard compact icon={PackageX} tone="red" label="Out of Stock" value={formatNumber(s?.out_of_stock)} />
        {/* Compact value: a full "KES 114,000.00" does not fit a half-width card on phones. */}
        <StatCard compact icon={Wallet} tone="teal" label="Stock Value" value={s ? moneyCompact(s.stock_value) : '…'}
          note={s ? `${money(s.stock_value)}${s.parts_without_cost ? ` · ${s.parts_without_cost} without a cost excluded` : ''}` : undefined} />
      </div>

      {s && s.low_stock + s.out_of_stock > 0 && view[0] === 'all' && (
        <div role="status" className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span><strong className="font-semibold">{s.low_stock + s.out_of_stock} {s.low_stock + s.out_of_stock === 1 ? 'part needs' : 'parts need'} reordering</strong>
            {s.out_of_stock ? ` — ${s.out_of_stock} out of stock` : ''}.</span>
          <button type="button" className="font-semibold underline" onClick={() => { setOffset(0); setParams({ view: 'attention' }) }}>Show them</button>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {VIEWS.map(([v, label]) => (
          <button key={v} type="button" aria-pressed={view[0] === v} onClick={() => { setOffset(0); setParams({ view: v }, { replace: true }) }}
            className={clsx('h-9 rounded-full border px-3.5 text-sm font-semibold',
              view[0] === v ? 'border-primary bg-primary text-white' : 'border-white bg-white text-ink hover:bg-surface-muted')}>
            {label}
          </button>
        ))}
        <label className="relative w-full sm:ml-auto sm:w-80">
          <span className="sr-only">Search spare parts</span>
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-ink-muted" aria-hidden />
          <input type="search" value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0) }}
            placeholder="Part number, name, category or bin…"
            className="h-10 w-full rounded-xl border border-white bg-white pr-3 pl-10 text-sm text-ink shadow-sm placeholder:text-ink-muted" />
        </label>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <Card>
          <CardHeader title={view[1]} subtitle={list.data ? `${formatNumber(list.data.total)} found` : undefined} />
          {list.error && !list.data ? (
            <ErrorState message={list.error.message} onRetry={list.refetch} />
          ) : !list.data ? (
            <LoadingState />
          ) : items.length === 0 ? (
            <EmptyState title={view[0] === 'all' && !q ? 'No spare parts yet' : 'No parts in this view'}>
              {canManage && view[0] === 'all' && !q && 'Use “Add part” to build the stores catalogue.'}
            </EmptyState>
          ) : (
            <>
              <ul className="space-y-2">
                {items.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => select(p.id)} aria-pressed={p.id === selectedId}
                      className={clsx('flex w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-xl border p-3 text-left transition',
                        p.id === selectedId ? 'border-accent bg-sky-50/70' : 'border-line bg-white hover:bg-surface-muted')}>
                      <span className="min-w-0">
                        <span className="block font-mono text-sm font-bold text-ink">{p.part_number}</span>
                        <span className="block truncate text-sm text-ink">{p.name}</span>
                        <span className="block text-xs text-ink-muted">{[p.category, p.location].filter(Boolean).join(' · ') || '—'}</span>
                      </span>
                      <span className="text-right">
                        <span className="block font-semibold text-ink">{qty(p.on_hand, p.unit)}</span>
                        <StatusBadge status={p.stock_state} label={STOCK_STATE_LABELS[p.stock_state]} tone={stockTone(p.stock_state)} />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun="parts" onChange={setOffset} />
            </>
          )}
        </Card>

        <div ref={detailRef} className="scroll-mt-20">
          {selectedId != null && <PartPanel id={selectedId} version={version} canManage={canManage}
            onOpen={(kind, part) => setDialog({ kind, part })} />}
        </div>
      </div>

      {dialog?.kind === 'new' && <PartFormModal onClose={() => setDialog(null)} onDone={(p) => done(`${p.part_number} added`, p.id)} />}
      {dialog?.kind === 'edit' && <PartFormModal part={dialog.part} onClose={() => setDialog(null)} onDone={(p) => done(`${p.part_number} updated`)} />}
      {dialog?.kind === 'receive' && <ReceiveStockModal part={dialog.part} onClose={() => setDialog(null)}
        onDone={(p) => done(`${p.part_number}: now ${qty(p.on_hand, p.unit)}`)} />}
      {dialog?.kind === 'count' && <CountStockModal part={dialog.part} onClose={() => setDialog(null)}
        onDone={(p) => done(`${p.part_number}: count recorded, ${qty(p.on_hand, p.unit)}`)} />}
    </>
  )
}

function PartPanel({ id, version, canManage, onOpen }: {
  id: number; version: number; canManage: boolean; onOpen: (kind: 'edit' | 'receive' | 'count', p: SparePart) => void
}) {
  const { data: p, error, refetch } = useApi<SparePartDetail>(`/maintenance/parts/${id}?v=${version}`)
  if (error && !p) return <Card><ErrorState message={error.message} onRetry={refetch} /></Card>
  if (!p) return <Card><LoadingState /></Card>
  const rows: [string, string | null][] = [
    ['On hand', qty(p.on_hand, p.unit)],
    ['Reorder level', qty(p.reorder_level, p.unit)],
    ['Reorder quantity', p.reorder_quantity != null ? qty(p.reorder_quantity, p.unit) : null],
    ['Unit cost', p.unit_cost != null ? money(p.unit_cost) : null],
    ['Stock value', p.stock_value != null ? money(p.stock_value) : null],
    ['Used, last 90 days', qty(p.issued_last_90_days, p.unit)],
    ['Location', p.location],
    ['Supplier', p.supplier],
  ]
  return (
    <Card className="self-start">
      <CardHeader title={<span className="font-mono">{p.part_number}</span>} subtitle={p.name}
        action={<StatusBadge status={p.stock_state} label={STOCK_STATE_LABELS[p.stock_state]} tone={stockTone(p.stock_state)} />} />
      {canManage && (
        <div className="mb-4 flex flex-wrap gap-2">
          <button type="button" className={`${btnSmallPrimary} h-10 px-4 text-sm`} onClick={() => onOpen('receive', p)}>
            <PackagePlus className="size-4" aria-hidden /> Receive
          </button>
          <button type="button" className={`${btnSmallGhost} h-10 px-3 text-sm`} onClick={() => onOpen('count', p)}>
            <ClipboardCheck className="size-4" aria-hidden /> Stock count
          </button>
          <button type="button" className={`${btnSmallGhost} h-10 px-3 text-sm`} onClick={() => onOpen('edit', p)}>
            <Pencil className="size-4" aria-hidden /> Edit
          </button>
        </div>
      )}
      <dl className="divide-y divide-line text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 py-2">
            <dt className="text-ink-muted">{k}</dt>
            <dd className="text-right font-medium text-ink">{v ?? <span className="font-normal text-ink-muted">—</span>}</dd>
          </div>
        ))}
      </dl>
      <h3 className="mt-5 mb-2 text-sm font-bold text-ink">Stock movements</h3>
      {p.movements.length === 0 ? <p className="text-sm text-ink-muted">No movements yet.</p> : (
        <ol className="divide-y divide-line text-sm" aria-label="Stock movements">
          {p.movements.map((m) => (
            <li key={m.id} className="flex items-start justify-between gap-3 py-2">
              <span className="min-w-0">
                <span className="font-medium text-ink">{MOVEMENT_LABELS[m.kind]}</span>
                {m.work_order && <> · <Link to={`/maintenance/work-orders?view=all&wo=${m.work_order.id}`} className="font-mono text-primary hover:underline">{m.work_order.number}</Link></>}
                {(m.reference || m.note) && <span className="block truncate text-xs text-ink-muted">{[m.reference, m.note].filter(Boolean).join(' · ')}</span>}
                <span className="block text-xs text-ink-muted">{formatDateTime(m.occurred_at)}{m.actor && ` · ${m.actor.full_name}`}</span>
              </span>
              <span className="shrink-0 text-right">
                <span className={clsx('block font-semibold', m.quantity < 0 ? 'text-red-600' : 'text-emerald-700')}>
                  {m.quantity > 0 ? '+' : ''}{qty(m.quantity, p.unit)}
                </span>
                <span className="block text-xs text-ink-muted">balance {qty(m.balance_after, p.unit)}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}
