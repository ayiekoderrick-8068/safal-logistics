import { PackageMinus, PackagePlus } from 'lucide-react'
import { useState } from 'react'
import { btnSmallGhost } from '../../../components/ui/buttons'
import { useToast } from '../../../components/ui/toastContext'
import { useApi } from '../../../hooks/useApi'
import { money, notifyMaintenanceChanged, qty, useMaintenanceAccess, type WorkOrderParts } from '../../../lib/maintenance'
import { IssuePartsModal, ReturnPartsModal } from './PartsModals'

/** Parts consumed by one work order (issues minus returns), with issue/return actions. */
export function WorkOrderPartsSection({ woId, woNumber, version }: { woId: number; woNumber: string; version: number }) {
  const toast = useToast()
  const { can } = useMaintenanceAccess()
  const [nonce, setNonce] = useState(0)
  const [dialog, setDialog] = useState<'issue' | 'return' | null>(null)
  const { data } = useApi<WorkOrderParts>(`/maintenance/work-orders/${woId}/parts?v=${version}-${nonce}`)
  if (!data?.lines) return null
  const closed = data.work_order.status === 'completed' || data.work_order.status === 'cancelled'
  const outstanding = data.lines.some((l) => l.net > 0)
  const canReturn = outstanding && (data.can_issue || (closed && can('parts.consume')))
  const done = (message: string) => {
    setDialog(null)
    setNonce((n) => n + 1)
    notifyMaintenanceChanged()
    toast.success(message)
  }

  return (
    <section className="mt-5" aria-labelledby={`wo-parts-${woId}`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 id={`wo-parts-${woId}`} className="text-sm font-bold text-ink">Parts consumed</h3>
        <span className="flex gap-2">
          {data.can_issue && (
            <button type="button" className={`${btnSmallGhost} h-9 px-3 text-sm`} onClick={() => setDialog('issue')}>
              <PackageMinus className="size-4" aria-hidden /> Issue parts
            </button>
          )}
          {canReturn && (
            <button type="button" className={`${btnSmallGhost} h-9 px-3 text-sm`} onClick={() => setDialog('return')}>
              <PackagePlus className="size-4" aria-hidden /> Return
            </button>
          )}
        </span>
      </div>
      {data.lines.length === 0 ? (
        <p className="text-sm text-ink-muted">No parts issued to this work order.</p>
      ) : (
        <>
          <ul className="divide-y divide-line text-sm">
            {data.lines.map((l) => (
              <li key={l.part.id} className="flex items-start justify-between gap-3 py-2">
                <span className="min-w-0">
                  <span className="font-mono font-semibold text-ink">{l.part.part_number}</span>
                  <span className="block truncate text-ink-muted">{l.part.name}</span>
                  {l.returned > 0 && <span className="block text-xs text-ink-muted">issued {qty(l.issued, l.part.unit)}, returned {qty(l.returned, l.part.unit)}</span>}
                </span>
                <span className="shrink-0 text-right">
                  <span className="block font-semibold text-ink">{qty(l.net, l.part.unit)}</span>
                  <span className="block text-xs text-ink-muted">{money(l.cost)}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1 flex justify-between border-t border-line pt-2 text-sm font-semibold text-ink">
            <span>Parts cost</span>
            <span>{data.total_cost == null ? 'Some parts have no cost' : money(data.total_cost)}</span>
          </p>
        </>
      )}
      {dialog === 'issue' && <IssuePartsModal woId={woId} woNumber={woNumber} onClose={() => setDialog(null)}
        onDone={() => done(`Parts issued to ${woNumber}`)} />}
      {dialog === 'return' && <ReturnPartsModal parts={data} onClose={() => setDialog(null)}
        onDone={() => done(`Parts returned from ${woNumber}`)} />}
    </section>
  )
}
