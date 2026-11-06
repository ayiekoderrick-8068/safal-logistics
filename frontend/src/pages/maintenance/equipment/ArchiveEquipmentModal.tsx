import { useState, type FormEvent } from 'react'
import { inputClass } from '../../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../../components/ui/Form'
import { Modal } from '../../../components/ui/Modal'
import { api, ApiError } from '../../../lib/api'
import type { Equipment } from '../../../lib/maintenance'

/** Archiving keeps the asset and its history; it only leaves the active register. */
export function ArchiveEquipmentModal({
  equipment,
  onClose,
  onDone,
}: {
  equipment: Equipment
  onClose: () => void
  onDone: (e: Equipment) => void
}) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    if (reason.trim().length < 3) {
      setError('Give a short reason (at least 3 characters).')
      return
    }
    setBusy(true)
    setError(null)
    try {
      onDone(await api<Equipment>(`/maintenance/equipment/${equipment.id}/archive`, {
        method: 'POST', body: JSON.stringify({ reason: reason.trim() }),
      }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not archive the equipment.')
      setBusy(false)
    }
  }

  return (
    <Modal title={`Archive ${equipment.code}`}
      description="The equipment leaves the active register. Its history is kept and it can be restored."
      onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={error} />
        <Field id="archive-reason" label="Reason">
          <input id="archive-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255}
            placeholder="e.g. Decommissioned, replaced by CNV-009" className={inputClass} autoFocus />
        </Field>
        <FormActions submitLabel="Archive equipment" submitting={busy} onCancel={onClose} />
      </form>
    </Modal>
  )
}
