import { useState, type FormEvent, type ReactNode } from 'react'
import { inputClass } from '../../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../../components/ui/Form'
import { Modal } from '../../../components/ui/Modal'
import { useApi } from '../../../hooks/useApi'
import { api, ApiError } from '../../../lib/api'
import { formatDate, MAINTENANCE_ROLE_LABELS } from '../../../lib/format'
import type { Equipment, EquipmentOptions, IntervalUnit, MaintenancePlan, MaintenanceTask, ScheduleBasis } from '../../../lib/maintenance'
import type { Page } from '../../../lib/types'
import { todayIso } from '../../../lib/time'

/** Small form-in-a-modal: runs `action`, shows the server's message on failure. */
function ActionModal<T>({
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

const post = <T,>(path: string, body: unknown, method = 'POST') =>
  api<T>(path, { method, body: JSON.stringify(body) })

function useTechnicians() {
  return useApi<EquipmentOptions>('/maintenance/equipment/options').data?.technicians ?? []
}

function TechnicianSelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const technicians = useTechnicians()
  return (
    <Field id={id} label="Assigned technician">
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
        <option value="">Unassigned</option>
        {technicians.map((t) => (
          <option key={t.id} value={t.id}>{t.full_name} · {MAINTENANCE_ROLE_LABELS[t.maintenance_role]}</option>
        ))}
      </select>
    </Field>
  )
}

function EquipmentSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { data } = useApi<Page<Equipment>>('/maintenance/equipment?limit=100')
  return (
    <Field id="pm-equipment" label="Equipment"
      hint={data && data.total > data.items.length ? `Showing the first ${data.items.length} of ${data.total}.` : undefined}>
      <select id="pm-equipment" value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
        <option value="">Choose equipment…</option>
        {data?.items.map((e) => <option key={e.id} value={e.id}>{e.code} · {e.name}</option>)}
      </select>
    </Field>
  )
}

const techId = (v: string) => (v ? Number(v) : null)

// ---------- tasks ----------
export function CompleteTaskModal({ task, onClose, onDone }: {
  task: MaintenanceTask; onClose: () => void; onDone: (t: MaintenanceTask) => void
}) {
  const [completedOn, setCompletedOn] = useState(todayIso())
  const [notes, setNotes] = useState('')
  return (
    <ActionModal title="Complete maintenance" description={`${task.equipment.code} · ${task.title}`}
      submitLabel="Mark as completed" onClose={onClose} onDone={onDone}
      validate={() => (!completedOn ? 'Enter the completion date.'
        : completedOn > todayIso() ? 'The completion date cannot be in the future.'
          : notes.trim().length < 3 ? 'Describe the work performed.' : null)}
      action={() => post<MaintenanceTask>(`/maintenance/tasks/${task.id}/complete`, { completed_on: completedOn, work_notes: notes.trim() })}>
      {task.instructions && (
        <div className="rounded-xl bg-surface-muted px-3 py-2.5 text-sm">
          <p className="font-semibold text-ink">Instructions</p>
          <p className="mt-0.5 whitespace-pre-line text-ink">{task.instructions}</p>
        </div>
      )}
      <p className="text-sm text-ink-muted">Due {formatDate(task.due_on)}. The next task in this plan is scheduled automatically.</p>
      <Field id="pm-completed-on" label="Completed on">
        <input id="pm-completed-on" type="date" max={todayIso()} value={completedOn}
          onChange={(e) => setCompletedOn(e.target.value)} className={inputClass} />
      </Field>
      <Field id="pm-notes" label="Work performed" hint="Required. What was checked, replaced or adjusted.">
        <textarea id="pm-notes" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)}
          className={`${inputClass} h-auto py-2.5`} />
      </Field>
    </ActionModal>
  )
}

export function CancelTaskModal({ task, onClose, onDone }: {
  task: MaintenanceTask; onClose: () => void; onDone: (t: MaintenanceTask) => void
}) {
  const [reason, setReason] = useState('')
  return (
    <ActionModal title="Cancel this service" description={`${task.equipment.code} · ${task.title} · due ${formatDate(task.due_on)}`}
      submitLabel="Cancel service" onClose={onClose} onDone={onDone}
      validate={() => (reason.trim().length < 3 ? 'Give the reason for cancelling.' : null)}
      action={() => post<MaintenanceTask>(`/maintenance/tasks/${task.id}/cancel`, { reason: reason.trim() })}>
      <p className="text-sm text-ink-muted">
        Cancelled work is not counted as completed.{task.plan_id ? ' The plan schedules its next cycle.' : ''}
      </p>
      <Field id="pm-cancel-reason" label="Reason">
        <input id="pm-cancel-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255}
          placeholder="e.g. Plant shutdown, asset replaced" className={inputClass} />
      </Field>
    </ActionModal>
  )
}

export function RescheduleTaskModal({ task, onClose, onDone }: {
  task: MaintenanceTask; onClose: () => void; onDone: (t: MaintenanceTask) => void
}) {
  const [dueOn, setDueOn] = useState(task.due_on < todayIso() ? todayIso() : task.due_on)
  const [tech, setTech] = useState(task.assigned_technician ? String(task.assigned_technician.id) : '')
  return (
    <ActionModal title="Reschedule or reassign" description={`${task.equipment.code} · ${task.title}`}
      submitLabel="Save" onClose={onClose} onDone={onDone}
      validate={() => (!dueOn || dueOn < todayIso() ? 'Choose today or a later date.' : null)}
      action={() => post<MaintenanceTask>(`/maintenance/tasks/${task.id}`, { due_on: dueOn, assigned_technician_id: techId(tech) }, 'PATCH')}>
      <Field id="pm-due" label="Due date">
        <input id="pm-due" type="date" min={todayIso()} value={dueOn} onChange={(e) => setDueOn(e.target.value)} className={inputClass} />
      </Field>
      <TechnicianSelect id="pm-task-tech" value={tech} onChange={setTech} />
    </ActionModal>
  )
}

export function ScheduleServiceModal({ onClose, onDone }: { onClose: () => void; onDone: (t: MaintenanceTask) => void }) {
  const [equipment, setEquipment] = useState('')
  const [title, setTitle] = useState('')
  const [dueOn, setDueOn] = useState(todayIso())
  const [tech, setTech] = useState('')
  return (
    <ActionModal title="Schedule a service" description="A once-off service. Use a plan for recurring work."
      submitLabel="Schedule service" onClose={onClose} onDone={onDone}
      validate={() => (!equipment ? 'Choose the equipment.' : title.trim().length < 3 ? 'Describe the service.'
        : !dueOn || dueOn < todayIso() ? 'Choose today or a later date.' : null)}
      action={() => post<MaintenanceTask>('/maintenance/tasks', {
        equipment_id: Number(equipment), title: title.trim(), due_on: dueOn, assigned_technician_id: techId(tech),
      })}>
      <EquipmentSelect value={equipment} onChange={setEquipment} />
      <Field id="pm-service-title" label="Service">
        <input id="pm-service-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120}
          placeholder="e.g. Safety valve test" className={inputClass} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="pm-service-due" label="Due date">
          <input id="pm-service-due" type="date" min={todayIso()} value={dueOn} onChange={(e) => setDueOn(e.target.value)} className={inputClass} />
        </Field>
        <TechnicianSelect id="pm-service-tech" value={tech} onChange={setTech} />
      </div>
    </ActionModal>
  )
}

// ---------- plans ----------
export function PlanFormModal({ plan, onClose, onDone }: {
  plan?: MaintenancePlan; onClose: () => void; onDone: (p: MaintenancePlan) => void
}) {
  const editing = !!plan
  const [equipment, setEquipment] = useState(plan ? String(plan.equipment.id) : '')
  const [title, setTitle] = useState(plan?.title ?? '')
  const [instructions, setInstructions] = useState(plan?.instructions ?? '')
  const [value, setValue] = useState(String(plan?.interval_value ?? 1))
  const [unit, setUnit] = useState<IntervalUnit>(plan?.interval_unit ?? 'months')
  const [basis, setBasis] = useState<ScheduleBasis>(plan?.schedule_basis ?? 'due_date')
  const [startOn, setStartOn] = useState(todayIso())
  const [tech, setTech] = useState(plan?.assigned_technician ? String(plan.assigned_technician.id) : '')
  const n = Number(value)
  const common = {
    title: title.trim(), instructions: instructions.trim() || null, interval_value: n, interval_unit: unit,
    schedule_basis: basis, assigned_technician_id: techId(tech),
  }
  return (
    <ActionModal wide title={editing ? 'Edit preventive plan' : 'New preventive plan'}
      description={editing ? `${plan.equipment.code} · changes apply to tasks generated from now on.` : 'Recurring, date-based servicing for one asset.'}
      submitLabel={editing ? 'Save plan' : 'Create plan'} onClose={onClose} onDone={onDone}
      validate={() => (!editing && !equipment ? 'Choose the equipment.'
        : title.trim().length < 3 ? 'Give the plan a title.'
          : !Number.isInteger(n) || n < 1 || n > 3650 ? 'The interval must be a whole number from 1 to 3650.'
            : !editing && !startOn ? 'Choose the first due date.' : null)}
      action={() => editing
        ? post<MaintenancePlan>(`/maintenance/plans/${plan.id}`, common, 'PATCH')
        : post<MaintenancePlan>('/maintenance/plans', { ...common, equipment_id: Number(equipment), start_on: startOn })}>
      {!editing && <EquipmentSelect value={equipment} onChange={setEquipment} />}
      <Field id="plan-title" label="Plan title">
        <input id="plan-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120}
          placeholder="e.g. Monthly compressor service" className={inputClass} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="plan-interval" label="Repeat every">
          <input id="plan-interval" type="number" min={1} max={3650} inputMode="numeric" value={value}
            onChange={(e) => setValue(e.target.value)} className={inputClass} />
        </Field>
        <Field id="plan-unit" label="Unit">
          <select id="plan-unit" value={unit} onChange={(e) => setUnit(e.target.value as IntervalUnit)} className={inputClass}>
            <option value="days">Days</option>
            <option value="weeks">Weeks</option>
            <option value="months">Months</option>
          </select>
        </Field>
        {!editing && (
          <Field id="plan-start" label="First due date">
            <input id="plan-start" type="date" value={startOn} onChange={(e) => setStartOn(e.target.value)} className={inputClass} />
          </Field>
        )}
      </div>
      <fieldset>
        <legend className="mb-1.5 text-sm font-semibold text-ink">Next due date is counted from</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {([
            ['due_date', 'The due date', 'Fixed calendar: late work does not shift the schedule.'],
            ['completion_date', 'The completion date', 'Floating: the next service follows the last one done.'],
          ] as const).map(([v, label, help]) => (
            <label key={v} className="flex cursor-pointer gap-2.5 rounded-xl border border-line p-3 has-checked:border-accent has-checked:bg-sky-50">
              <input type="radio" name="plan-basis" value={v} checked={basis === v} onChange={() => setBasis(v)} className="mt-1" />
              <span className="text-sm"><span className="font-semibold text-ink">{label}</span><br /><span className="text-ink-muted">{help}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      <TechnicianSelect id="plan-tech" value={tech} onChange={setTech} />
      <Field id="plan-instructions" label="Instructions (optional)" hint="Shown to the technician when completing the task.">
        <textarea id="plan-instructions" rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)}
          maxLength={4000} className={`${inputClass} h-auto py-2.5`} />
      </Field>
    </ActionModal>
  )
}

export function StopPlanModal({ plan, onClose, onDone }: {
  plan: MaintenancePlan; onClose: () => void; onDone: (p: MaintenancePlan) => void
}) {
  const [reason, setReason] = useState('')
  return (
    <ActionModal title="Stop this plan" description={`${plan.equipment.code} · ${plan.title}`}
      submitLabel="Stop plan" onClose={onClose} onDone={onDone}
      validate={() => (reason.trim().length < 3 ? 'Give the reason for stopping the plan.' : null)}
      action={() => post<MaintenancePlan>(`/maintenance/plans/${plan.id}/deactivate`, { reason: reason.trim() })}>
      <p className="text-sm text-ink-muted">Its open task is cancelled with this reason. History is kept and the plan can be resumed.</p>
      <Field id="plan-stop-reason" label="Reason">
        <input id="plan-stop-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} className={inputClass} />
      </Field>
    </ActionModal>
  )
}

export function ResumePlanModal({ plan, onClose, onDone }: {
  plan: MaintenancePlan; onClose: () => void; onDone: (p: MaintenancePlan) => void
}) {
  const [dueOn, setDueOn] = useState(todayIso())
  return (
    <ActionModal title="Resume this plan" description={`${plan.equipment.code} · ${plan.title}`}
      submitLabel="Resume plan" onClose={onClose} onDone={onDone}
      validate={() => (!dueOn || dueOn < todayIso() ? 'Choose today or a later date.' : null)}
      action={() => post<MaintenancePlan>(`/maintenance/plans/${plan.id}/activate`, { next_due_on: dueOn })}>
      <Field id="plan-resume-due" label="Next due date">
        <input id="plan-resume-due" type="date" min={todayIso()} value={dueOn} onChange={(e) => setDueOn(e.target.value)} className={inputClass} />
      </Field>
    </ActionModal>
  )
}
