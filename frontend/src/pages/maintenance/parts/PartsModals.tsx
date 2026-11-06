import { useState } from 'react'
import { inputClass } from '../../../components/ui/buttons'
import { Field } from '../../../components/ui/Form'
import { useApi } from '../../../hooks/useApi'
import {
  newRequestId,
  qty,
  quantityProblem,
  send,
  UNIT_LABELS,
  type SparePart,
  type StockUnit,
  type WorkOrderParts,
} from '../../../lib/maintenance'
import type { Page } from '../../../lib/types'
import { ActionModal } from '../forms'

const optional = (s: string) => (s.trim() ? s.trim() : null)
const money = (s: string) => (s.trim() ? s.trim() : null)

export function PartFormModal({ part, onClose, onDone }: { part?: SparePart; onClose: () => void; onDone: (p: SparePart) => void }) {
  const editing = !!part
  const [number, setNumber] = useState(part?.part_number ?? '')
  const [name, setName] = useState(part?.name ?? '')
  const [category, setCategory] = useState(part?.category ?? '')
  const [unit, setUnit] = useState<StockUnit>(part?.unit ?? 'each')
  const [opening, setOpening] = useState('0')
  const [reorder, setReorder] = useState(String(part?.reorder_level ?? 0))
  const [reorderQty, setReorderQty] = useState(part?.reorder_quantity != null ? String(part.reorder_quantity) : '')
  const [location, setLocation] = useState(part?.location ?? '')
  const [supplier, setSupplier] = useState(part?.supplier ?? '')
  const [cost, setCost] = useState(part?.unit_cost != null ? String(part.unit_cost) : '')
  const common = {
    name: name.trim(), category: optional(category), reorder_level: reorder.trim() || '0',
    reorder_quantity: optional(reorderQty), location: optional(location), supplier: optional(supplier), unit_cost: money(cost),
  }
  return (
    <ActionModal wide title={editing ? `Edit ${part.part_number}` : 'Add spare part'}
      description={editing ? 'Stock levels change only through receipts, issues, returns and counts.' : 'Add a part to the stores catalogue.'}
      submitLabel={editing ? 'Save' : 'Add part'} onClose={onClose} onDone={onDone}
      validate={() => (!editing && !/^[A-Za-z0-9][A-Za-z0-9./_-]{1,39}$/.test(number.trim()) ? 'Enter a part number (letters, numbers, . / _ -).'
        : name.trim().length < 2 ? 'Enter the part name.'
          : quantityProblem(reorder, unit, 'reorder level', true)
            ?? (!editing && opening.trim() !== '0' ? quantityProblem(opening, unit, 'opening quantity') : null)
            ?? (cost.trim() && !(Number(cost) >= 0) ? 'The unit cost must be zero or more.' : null))}
      action={() => editing
        ? send<SparePart>(`/maintenance/parts/${part.id}`, common, 'PATCH')
        : send<SparePart>('/maintenance/parts', { ...common, part_number: number.trim(), unit, opening_quantity: opening.trim() || '0' })}>
      <div className="grid gap-4 sm:grid-cols-[200px_1fr]">
        <Field id="part-number" label="Part number" hint={editing ? 'Cannot be changed.' : 'e.g. BRG-6205'}>
          <input id="part-number" value={number} onChange={(e) => setNumber(e.target.value)} readOnly={editing}
            autoComplete="off" spellCheck={false} className={`${inputClass} uppercase read-only:bg-slate-50`} />
        </Field>
        <Field id="part-name" label="Name">
          <input id="part-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} className={inputClass} />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="part-unit" label="Unit" hint={editing ? 'Cannot be changed.' : undefined}>
          <select id="part-unit" value={unit} disabled={editing} onChange={(e) => setUnit(e.target.value as StockUnit)} className={inputClass}>
            {(Object.entries(UNIT_LABELS) as [StockUnit, string][]).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field id="part-category" label="Category (optional)">
          <input id="part-category" value={category} onChange={(e) => setCategory(e.target.value)} maxLength={60}
            placeholder="Bearings, belts, filters…" className={inputClass} />
        </Field>
        {!editing && (
          <Field id="part-opening" label="Opening stock" hint="Recorded as the first receipt.">
            <input id="part-opening" inputMode="decimal" value={opening} onChange={(e) => setOpening(e.target.value)} className={inputClass} />
          </Field>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="part-reorder" label="Reorder level" hint="Low-stock alert at or below this.">
          <input id="part-reorder" inputMode="decimal" value={reorder} onChange={(e) => setReorder(e.target.value)} className={inputClass} />
        </Field>
        <Field id="part-reorder-qty" label="Reorder quantity (optional)">
          <input id="part-reorder-qty" inputMode="decimal" value={reorderQty} onChange={(e) => setReorderQty(e.target.value)} className={inputClass} />
        </Field>
        <Field id="part-cost" label="Unit cost, KES (optional)">
          <input id="part-cost" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} className={inputClass} />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="part-location" label="Store location (optional)">
          <input id="part-location" value={location} onChange={(e) => setLocation(e.target.value)} maxLength={80}
            placeholder="Store A / Bin 3" className={inputClass} />
        </Field>
        <Field id="part-supplier" label="Supplier (optional)">
          <input id="part-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)} maxLength={120} className={inputClass} />
        </Field>
      </div>
    </ActionModal>
  )
}

export function ReceiveStockModal({ part, onClose, onDone }: { part: SparePart; onClose: () => void; onDone: (p: SparePart) => void }) {
  const [quantity, setQuantity] = useState('')
  const [reference, setReference] = useState('')
  const [cost, setCost] = useState(part.unit_cost != null ? String(part.unit_cost) : '')
  const [requestId] = useState(newRequestId)
  return (
    <ActionModal title={`Receive ${part.part_number}`} description={`${part.name} · ${qty(part.on_hand, part.unit)} on hand`}
      submitLabel="Receive stock" onClose={onClose} onDone={onDone}
      validate={() => quantityProblem(quantity, part.unit)}
      action={() => send<SparePart>(`/maintenance/parts/${part.id}/receive`, {
        quantity: quantity.trim(), reference: optional(reference), unit_cost: money(cost), request_id: requestId,
      })}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="receive-qty" label={`Quantity (${UNIT_LABELS[part.unit].toLowerCase()})`}>
          <input id="receive-qty" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={inputClass} autoFocus />
        </Field>
        <Field id="receive-cost" label="Unit cost, KES (optional)">
          <input id="receive-cost" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} className={inputClass} />
        </Field>
      </div>
      <Field id="receive-ref" label="GRN / delivery note (optional)">
        <input id="receive-ref" value={reference} onChange={(e) => setReference(e.target.value)} maxLength={80} className={inputClass} />
      </Field>
    </ActionModal>
  )
}

export function CountStockModal({ part, onClose, onDone }: { part: SparePart; onClose: () => void; onDone: (p: SparePart) => void }) {
  const [counted, setCounted] = useState(String(part.on_hand))
  const [reason, setReason] = useState('')
  const [requestId] = useState(newRequestId)
  const diff = Number(counted) - part.on_hand
  return (
    <ActionModal title={`Stock count: ${part.part_number}`} description={`${part.name} · recorded ${qty(part.on_hand, part.unit)}`}
      submitLabel="Record count" onClose={onClose} onDone={onDone}
      validate={() => quantityProblem(counted, part.unit, 'counted quantity', true)
        ?? (diff === 0 ? 'The count matches the recorded stock; nothing to adjust.'
          : reason.trim().length < 3 ? 'Give the reason for the difference.' : null)}
      action={() => send<SparePart>(`/maintenance/parts/${part.id}/adjust`, {
        counted_quantity: counted.trim(), reason: reason.trim(), request_id: requestId,
      })}>
      <Field id="count-qty" label="Counted quantity"
        hint={Number.isFinite(diff) && diff !== 0 ? `Adjustment of ${diff > 0 ? '+' : ''}${qty(diff, part.unit)}` : undefined}>
        <input id="count-qty" inputMode="decimal" value={counted} onChange={(e) => setCounted(e.target.value)} className={inputClass} />
      </Field>
      <Field id="count-reason" label="Reason">
        <input id="count-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255}
          placeholder="e.g. Quarterly stock take, damaged items written off" className={inputClass} />
      </Field>
    </ActionModal>
  )
}

export function IssuePartsModal({ woId, woNumber, onClose, onDone }: {
  woId: number; woNumber: string; onClose: () => void; onDone: (r: WorkOrderParts) => void
}) {
  const { data } = useApi<Page<SparePart>>('/maintenance/parts?limit=100')
  const [partId, setPartId] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [note, setNote] = useState('')
  const [requestId] = useState(newRequestId)
  const part = data?.items.find((p) => String(p.id) === partId)
  return (
    <ActionModal title={`Issue parts to ${woNumber}`} description="The stock is deducted immediately and recorded against this work order."
      submitLabel="Issue parts" onClose={onClose} onDone={onDone}
      validate={() => (!part ? 'Choose the part.' : quantityProblem(quantity, part.unit)
        ?? (Number(quantity) > part.on_hand ? `Only ${qty(part.on_hand, part.unit)} in stock.` : null))}
      action={() => send<WorkOrderParts>(`/maintenance/work-orders/${woId}/parts`, {
        part_id: Number(partId), quantity: quantity.trim(), note: optional(note), request_id: requestId,
      })}>
      <Field id="issue-part" label="Part">
        <select id="issue-part" value={partId} onChange={(e) => setPartId(e.target.value)} className={inputClass}>
          <option value="">Choose a part…</option>
          {data?.items.map((p) => (
            <option key={p.id} value={p.id} disabled={p.on_hand <= 0}>
              {p.part_number} · {p.name} ({qty(p.on_hand, p.unit)}{p.location ? `, ${p.location}` : ''})
            </option>
          ))}
        </select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="issue-qty" label={part ? `Quantity (${UNIT_LABELS[part.unit].toLowerCase()})` : 'Quantity'}>
          <input id="issue-qty" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={inputClass} />
        </Field>
        <Field id="issue-note" label="Note (optional)">
          <input id="issue-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={255} className={inputClass} />
        </Field>
      </div>
    </ActionModal>
  )
}

export function ReturnPartsModal({ parts, onClose, onDone }: {
  parts: WorkOrderParts; onClose: () => void; onDone: (r: WorkOrderParts) => void
}) {
  const outstanding = parts.lines.filter((l) => l.net > 0)
  const [partId, setPartId] = useState(outstanding[0] ? String(outstanding[0].part.id) : '')
  const [quantity, setQuantity] = useState('1')
  const [requestId] = useState(newRequestId)
  const line = outstanding.find((l) => String(l.part.id) === partId)
  return (
    <ActionModal title={`Return parts from ${parts.work_order.number}`} description="Unused parts go back into stock."
      submitLabel="Return to stock" onClose={onClose} onDone={onDone}
      validate={() => (!line ? 'Choose the part.' : quantityProblem(quantity, line.part.unit)
        ?? (Number(quantity) > line.net ? `Only ${qty(line.net, line.part.unit)} is outstanding.` : null))}
      action={() => send<WorkOrderParts>(`/maintenance/work-orders/${parts.work_order.id}/parts/return`, {
        part_id: Number(partId), quantity: quantity.trim(), request_id: requestId,
      })}>
      <Field id="return-part" label="Part">
        <select id="return-part" value={partId} onChange={(e) => setPartId(e.target.value)} className={inputClass}>
          {outstanding.map((l) => (
            <option key={l.part.id} value={l.part.id}>{l.part.part_number} · {l.part.name} ({qty(l.net, l.part.unit)} issued)</option>
          ))}
        </select>
      </Field>
      <Field id="return-qty" label="Quantity">
        <input id="return-qty" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={inputClass} />
      </Field>
    </ActionModal>
  )
}
