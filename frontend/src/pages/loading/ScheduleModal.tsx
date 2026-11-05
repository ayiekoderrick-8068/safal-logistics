import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { a11y } from '../../components/ui/formA11y'
import { Modal } from '../../components/ui/Modal'
import { LoadingState } from '../../components/ui/States'
import { useApi } from '../../hooks/useApi'
import { api, ApiError } from '../../lib/api'
import { isValidZonedInput, toZonedInput, zonedInputToIso } from '../../lib/time'
import type { Bay, Page, Schedule, Truck } from '../../lib/types'

const DURATIONS = [30, 45, 60, 90, 120, 150, 180, 240]

const schema = z.object({
  truck_id: z.string().min(1, 'Select a truck'),
  bay_id: z.string().min(1, 'Select a loading bay'),
  start: z.string().refine(isValidZonedInput, 'Enter a start date and time'),
  duration: z.string(),
  notes: z.string().max(500, 'Keep notes under 500 characters'),
})
type Values = z.infer<typeof schema>

function nextQuarterHour(): string {
  const d = new Date(Math.ceil(Date.now() / 900_000) * 900_000)
  return toZonedInput(d)
}

interface Props {
  truckId?: number
  onClose: () => void
  onSaved: (s: Schedule) => void
}

export function ScheduleModal(props: Props) {
  const trucks = useApi<Page<Truck>>('/trucks?status=available&limit=100')
  const bays = useApi<Bay[]>('/bays')
  const error = trucks.error ?? bays.error
  return (
    <Modal title="Schedule Loading" description="Book a loading bay for a truck. Times are in Nairobi time (EAT)." onClose={props.onClose}>
      {trucks.data && bays.data ? (
        // Mount the form only once options exist so default selections (e.g. ?truck=) apply.
        <ScheduleForm {...props} trucks={trucks.data.items} bays={bays.data} />
      ) : error ? (
        <FormError message={error.message} />
      ) : (
        <LoadingState />
      )}
    </Modal>
  )
}

function ScheduleForm({ truckId, onClose, onSaved, trucks, bays }: Props & { trucks: Truck[]; bays: Bay[] }) {
  const [serverError, setServerError] = useState<string | null>(null)
  const activeBays = bays.filter((b) => b.is_active)
  const preselect = truckId && trucks.some((t) => t.id === truckId) ? String(truckId) : ''

  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { truck_id: preselect, bay_id: '', start: nextQuarterHour(), duration: '90', notes: '' },
  })

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    const start = zonedInputToIso(v.start)
    const end = new Date(new Date(start).getTime() + Number(v.duration) * 60_000).toISOString()
    try {
      const s = await api<Schedule>('/schedules', {
        method: 'POST',
        body: JSON.stringify({
          truck_id: Number(v.truck_id), bay_id: Number(v.bay_id),
          scheduled_start: start, scheduled_end: end, notes: v.notes.trim() || null,
        }),
      })
      onSaved(s)
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not create the booking.')
    }
  })

  const noTrucks = trucks.length === 0
  return (
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <Field id="sched-truck" label="Truck" error={errors.truck_id?.message}
          hint={noTrucks ? 'No available trucks. Trucks in maintenance or on a trip cannot be booked.' : undefined}>
          <select {...a11y('sched-truck', errors.truck_id?.message, !!noTrucks)} {...register('truck_id')} className={inputClass}>
            <option value="">Select truck…</option>
            {trucks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.registration}{t.driver ? ` — ${t.driver.label}` : ''}
              </option>
            ))}
          </select>
        </Field>
        <Field id="sched-bay" label="Loading bay" error={errors.bay_id?.message}
          hint={activeBays.length === 0 ? 'No active bays — add a bay first.' : undefined}>
          <select {...a11y('sched-bay', errors.bay_id?.message)} {...register('bay_id')} className={inputClass}>
            <option value="">Select bay…</option>
            {activeBays.map((b) => (
              <option key={b.id} value={b.id}>{b.name} (target {b.effective_target_minutes} min)</option>
            ))}
          </select>
        </Field>
        <div className="grid gap-4 sm:grid-cols-[1fr_160px]">
          <Field id="sched-start" label="Start" error={errors.start?.message}>
            <input type="datetime-local" {...a11y('sched-start', errors.start?.message)} {...register('start')} className={inputClass} />
          </Field>
          <Field id="sched-duration" label="Booked for">
            <select id="sched-duration" {...register('duration')} className={inputClass}>
              {DURATIONS.map((m) => (
                <option key={m} value={m}>{m < 60 ? `${m} min` : `${m / 60} h`}</option>
              ))}
            </select>
          </Field>
        </div>
        <Field id="sched-notes" label="Notes (optional)" error={errors.notes?.message}>
          <textarea {...a11y('sched-notes', errors.notes?.message)} {...register('notes')} rows={2}
            className={`${inputClass} h-auto py-2`} />
        </Field>
        <FormActions submitLabel="Book bay" submitting={isSubmitting} onCancel={onClose} />
      </form>
  )
}
