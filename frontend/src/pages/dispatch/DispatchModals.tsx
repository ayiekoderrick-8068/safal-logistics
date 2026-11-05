import { zodResolver } from '@hookform/resolvers/zod'
import { useState, type FormEvent } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { a11y } from '../../components/ui/formA11y'
import { Modal } from '../../components/ui/Modal'
import { LoadingState } from '../../components/ui/States'
import { useApi } from '../../hooks/useApi'
import { api, ApiError } from '../../lib/api'
import { DELAY_CAUSE_LABELS, formatDateTime, formatDuration } from '../../lib/format'
import { formatClock, isValidZonedInput, minutesBetween, toZonedInput, zonedInputToIso } from '../../lib/time'
import type { DelayCause, Dispatch, Route, Schedule } from '../../lib/types'

const CAUSES = Object.entries(DELAY_CAUSE_LABELS) as [DelayCause, string][]

function errorText(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback
}

// ---------- New dispatch ----------
const dispatchSchema = z.object({
  schedule_id: z.string().min(1, 'Select a loaded truck'),
  route_id: z.string().min(1, 'Select a route'),
  dispatched_at: z.string().refine(isValidZonedInput, 'Enter the departure date and time'),
})
type DispatchValues = z.infer<typeof dispatchSchema>

interface NewDispatchProps {
  scheduleId?: number
  onClose: () => void
  onSaved: (d: Dispatch) => void
}

export function NewDispatchModal(props: NewDispatchProps) {
  const ready = useApi<Schedule[]>('/dispatches/ready')
  const routes = useApi<Route[]>('/routes')
  const error = ready.error ?? routes.error
  return (
    <Modal title="New Dispatch" description="Dispatching records the truck’s departure and closes its turnaround." onClose={props.onClose}>
      {ready.data && routes.data ? (
        // Mount once options exist so a preselected load (?schedule=) applies.
        <NewDispatchForm {...props} ready={ready.data} routes={routes.data} />
      ) : error ? (
        <FormError message={error.message} />
      ) : (
        <LoadingState />
      )}
    </Modal>
  )
}

function NewDispatchForm({ scheduleId, onClose, onSaved, ready, routes }: NewDispatchProps & { ready: Schedule[]; routes: Route[] }) {
  const [serverError, setServerError] = useState<string | null>(null)
  const [openedAt] = useState(() => toZonedInput(new Date()))
  const preselect = scheduleId && ready.some((s) => s.id === scheduleId) ? String(scheduleId) : ''
  const { register, handleSubmit, control, formState: { errors, isSubmitting } } = useForm<DispatchValues>({
    resolver: zodResolver(dispatchSchema),
    defaultValues: { schedule_id: preselect, route_id: '', dispatched_at: openedAt },
  })
  const [scheduleValue, routeValue, departure] = useWatch({ control, name: ['schedule_id', 'route_id', 'dispatched_at'] })
  const schedule = ready.find((s) => String(s.id) === scheduleValue)
  const route = routes.find((r) => String(r.id) === routeValue)
  const departureIso = isValidZonedInput(departure) ? zonedInputToIso(departure) : null

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    try {
      onSaved(await api<Dispatch>('/dispatches', {
        method: 'POST',
        body: JSON.stringify({ schedule_id: Number(v.schedule_id), route_id: Number(v.route_id), dispatched_at: zonedInputToIso(v.dispatched_at) }),
      }))
    } catch (err) {
      setServerError(errorText(err, 'Could not create the dispatch.'))
    }
  })

  const noneReady = ready.length === 0
  return (
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <Field id="dispatch-load" label="Loaded truck" error={errors.schedule_id?.message}
          hint={noneReady ? 'No loads are ready. Finish loading on the Loading Bays page first.' : undefined}>
          <select {...a11y('dispatch-load', errors.schedule_id?.message, !!noneReady)} {...register('schedule_id')} className={inputClass}>
            <option value="">Select loaded truck…</option>
            {ready.map((s) => (
              <option key={s.id} value={s.id}>
                {s.truck.label} — {s.bay.label}, loaded {formatClock(s.loading_finished_at)}
              </option>
            ))}
          </select>
        </Field>
        <Field id="dispatch-route" label="Route" error={errors.route_id?.message}
          hint={routes.length === 0 ? 'No routes yet — add one first.' : undefined}>
          <select {...a11y('dispatch-route', errors.route_id?.message)} {...register('route_id')} className={inputClass}>
            <option value="">Select route…</option>
            {routes.filter((r) => r.is_active).map((r) => (
              <option key={r.id} value={r.id}>{r.label} ({formatDuration(r.expected_duration_minutes)})</option>
            ))}
          </select>
        </Field>
        <Field id="dispatch-at" label="Departure time (EAT)" error={errors.dispatched_at?.message}>
          <input type="datetime-local" {...a11y('dispatch-at', errors.dispatched_at?.message)} {...register('dispatched_at')} className={inputClass} />
        </Field>
        {schedule && departureIso && schedule.arrival_at && (
          <dl className="grid grid-cols-2 gap-3 rounded-xl bg-surface-muted p-3 text-sm" aria-live="polite">
            <div>
              <dt className="text-ink-muted">Turnaround</dt>
              <dd className="font-semibold text-ink">{formatDuration(minutesBetween(schedule.arrival_at, departureIso))}
                <span className="font-normal text-ink-muted"> (target {formatDuration(schedule.target_minutes)})</span></dd>
            </div>
            <div>
              <dt className="text-ink-muted">Expected arrival</dt>
              <dd className="font-semibold text-ink">
                {route ? formatDateTime(new Date(new Date(departureIso).getTime() + route.expected_duration_minutes * 60_000).toISOString()) : '—'}
              </dd>
            </div>
          </dl>
        )}
        <FormActions submitLabel="Dispatch truck" submitting={isSubmitting} onCancel={onClose} />
      </form>
  )
}

// ---------- Deliver ----------
export function DeliverModal({
  dispatch,
  graceMinutes,
  onClose,
  onSaved,
}: {
  dispatch: Dispatch
  graceMinutes: number
  onClose: () => void
  onSaved: (d: Dispatch) => void
}) {
  const [value, setValue] = useState(() => toZonedInput(new Date()))
  const [cause, setCause] = useState<DelayCause | ''>(dispatch.delay_cause ?? '')
  const [notes, setNotes] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ at?: string; cause?: string }>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const arrivalIso = isValidZonedInput(value) ? zonedInputToIso(value) : null
  const late = arrivalIso ? minutesBetween(dispatch.expected_arrival_at, arrivalIso) : 0
  const isLate = late > graceMinutes
  const needsCause = isLate && !dispatch.delay_cause

  async function submit(e: FormEvent) {
    e.preventDefault()
    const errs = {
      at: arrivalIso ? undefined : 'Enter the arrival date and time',
      cause: needsCause && !cause ? 'Select why the delivery was late' : undefined,
    }
    setFieldErrors(errs)
    if (errs.at || errs.cause) return
    setBusy(true)
    setError(null)
    try {
      onSaved(await api<Dispatch>(`/dispatches/${dispatch.id}/deliver`, {
        method: 'POST',
        body: JSON.stringify({ actual_arrival_at: arrivalIso, delay_cause: isLate && cause ? cause : null, delay_notes: notes.trim() || null }),
      }))
    } catch (err) {
      setError(errorText(err, 'Could not record the delivery.'))
      setBusy(false)
    }
  }

  return (
    <Modal title="Record Delivery" description={`${dispatch.load_ref} · ${dispatch.truck.label} · ${dispatch.route.label}`} onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={error} />
        <Field id="deliver-at" label="Actual arrival time (EAT)" error={fieldErrors.at}
          hint={`Expected ${formatDateTime(dispatch.expected_arrival_at)}`}>
          <input type="datetime-local" {...a11y('deliver-at', fieldErrors.at, true)} value={value}
            onChange={(e) => setValue(e.target.value)} className={inputClass} />
        </Field>
        {arrivalIso && (
          <p aria-live="polite" className={isLate ? 'rounded-xl bg-red-50 px-3 py-2 text-sm font-semibold text-red-700' : 'rounded-xl bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-700'}>
            {isLate ? `${late} min late — this delivery will be flagged as delayed.` : late > 0 ? `${late} min after ETA (within the ${graceMinutes}-min grace).` : 'On time.'}
          </p>
        )}
        {isLate && (
          <>
            <Field id="deliver-cause" label={needsCause ? 'Delay cause' : 'Delay cause (already recorded)'} error={fieldErrors.cause}>
              <select {...a11y('deliver-cause', fieldErrors.cause)} value={cause} onChange={(e) => setCause(e.target.value as DelayCause)} className={inputClass}>
                <option value="">Select cause…</option>
                {CAUSES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
            </Field>
            <Field id="deliver-notes" label="Notes (optional)">
              <textarea id="deliver-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} maxLength={500}
                className={`${inputClass} h-auto py-2`} />
            </Field>
          </>
        )}
        <FormActions submitLabel="Confirm delivery" submitting={busy} onCancel={onClose} />
      </form>
    </Modal>
  )
}

// ---------- Flag delay ----------
const flagSchema = z.object({
  cause: z.string().min(1, 'Select a cause'),
  minutes: z.string().refine((v) => Number.isInteger(Number(v)) && Number(v) > 0 && Number(v) <= 2880, 'Whole minutes between 1 and 2880'),
  description: z.string().max(500),
})
type FlagValues = z.infer<typeof flagSchema>

export function FlagDelayModal({ dispatch, onClose, onSaved }: { dispatch: Dispatch; onClose: () => void; onSaved: (d: Dispatch) => void }) {
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FlagValues>({
    resolver: zodResolver(flagSchema), defaultValues: { cause: '', minutes: '', description: '' },
  })
  const submit = handleSubmit(async (v) => {
    setServerError(null)
    try {
      onSaved(await api<Dispatch>(`/dispatches/${dispatch.id}/flag-delay`, {
        method: 'POST',
        body: JSON.stringify({ cause: v.cause, estimated_delay_minutes: Number(v.minutes), description: v.description.trim() || null }),
      }))
    } catch (err) {
      setServerError(errorText(err, 'Could not flag the delay.'))
    }
  })
  return (
    <Modal title="Flag Delay" description={`${dispatch.load_ref} · ${dispatch.truck.label} · ${dispatch.route.label}`} onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="flag-cause" label="Cause" error={errors.cause?.message}>
            <select {...a11y('flag-cause', errors.cause?.message)} {...register('cause')} className={inputClass}>
              <option value="">Select cause…</option>
              {CAUSES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </Field>
          <Field id="flag-minutes" label="Estimated delay (min)" error={errors.minutes?.message}>
            <input type="number" min="1" {...a11y('flag-minutes', errors.minutes?.message)} {...register('minutes')} className={inputClass} />
          </Field>
        </div>
        <Field id="flag-description" label="Details (optional)" error={errors.description?.message}>
          <textarea {...a11y('flag-description', errors.description?.message)} {...register('description')} rows={2} className={`${inputClass} h-auto py-2`} />
        </Field>
        <FormActions submitLabel="Flag delay" submitting={isSubmitting} onCancel={onClose} />
      </form>
    </Modal>
  )
}

// ---------- Route ----------
const routeSchema = z.object({
  origin: z.string().trim().min(2, 'Enter the origin').max(80),
  destination: z.string().trim().min(2, 'Enter the destination').max(80),
  distance: z.string().refine((v) => Number(v) > 0 && Number(v) <= 5000, 'Distance between 0 and 5000 km'),
  hours: z.string().refine((v) => Number(v) > 0 && Number(v) <= 72, 'Duration between 0 and 72 hours'),
}).refine((v) => v.origin.toLowerCase() !== v.destination.toLowerCase(), {
  message: 'Destination must differ from origin', path: ['destination'],
})
type RouteValues = z.infer<typeof routeSchema>

export function RouteModal({ onClose, onSaved }: { onClose: () => void; onSaved: (r: Route) => void }) {
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<RouteValues>({
    resolver: zodResolver(routeSchema), defaultValues: { origin: 'Nairobi', destination: '', distance: '', hours: '' },
  })
  const submit = handleSubmit(async (v) => {
    setServerError(null)
    try {
      onSaved(await api<Route>('/routes', {
        method: 'POST',
        body: JSON.stringify({ origin: v.origin, destination: v.destination, distance_km: Number(v.distance),
          expected_duration_minutes: Math.round(Number(v.hours) * 60) }),
      }))
    } catch (err) {
      setServerError(errorText(err, 'Could not save the route.'))
    }
  })
  return (
    <Modal title="Add Route" description="Expected duration is used to calculate each dispatch’s ETA." onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="route-origin" label="Origin" error={errors.origin?.message}>
            <input {...a11y('route-origin', errors.origin?.message)} {...register('origin')} className={inputClass} />
          </Field>
          <Field id="route-destination" label="Destination" error={errors.destination?.message}>
            <input {...a11y('route-destination', errors.destination?.message)} {...register('destination')} className={inputClass} />
          </Field>
          <Field id="route-distance" label="Distance (km)" error={errors.distance?.message}>
            <input type="number" min="1" step="0.1" {...a11y('route-distance', errors.distance?.message)} {...register('distance')} className={inputClass} />
          </Field>
          <Field id="route-hours" label="Expected duration (hours)" error={errors.hours?.message}>
            <input type="number" min="0.25" step="0.25" {...a11y('route-hours', errors.hours?.message)} {...register('hours')} className={inputClass} />
          </Field>
        </div>
        <FormActions submitLabel="Add route" submitting={isSubmitting} onCancel={onClose} />
      </form>
    </Modal>
  )
}
