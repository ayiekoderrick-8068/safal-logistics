import { useState, type FormEvent } from 'react'
import { inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { a11y } from '../../components/ui/formA11y'
import { Modal } from '../../components/ui/Modal'
import { api, ApiError } from '../../lib/api'
import { isValidZonedInput, toZonedInput, zonedInputToIso } from '../../lib/time'
import type { Schedule } from '../../lib/types'
import { EVENT_LABELS, type ScheduleEvent } from './events'

/** Records one workflow timestamp; defaults to now but can be corrected (e.g. entered late). */
export function EventModal({
  schedule,
  event,
  onClose,
  onSaved,
}: {
  schedule: Schedule
  event: ScheduleEvent
  onClose: () => void
  onSaved: (s: Schedule) => void
}) {
  const [value, setValue] = useState(() => toZonedInput(new Date()))
  const [error, setError] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string>()
  const [busy, setBusy] = useState(false)
  const labels = EVENT_LABELS[event]

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!isValidZonedInput(value)) {
      setFieldError('Enter a date and time')
      return
    }
    setFieldError(undefined)
    setBusy(true)
    setError(null)
    try {
      const saved = await api<Schedule>(`/schedules/${schedule.id}/events`, {
        method: 'POST',
        body: JSON.stringify({ event, at: zonedInputToIso(value) }),
      })
      onSaved(saved)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not record the time.')
      setBusy(false)
    }
  }

  return (
    <Modal title={labels.action} description={`${schedule.truck.label} at ${schedule.bay.label}`} onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={error} />
        <Field id="event-at" label={`${labels.field} (EAT)`} error={fieldError}
          hint="Defaults to now. Adjust if you are recording it after the fact.">
          <input type="datetime-local" {...a11y('event-at', fieldError, true)} value={value}
            onChange={(e) => setValue(e.target.value)} className={inputClass} />
        </Field>
        <FormActions submitLabel={labels.action} submitting={busy} onCancel={onClose} />
      </form>
    </Modal>
  )
}
