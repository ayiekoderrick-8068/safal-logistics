/** Form building blocks shared by the maintenance dialogs. */
import { useState, type FormEvent, type ReactNode } from 'react'
import { inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { Modal } from '../../components/ui/Modal'
import { useApi } from '../../hooks/useApi'
import { ApiError } from '../../lib/api'
import { MAINTENANCE_ROLE_LABELS } from '../../lib/format'
import type { Equipment, EquipmentOptions } from '../../lib/maintenance'
import type { Page } from '../../lib/types'

/** Small form-in-a-modal: runs `action`, shows the server's message on failure. */
export function ActionModal<T>({
  title, description, submitLabel, onClose, onDone, action, validate, wide, children,
}: {
  title: string
  description?: string
  submitLabel: string
  onClose: () => void
  onDone: (result: T) => void
  action: () => Promise<T>
  validate?: () => string | null
  wide?: boolean
  children: ReactNode
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    const problem = validate?.()
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    try {
      onDone(await action())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
      setBusy(false)
    }
  }
  return (
    <Modal title={title} description={description} onClose={onClose} wide={wide}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={error} />
        {children}
        <FormActions submitLabel={submitLabel} submitting={busy} onCancel={onClose} />
      </form>
    </Modal>
  )
}

export function TechnicianSelect({ id, value, onChange, label = 'Assigned technician' }: {
  id: string
  value: string
  onChange: (v: string) => void
  label?: string
}) {
  const technicians = useApi<EquipmentOptions>('/maintenance/equipment/options').data?.technicians ?? []
  return (
    <Field id={id} label={label}>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
        <option value="">Unassigned</option>
        {technicians.map((t) => (
          <option key={t.id} value={t.id}>{t.full_name} · {MAINTENANCE_ROLE_LABELS[t.maintenance_role]}</option>
        ))}
      </select>
    </Field>
  )
}

export function EquipmentSelect({ value, onChange, id = 'pm-equipment' }: {
  value: string
  onChange: (v: string) => void
  id?: string
}) {
  const { data } = useApi<Page<Equipment>>('/maintenance/equipment?limit=100')
  return (
    <Field id={id} label="Equipment"
      hint={data && data.total > data.items.length ? `Showing the first ${data.items.length} of ${data.total}.` : undefined}>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
        <option value="">Choose equipment…</option>
        {data?.items.map((e) => <option key={e.id} value={e.id}>{e.code} · {e.name}</option>)}
      </select>
    </Field>
  )
}
