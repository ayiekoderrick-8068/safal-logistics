import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
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
import { formatClock, isValidZonedInput, toZonedInput, zonedInputToIso } from '../../lib/time'
import type { AssignableUser, Dispatch, Incident, Page, Schedule } from '../../lib/types'
import { todayIn } from '../overview/period'

const CAUSES = Object.entries(DELAY_CAUSE_LABELS)
const STATUSES = [
  { value: 'open', label: 'Open' },
  { value: 'investigating', label: 'Investigating' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'resolved', label: 'Resolved' },
]
const minutes = z.string().refine((v) => /^\d+$/.test(v) && Number(v) <= 2880, 'Whole minutes between 0 and 2880')

// ---------- Report ----------
const reportSchema = z.object({
  source: z.enum(['loading', 'dispatch']),
  operation_id: z.string().min(1, 'Select the affected operation'),
  cause: z.string().min(1, 'Select a delay category'),
  started_at: z.string().refine(isValidZonedInput, 'Enter when the delay started'),
  impact: minutes,
  description: z.string().trim().min(3, 'Describe the delay').max(1000),
  assigned_to: z.string(),
})
type ReportValues = z.infer<typeof reportSchema>
export type ReportPreset = { source: 'loading' | 'dispatch'; id: number }

export function ReportDelayModal({ preset, onClose, onSaved }: {
  preset?: ReportPreset
  onClose: () => void
  onSaved: (i: Incident) => void
}) {
  const schedules = useApi<Page<Schedule>>(`/schedules?date=${todayIn()}&limit=100`)
  const dispatches = useApi<Page<Dispatch>>('/dispatches?limit=50')
  const users = useApi<AssignableUser[]>('/users/assignable')
  const error = schedules.error ?? dispatches.error ?? users.error
  return (
    <Modal title="Report Delay" description="Record a loading or dispatch delay. Times are in Nairobi time (EAT)." onClose={onClose} wide>
      {schedules.data && dispatches.data && users.data ? (
        <ReportForm preset={preset} schedules={schedules.data.items.filter((s) => s.status !== 'cancelled')}
          dispatches={dispatches.data.items} users={users.data} onClose={onClose} onSaved={onSaved} />
      ) : error ? <FormError message={error.message} /> : <LoadingState />}
    </Modal>
  )
}

function ReportForm({ preset, schedules, dispatches, users, onClose, onSaved }: {
  preset?: ReportPreset
  schedules: Schedule[]
  dispatches: Dispatch[]
  users: AssignableUser[]
  onClose: () => void
  onSaved: (i: Incident) => void
}) {
  const [serverError, setServerError] = useState<string | null>(null)
  const [openedAt] = useState(() => toZonedInput(new Date()))
  const { register, handleSubmit, control, setValue, formState: { errors, isSubmitting } } = useForm<ReportValues>({
    resolver: zodResolver(reportSchema),
    defaultValues: {
      source: preset?.source ?? 'loading', operation_id: preset ? String(preset.id) : '', cause: '',
      started_at: openedAt, impact: '0', description: '', assigned_to: '',
    },
  })
  const source = useWatch({ control, name: 'source' })
  // A preset operation may be outside the default lists (e.g. an older dispatch); keep it selectable.
  const presetMissing = preset && (preset.source === 'loading'
    ? !schedules.some((s) => s.id === preset.id) : !dispatches.some((d) => d.id === preset.id))

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    try {
      onSaved(await api<Incident>('/incidents', {
        method: 'POST',
        body: JSON.stringify({
          [v.source === 'loading' ? 'schedule_id' : 'dispatch_id']: Number(v.operation_id),
          cause: v.cause, started_at: zonedInputToIso(v.started_at), impact_minutes: Number(v.impact),
          description: v.description, assigned_to_id: v.assigned_to ? Number(v.assigned_to) : null,
        }),
      }))
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not report the delay.')
    }
  })

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={serverError} />
      <fieldset>
        <legend className="mb-1.5 text-sm font-semibold text-ink">Delay affects</legend>
        <div className="flex gap-4">
          {(['loading', 'dispatch'] as const).map((s) => (
            <label key={s} className="flex items-center gap-2 text-sm text-ink">
              <input type="radio" value={s} {...register('source', { onChange: () => setValue('operation_id', '') })}
                className="size-4 accent-[#0e6481]" />
              {s === 'loading' ? 'Loading operation (today)' : 'Dispatch / delivery'}
            </label>
          ))}
        </div>
      </fieldset>
      <Field id="inc-op" label={source === 'loading' ? 'Loading schedule' : 'Dispatch'} error={errors.operation_id?.message}>
        <select {...a11y('inc-op', errors.operation_id?.message)} {...register('operation_id')} className={inputClass}>
          <option value="">Select…</option>
          {presetMissing && preset.source === source && <option value={preset.id}>Selected {source} #{preset.id}</option>}
          {source === 'loading'
            ? schedules.map((s) => (
                <option key={s.id} value={s.id}>{s.truck.label} — {s.bay.label}, {formatClock(s.scheduled_start)} ({s.status})</option>
              ))
            : dispatches.map((d) => (
                <option key={d.id} value={d.id}>{d.load_ref} — {d.truck.label}, {d.route.label} ({d.status.replace('_', ' ')})</option>
              ))}
        </select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="inc-cause" label="Delay category" error={errors.cause?.message}>
          <select {...a11y('inc-cause', errors.cause?.message)} {...register('cause')} className={inputClass}>
            <option value="">Select category…</option>
            {CAUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field id="inc-start" label="Delay started (EAT)" error={errors.started_at?.message}>
          <input type="datetime-local" {...a11y('inc-start', errors.started_at?.message)} {...register('started_at')} className={inputClass} />
        </Field>
        <Field id="inc-impact" label="Estimated impact (minutes)" error={errors.impact?.message}>
          <input type="number" min="0" {...a11y('inc-impact', errors.impact?.message)} {...register('impact')} className={inputClass} />
        </Field>
        <Field id="inc-assignee" label="Responsible staff member (optional)">
          <select id="inc-assignee" {...register('assigned_to')} className={inputClass}>
            <option value="">Unassigned</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
          </select>
        </Field>
      </div>
      <Field id="inc-desc" label="Description" error={errors.description?.message}>
        <textarea {...a11y('inc-desc', errors.description?.message)} {...register('description')} rows={3}
          className={`${inputClass} h-auto py-2`} placeholder="What happened and what is being done?" />
      </Field>
      <FormActions submitLabel="Report delay" submitting={isSubmitting} onCancel={onClose} />
    </form>
  )
}

// ---------- Update ----------
const updateSchema = z.object({
  status: z.enum(['open', 'investigating', 'in_progress', 'resolved']),
  cause: z.string().min(1),
  assigned_to: z.string(),
  impact: minutes,
  resolution_notes: z.string().max(1000),
  resolved_at: z.string(),
}).superRefine((v, ctx) => {
  if (v.status !== 'resolved') return
  if (v.resolution_notes.trim().length < 3) {
    ctx.addIssue({ code: 'custom', path: ['resolution_notes'], message: 'Describe how the delay was resolved' })
  }
  if (!isValidZonedInput(v.resolved_at)) {
    ctx.addIssue({ code: 'custom', path: ['resolved_at'], message: 'Enter when it was resolved' })
  }
})
type UpdateValues = z.infer<typeof updateSchema>

export function UpdateIncidentModal({ incident, onClose, onSaved }: {
  incident: Incident
  onClose: () => void
  onSaved: (i: Incident) => void
}) {
  const users = useApi<AssignableUser[]>('/users/assignable')
  return (
    <Modal title={`Delay #${incident.id}`} wide onClose={onClose}
      description={`${incident.truck?.label ?? ''} · ${incident.operation} · started ${formatDateTime(incident.started_at)}`}>
      {users.data ? <UpdateForm incident={incident} users={users.data} onClose={onClose} onSaved={onSaved} />
        : users.error ? <FormError message={users.error.message} /> : <LoadingState />}
    </Modal>
  )
}

function UpdateForm({ incident, users, onClose, onSaved }: {
  incident: Incident
  users: AssignableUser[]
  onClose: () => void
  onSaved: (i: Incident) => void
}) {
  const [serverError, setServerError] = useState<string | null>(null)
  const [openedAt] = useState(() => toZonedInput(incident.resolved_at ? new Date(incident.resolved_at) : new Date()))
  const { register, handleSubmit, control, formState: { errors, isSubmitting } } = useForm<UpdateValues>({
    resolver: zodResolver(updateSchema),
    defaultValues: {
      status: incident.status, cause: incident.cause, assigned_to: incident.assigned_to ? String(incident.assigned_to.id) : '',
      impact: String(incident.impact_minutes), resolution_notes: incident.resolution_notes ?? '', resolved_at: openedAt,
    },
  })
  const status = useWatch({ control, name: 'status' })

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    try {
      onSaved(await api<Incident>(`/incidents/${incident.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          status: v.status, cause: v.cause, impact_minutes: Number(v.impact),
          assigned_to_id: v.assigned_to ? Number(v.assigned_to) : null,
          resolution_notes: v.resolution_notes,
          ...(v.status === 'resolved' ? { resolved_at: zonedInputToIso(v.resolved_at) } : {}),
        }),
      }))
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not update the incident.')
    }
  })

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={serverError} />
      {incident.description && (
        <p className="rounded-xl bg-surface-muted px-4 py-3 text-sm text-ink">
          <span className="font-semibold">Reported{incident.reported_by ? ` by ${incident.reported_by}` : ''}:</span> {incident.description}
        </p>
      )}
      <p className="text-sm text-ink-muted">
        Duration so far: <strong className="text-ink">{formatDuration(incident.duration_minutes)}</strong>
        {incident.is_ongoing ? ' (ongoing)' : ''}
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="upd-status" label="Status">
          <select id="upd-status" {...register('status')} className={inputClass}>
            {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </Field>
        <Field id="upd-assignee" label="Responsible staff member">
          <select id="upd-assignee" {...register('assigned_to')} className={inputClass}>
            <option value="">Unassigned</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
          </select>
        </Field>
        <Field id="upd-cause" label="Delay category">
          <select id="upd-cause" {...register('cause')} className={inputClass}>
            {CAUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field id="upd-impact" label="Impact (minutes)" error={errors.impact?.message}>
          <input type="number" min="0" {...a11y('upd-impact', errors.impact?.message)} {...register('impact')} className={inputClass} />
        </Field>
        {status === 'resolved' && (
          <Field id="upd-resolved" label="Resolved at (EAT)" error={errors.resolved_at?.message}>
            <input type="datetime-local" {...a11y('upd-resolved', errors.resolved_at?.message)} {...register('resolved_at')} className={inputClass} />
          </Field>
        )}
      </div>
      <Field id="upd-notes" label={status === 'resolved' ? 'Resolution notes' : 'Resolution notes (optional)'} error={errors.resolution_notes?.message}>
        <textarea {...a11y('upd-notes', errors.resolution_notes?.message)} {...register('resolution_notes')} rows={3}
          className={`${inputClass} h-auto py-2`} />
      </Field>
      <FormActions submitLabel="Save changes" submitting={isSubmitting} onCancel={onClose} />
    </form>
  )
}
