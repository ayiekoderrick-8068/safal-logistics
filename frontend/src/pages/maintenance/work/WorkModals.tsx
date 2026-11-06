import { useState } from 'react'
import { inputClass } from '../../../components/ui/buttons'
import { Field } from '../../../components/ui/Form'
import {
  FAULT_LABELS,
  PRIORITY_LABELS,
  send,
  SEVERITY_LABELS,
  techId,
  WO_TYPE_LABELS,
  type Breakdown,
  type FaultCategory,
  type Priority,
  type Severity,
  type WorkOrder,
  type WorkOrderType,
} from '../../../lib/maintenance'
import { isValidZonedInput, todayIso, toZonedInput, zonedInputToIso } from '../../../lib/time'
import { ActionModal, EquipmentSelect, TechnicianSelect } from '../forms'

const nowInput = () => toZonedInput(new Date())
const area = `${inputClass} h-auto py-2.5`
/** datetime-local has minute precision: compare against the start rounded down to the minute. */
const minuteFloor = (iso: string) => Math.floor(new Date(iso).getTime() / 60_000) * 60_000

/**
 * A "now" field that the user may change. Left untouched, the exact current time is sent at
 * submit (the input itself drops the seconds, which could otherwise land before a start time
 * recorded earlier in the same minute).
 */
function useWhen() {
  const [value, setValue] = useState(nowInput())
  const [edited, setEdited] = useState(false)
  return {
    value,
    edited,
    onChange: (v: string) => { setValue(v); setEdited(true) },
    iso: () => (edited ? zonedInputToIso(value) : new Date().toISOString()),
  }
}

function Select<T extends string>({ id, label, value, onChange, options }: {
  id: string; label: string; value: T; onChange: (v: T) => void; options: Record<T, string>
}) {
  return (
    <Field id={id} label={label}>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value as T)} className={inputClass}>
        {(Object.entries(options) as [T, string][]).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </Field>
  )
}

function whenProblem(value: string, label: string, notBefore?: string, startLabel = 'the failure started'): string | null {
  if (!isValidZonedInput(value)) return `Enter the ${label}.`
  const at = new Date(zonedInputToIso(value)).getTime()
  if (at > Date.now() + 5 * 60_000) return `The ${label} cannot be in the future.`
  if (notBefore && at < minuteFloor(notBefore)) return `The ${label} cannot be before ${startLabel}.`
  return null
}

// ---------- work orders ----------
export function NewWorkOrderModal({ canAssign, selfId, onClose, onDone }: {
  canAssign: boolean; selfId: number; onClose: () => void; onDone: (w: WorkOrder) => void
}) {
  const [equipment, setEquipment] = useState('')
  const [kind, setKind] = useState<WorkOrderType>('corrective')
  const [priority, setPriority] = useState<Priority>('medium')
  const [description, setDescription] = useState('')
  const [scheduled, setScheduled] = useState('')
  const [tech, setTech] = useState('')
  const [mine, setMine] = useState(!canAssign)
  return (
    <ActionModal wide title="New work order" description="Raise maintenance work for one asset."
      submitLabel="Raise work order" onClose={onClose} onDone={onDone}
      validate={() => (!equipment ? 'Choose the equipment.'
        : description.trim().length < 5 ? 'Describe the fault or the work needed.'
          : scheduled && scheduled < todayIso() ? 'The scheduled date cannot be in the past.' : null)}
      action={() => send<WorkOrder>('/maintenance/work-orders', {
        equipment_id: Number(equipment), maintenance_type: kind, priority, fault_description: description.trim(),
        scheduled_on: scheduled || null,
        assigned_technician_id: canAssign ? techId(tech) : mine ? selfId : null,
      })}>
      <EquipmentSelect id="wo-equipment" value={equipment} onChange={setEquipment} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Select id="wo-type" label="Maintenance type" value={kind} onChange={setKind} options={WO_TYPE_LABELS} />
        <Select id="wo-priority" label="Priority" value={priority} onChange={setPriority} options={PRIORITY_LABELS} />
      </div>
      <Field id="wo-description" label="Fault description / work required">
        <textarea id="wo-description" rows={3} value={description} onChange={(e) => setDescription(e.target.value)}
          maxLength={4000} className={area} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="wo-scheduled" label="Scheduled date (optional)">
          <input id="wo-scheduled" type="date" min={todayIso()} value={scheduled}
            onChange={(e) => setScheduled(e.target.value)} className={inputClass} />
        </Field>
        {canAssign ? (
          <TechnicianSelect id="wo-tech" value={tech} onChange={setTech} />
        ) : (
          <label className="flex items-center gap-2 self-end pb-3 text-sm text-ink">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} className="size-4" />
            Assign to me
          </label>
        )}
      </div>
    </ActionModal>
  )
}

export function EditWorkOrderModal({ wo, onClose, onDone }: { wo: WorkOrder; onClose: () => void; onDone: (w: WorkOrder) => void }) {
  const [priority, setPriority] = useState<Priority>(wo.priority)
  const [description, setDescription] = useState(wo.fault_description)
  const [scheduled, setScheduled] = useState(wo.scheduled_on ?? '')
  const [tech, setTech] = useState(wo.assigned_technician ? String(wo.assigned_technician.id) : '')
  const started = wo.status === 'in_progress' || wo.status === 'awaiting_parts'
  return (
    <ActionModal title={`Edit ${wo.number}`} description={`${wo.equipment.code} · ${wo.equipment.name}`}
      submitLabel="Save" onClose={onClose} onDone={onDone}
      validate={() => (description.trim().length < 5 ? 'Describe the fault or the work needed.'
        : scheduled && scheduled !== wo.scheduled_on && scheduled < todayIso() ? 'The scheduled date cannot be in the past.'
          : started && !tech ? 'Work in progress cannot be unassigned. Choose a technician.' : null)}
      action={() => send<WorkOrder>(`/maintenance/work-orders/${wo.id}`, {
        priority, fault_description: description.trim(), scheduled_on: scheduled || null, assigned_technician_id: techId(tech),
      }, 'PATCH')}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Select id="wo-edit-priority" label="Priority" value={priority} onChange={setPriority} options={PRIORITY_LABELS} />
        <Field id="wo-edit-scheduled" label="Scheduled date">
          <input id="wo-edit-scheduled" type="date" value={scheduled} onChange={(e) => setScheduled(e.target.value)} className={inputClass} />
        </Field>
      </div>
      <TechnicianSelect id="wo-edit-tech" value={tech} onChange={setTech} />
      <Field id="wo-edit-description" label="Fault description / work required">
        <textarea id="wo-edit-description" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} className={area} />
      </Field>
    </ActionModal>
  )
}

export function CompleteWorkOrderModal({ wo, onClose, onDone }: { wo: WorkOrder; onClose: () => void; onDone: (w: WorkOrder) => void }) {
  const [performed, setPerformed] = useState('')
  const [notes, setNotes] = useState('')
  const when = useWhen()
  const openBreakdown = wo.breakdown?.is_open ? wo.breakdown : null
  const [restore, setRestore] = useState(!!openBreakdown)
  return (
    <ActionModal wide title={`Complete ${wo.number}`} description={`${wo.equipment.code} · ${wo.fault_description}`}
      submitLabel="Complete work order" onClose={onClose} onDone={onDone}
      validate={() => (performed.trim().length < 10 ? 'Describe the work performed (at least 10 characters).'
        : when.edited ? whenProblem(when.value, 'completion time', wo.started_at ?? undefined, 'the work started') : null)}
      action={() => send<WorkOrder>(`/maintenance/work-orders/${wo.id}/complete`, {
        work_performed: performed.trim(), completion_notes: notes.trim() || null,
        // Untouched: let the server stamp the exact time.
        completed_at: when.edited ? when.iso() : null, restore_breakdown: restore,
      })}>
      <Field id="wo-performed" label="Work performed" hint="Required. What was found, repaired or replaced.">
        <textarea id="wo-performed" rows={4} value={performed} onChange={(e) => setPerformed(e.target.value)} className={area} />
      </Field>
      <Field id="wo-notes" label="Completion notes (optional)" hint="Follow-ups, observations, recommendations.">
        <textarea id="wo-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} className={area} />
      </Field>
      <Field id="wo-completed-at" label="Completed at">
        <input id="wo-completed-at" type="datetime-local" max={nowInput()} value={when.value}
          onChange={(e) => when.onChange(e.target.value)} className={inputClass} />
      </Field>
      {openBreakdown && (
        <label className="flex items-start gap-2.5 rounded-xl border border-line p-3 text-sm has-checked:border-accent has-checked:bg-sky-50">
          <input type="checkbox" checked={restore} onChange={(e) => setRestore(e.target.checked)} className="mt-0.5 size-4" />
          <span>
            <span className="font-semibold text-ink">Equipment is back in service</span><br />
            <span className="text-ink-muted">Records breakdown {openBreakdown.number} as restored at the completion time.</span>
          </span>
        </label>
      )}
    </ActionModal>
  )
}

export function CancelWorkOrderModal({ wo, onClose, onDone }: { wo: WorkOrder; onClose: () => void; onDone: (w: WorkOrder) => void }) {
  const [reason, setReason] = useState('')
  return (
    <ActionModal title={`Cancel ${wo.number}`} description={`${wo.equipment.code} · ${wo.fault_description}`}
      submitLabel="Cancel work order" onClose={onClose} onDone={onDone}
      validate={() => (reason.trim().length < 3 ? 'Give the reason for cancelling.' : null)}
      action={() => send<WorkOrder>(`/maintenance/work-orders/${wo.id}/transition`, { to: 'cancelled', note: reason.trim() })}>
      <p className="text-sm text-ink-muted">Cancelled work orders stay in the history and are not counted as completed.</p>
      <Field id="wo-cancel-reason" label="Reason">
        <input id="wo-cancel-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} className={inputClass} />
      </Field>
    </ActionModal>
  )
}

// ---------- breakdowns ----------
export function LogBreakdownModal({ canRaise, onClose, onDone }: {
  canRaise: boolean; onClose: () => void; onDone: (b: Breakdown) => void
}) {
  const [equipment, setEquipment] = useState('')
  const [when, setWhen] = useState(nowInput())
  const [severity, setSeverity] = useState<Severity>('major')
  const [category, setCategory] = useState<FaultCategory>('mechanical')
  const [description, setDescription] = useState('')
  const [cause, setCause] = useState('')
  const [down, setDown] = useState(true)
  const [raise, setRaise] = useState(canRaise)
  return (
    <ActionModal wide title="Log a breakdown" description="Record an equipment failure as soon as it happens."
      submitLabel="Log breakdown" onClose={onClose} onDone={onDone}
      validate={() => (!equipment ? 'Choose the equipment.'
        : whenProblem(when, 'failure time') ?? (description.trim().length < 5 ? 'Describe what failed.' : null))}
      action={() => send<Breakdown>('/maintenance/breakdowns', {
        equipment_id: Number(equipment), started_at: zonedInputToIso(when), severity, category,
        description: description.trim(), possible_cause: cause.trim() || null, equipment_down: down,
        create_work_order: raise,
      })}>
      <EquipmentSelect id="bd-equipment" value={equipment} onChange={setEquipment} />
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="bd-started" label="Failure started">
          <input id="bd-started" type="datetime-local" max={nowInput()} value={when} onChange={(e) => setWhen(e.target.value)} className={inputClass} />
        </Field>
        <Select id="bd-severity" label="Severity" value={severity} onChange={setSeverity} options={SEVERITY_LABELS} />
        <Select id="bd-category" label="Fault category" value={category} onChange={setCategory} options={FAULT_LABELS} />
      </div>
      <Field id="bd-description" label="What failed">
        <textarea id="bd-description" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} className={area}
          placeholder="Symptoms, alarms, what the operator saw" />
      </Field>
      <Field id="bd-cause" label="Possible cause (optional)">
        <input id="bd-cause" value={cause} onChange={(e) => setCause(e.target.value)} className={inputClass} />
      </Field>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="flex items-start gap-2.5 rounded-xl border border-line p-3 text-sm has-checked:border-accent has-checked:bg-sky-50">
          <input type="checkbox" checked={down} onChange={(e) => setDown(e.target.checked)} className="mt-0.5 size-4" />
          <span><span className="font-semibold text-ink">Equipment is stopped</span><br />
            <span className="text-ink-muted">Counts as downtime and marks it out of service.</span></span>
        </label>
        {canRaise && (
          <label className="flex items-start gap-2.5 rounded-xl border border-line p-3 text-sm has-checked:border-accent has-checked:bg-sky-50">
            <input type="checkbox" checked={raise} onChange={(e) => setRaise(e.target.checked)} className="mt-0.5 size-4" />
            <span><span className="font-semibold text-ink">Raise a repair work order</span><br />
              <span className="text-ink-muted">Priority follows the severity.</span></span>
          </label>
        )}
      </div>
    </ActionModal>
  )
}

export function RestoreBreakdownModal({ bd, onClose, onDone }: { bd: Breakdown; onClose: () => void; onDone: (b: Breakdown) => void }) {
  const when = useWhen()
  const [actions, setActions] = useState(bd.actions_taken ?? '')
  return (
    <ActionModal title={`Restore ${bd.number}`} description={`${bd.equipment.code} · ${bd.description}`}
      submitLabel="Record restoration" onClose={onClose} onDone={onDone}
      validate={() => (when.edited ? whenProblem(when.value, 'restoration time', bd.started_at) : null)
        ?? (actions.trim().length < 5 ? 'Describe the repairs and actions taken.' : null)}
      action={() => send<Breakdown>(`/maintenance/breakdowns/${bd.id}/restore`, {
        restored_at: when.iso(), actions_taken: actions.trim(),
      })}>
      <Field id="bd-restored" label="Back in service at">
        <input id="bd-restored" type="datetime-local" max={nowInput()} value={when.value}
          onChange={(e) => when.onChange(e.target.value)} className={inputClass} />
      </Field>
      <Field id="bd-actions" label="Repairs and actions taken">
        <textarea id="bd-actions" rows={3} value={actions} onChange={(e) => setActions(e.target.value)} className={area} />
      </Field>
    </ActionModal>
  )
}

export function EditBreakdownModal({ bd, onClose, onDone }: { bd: Breakdown; onClose: () => void; onDone: (b: Breakdown) => void }) {
  const [severity, setSeverity] = useState<Severity>(bd.severity)
  const [category, setCategory] = useState<FaultCategory>(bd.category)
  const [cause, setCause] = useState(bd.possible_cause ?? '')
  const [actions, setActions] = useState(bd.actions_taken ?? '')
  return (
    <ActionModal title={`Update ${bd.number}`} description={`${bd.equipment.code} · ${bd.description}`}
      submitLabel="Save" onClose={onClose} onDone={onDone}
      action={() => send<Breakdown>(`/maintenance/breakdowns/${bd.id}`, {
        severity, category, possible_cause: cause.trim() || null, actions_taken: actions.trim() || null,
      }, 'PATCH')}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Select id="bd-edit-severity" label="Severity" value={severity} onChange={setSeverity} options={SEVERITY_LABELS} />
        <Select id="bd-edit-category" label="Fault category" value={category} onChange={setCategory} options={FAULT_LABELS} />
      </div>
      <Field id="bd-edit-cause" label="Possible cause">
        <textarea id="bd-edit-cause" rows={2} value={cause} onChange={(e) => setCause(e.target.value)} className={area} />
      </Field>
      <Field id="bd-edit-actions" label="Repairs and actions taken">
        <textarea id="bd-edit-actions" rows={2} value={actions} onChange={(e) => setActions(e.target.value)} className={area} />
      </Field>
    </ActionModal>
  )
}
