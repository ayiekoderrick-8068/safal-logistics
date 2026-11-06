import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { inputClass } from '../../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../../components/ui/Form'
import { a11y } from '../../../components/ui/formA11y'
import { Modal } from '../../../components/ui/Modal'
import { useApi } from '../../../hooks/useApi'
import { api, ApiError } from '../../../lib/api'
import {
  CATEGORY_LABELS,
  EQUIPMENT_STATUS_LABELS,
  type Equipment,
  type EquipmentCategory,
  type EquipmentOptions,
  type EquipmentStatus,
} from '../../../lib/maintenance'
import { MAINTENANCE_ROLE_LABELS } from '../../../lib/format'
import { todayIso } from '../../../lib/time'

const CATEGORIES = Object.keys(CATEGORY_LABELS) as [EquipmentCategory, ...EquipmentCategory[]]
const STATUSES = Object.keys(EQUIPMENT_STATUS_LABELS) as [EquipmentStatus, ...EquipmentStatus[]]
const optionalText = (max: number) => z.string().trim().max(max)

// Mirrors the server rules (the API validates again and is the authority).
const schema = z
  .object({
    code: z.string().trim().toUpperCase()
      .regex(/^[A-Z0-9][A-Z0-9-]{1,29}$/, '2–30 characters: letters, numbers and dashes, e.g. CNV-001'),
    name: z.string().trim().min(2, 'Enter the equipment name').max(120),
    category: z.enum(CATEGORIES),
    manufacturer: optionalText(80),
    model: optionalText(80),
    serial_number: optionalText(80),
    facility: z.string().trim().min(2, 'Enter the facility').max(80),
    department: optionalText(80),
    location: optionalText(120),
    installed_on: z.string(),
    status: z.enum(STATUSES),
    assigned_technician_id: z.string(),
    last_service_on: z.string(),
    next_service_on: z.string(),
    notes: optionalText(2000),
  })
  .refine((v) => !v.installed_on || v.installed_on <= todayIso(), {
    path: ['installed_on'], message: 'The installation date cannot be in the future',
  })
  .refine((v) => !v.last_service_on || v.last_service_on <= todayIso(), {
    path: ['last_service_on'], message: 'The last service date cannot be in the future',
  })
  .refine((v) => !v.last_service_on || !v.installed_on || v.last_service_on >= v.installed_on, {
    path: ['last_service_on'], message: 'Cannot be before the installation date',
  })
  .refine((v) => !v.next_service_on || !v.last_service_on || v.next_service_on >= v.last_service_on, {
    path: ['next_service_on'], message: 'Cannot be before the last service date',
  })
type Values = z.infer<typeof schema>

export function EquipmentFormModal({
  equipment,
  onClose,
  onSaved,
}: {
  equipment?: Equipment
  onClose: () => void
  onSaved: (e: Equipment) => void
}) {
  const editing = !!equipment
  const [serverError, setServerError] = useState<string | null>(null)
  const options = useApi<EquipmentOptions>('/maintenance/equipment/options')
  const e = equipment
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      code: e?.code ?? '',
      name: e?.name ?? '',
      category: e?.category ?? 'conveyor',
      manufacturer: e?.manufacturer ?? '',
      model: e?.model ?? '',
      serial_number: e?.serial_number ?? '',
      facility: e?.facility ?? '',
      department: e?.department ?? '',
      location: e?.location ?? '',
      installed_on: e?.installed_on ?? '',
      status: e?.status ?? 'operational',
      assigned_technician_id: e?.assigned_technician ? String(e.assigned_technician.id) : '',
      last_service_on: e?.last_service_on ?? '',
      next_service_on: e?.next_service_on ?? '',
      notes: e?.notes ?? '',
    },
  })

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    const orNull = (s: string) => (s.trim() ? s.trim() : null)
    const body = {
      name: v.name,
      category: v.category,
      manufacturer: orNull(v.manufacturer),
      model: orNull(v.model),
      serial_number: orNull(v.serial_number),
      facility: v.facility,
      department: orNull(v.department),
      location: orNull(v.location),
      installed_on: v.installed_on || null,
      status: v.status,
      assigned_technician_id: v.assigned_technician_id ? Number(v.assigned_technician_id) : null,
      last_service_on: v.last_service_on || null,
      next_service_on: v.next_service_on || null,
      notes: orNull(v.notes),
    }
    try {
      const saved = editing
        ? await api<Equipment>(`/maintenance/equipment/${equipment.id}`, { method: 'PATCH', body: JSON.stringify(body) })
        : await api<Equipment>('/maintenance/equipment', { method: 'POST', body: JSON.stringify({ ...body, code: v.code }) })
      onSaved(saved)
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not save the equipment.')
    }
  })

  const o = options.data
  const err = (k: keyof Values) => errors[k]?.message
  return (
    <Modal
      title={editing ? `Edit ${equipment.code}` : 'Add Equipment'}
      description={editing ? equipment.name : 'Register an asset in the equipment register.'}
      onClose={onClose}
      wide
    >
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <div className="grid gap-4 sm:grid-cols-[180px_1fr]">
          <Field id="eq-code" label="Equipment ID" error={err('code')} hint={editing ? 'Cannot be changed.' : 'e.g. CNV-001'}>
            <input {...a11y('eq-code', err('code'))} {...register('code')} readOnly={editing}
              autoComplete="off" spellCheck={false} className={`${inputClass} uppercase read-only:bg-slate-50`} />
          </Field>
          <Field id="eq-name" label="Equipment name" error={err('name')}>
            <input {...a11y('eq-name', err('name'))} {...register('name')} className={inputClass}
              placeholder="Line 2 conveyor drive motor" />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field id="eq-category" label="Category">
            <select id="eq-category" {...register('category')} className={inputClass}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
            </select>
          </Field>
          <Field id="eq-manufacturer" label="Manufacturer (optional)" error={err('manufacturer')}>
            <input id="eq-manufacturer" {...register('manufacturer')} className={inputClass} />
          </Field>
          <Field id="eq-model" label="Model (optional)" error={err('model')}>
            <input id="eq-model" {...register('model')} className={inputClass} />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="eq-serial" label="Serial number (optional)" error={err('serial_number')}>
            <input id="eq-serial" {...register('serial_number')} autoComplete="off" spellCheck={false} className={inputClass} />
          </Field>
          <Field id="eq-installed" label="Installation date (optional)" error={err('installed_on')}>
            <input type="date" max={todayIso()} {...a11y('eq-installed', err('installed_on'))} {...register('installed_on')}
              className={inputClass} />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field id="eq-facility" label="Facility" error={err('facility')}>
            <input list="eq-facilities" {...a11y('eq-facility', err('facility'))} {...register('facility')} className={inputClass} />
          </Field>
          <Field id="eq-department" label="Department (optional)" error={err('department')}>
            <input id="eq-department" list="eq-departments" {...register('department')} className={inputClass} />
          </Field>
          <Field id="eq-location" label="Location (optional)" error={err('location')}>
            <input id="eq-location" list="eq-locations" {...register('location')} className={inputClass} placeholder="Line 2, bay 4" />
          </Field>
        </div>
        <datalist id="eq-facilities">{o?.facilities.map((f) => <option key={f} value={f} />)}</datalist>
        <datalist id="eq-departments">{o?.departments.map((f) => <option key={f} value={f} />)}</datalist>
        <datalist id="eq-locations">{o?.locations.map((f) => <option key={f} value={f} />)}</datalist>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="eq-status" label="Operational status">
            <select id="eq-status" {...register('status')} className={inputClass}>
              {STATUSES.map((s) => <option key={s} value={s}>{EQUIPMENT_STATUS_LABELS[s]}</option>)}
            </select>
          </Field>
          <Field id="eq-technician" label="Assigned technician"
            hint={o && o.technicians.length === 0 ? 'No users have a technician, planner or manager role yet.' : undefined}>
            <select id="eq-technician" {...register('assigned_technician_id')} className={inputClass}>
              <option value="">Unassigned</option>
              {o?.technicians.map((t) => (
                <option key={t.id} value={t.id}>{t.full_name} · {MAINTENANCE_ROLE_LABELS[t.maintenance_role]}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="eq-last" label="Last service date (optional)" error={err('last_service_on')}>
            <input type="date" max={todayIso()} {...a11y('eq-last', err('last_service_on'))} {...register('last_service_on')}
              className={inputClass} />
          </Field>
          <Field id="eq-next" label="Next service date (optional)" error={err('next_service_on')}
            hint="Set by preventive-maintenance plans once they are introduced.">
            <input type="date" {...a11y('eq-next', err('next_service_on'))} {...register('next_service_on')} className={inputClass} />
          </Field>
        </div>
        <Field id="eq-notes" label="Notes (optional)" error={err('notes')}>
          <textarea id="eq-notes" rows={3} {...register('notes')} className={`${inputClass} h-auto py-2.5`} />
        </Field>
        <FormActions submitLabel={editing ? 'Save changes' : 'Register equipment'} submitting={isSubmitting} onCancel={onClose} />
      </form>
    </Modal>
  )
}
