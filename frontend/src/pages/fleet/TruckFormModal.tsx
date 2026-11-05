import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { a11y } from '../../components/ui/formA11y'
import { Modal } from '../../components/ui/Modal'
import { useApi } from '../../hooks/useApi'
import { api, ApiError } from '../../lib/api'
import type { Driver, Truck } from '../../lib/types'
import { truckSchema, type TruckValues } from './truckSchema'

export function TruckFormModal({
  truck,
  onClose,
  onSaved,
}: {
  truck?: Truck
  onClose: () => void
  onSaved: (t: Truck) => void
}) {
  const editing = !!truck
  const busy = truck?.status === 'loading' || truck?.status === 'in_transit'
  const [serverError, setServerError] = useState<string | null>(null)
  const drivers = useApi<Driver[]>('/drivers?unassigned=true')
  const driverOptions = [
    ...(truck?.driver ? [{ id: truck.driver.id, full_name: truck.driver.label }] : []),
    ...(drivers.data ?? []),
  ]

  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<TruckValues>({
    resolver: zodResolver(truckSchema),
    defaultValues: {
      registration: truck?.registration ?? '',
      make: truck?.make ?? '',
      model: truck?.model ?? '',
      capacity_tonnes: truck ? String(truck.capacity_tonnes) : '',
      driver_id: truck?.driver ? String(truck.driver.id) : '',
      status: truck?.status ?? 'available',
    },
  })

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    const common = {
      make: v.make || null,
      model: v.model || null,
      capacity_tonnes: Number(v.capacity_tonnes),
      driver_id: v.driver_id ? Number(v.driver_id) : null,
    }
    try {
      const saved = editing
        ? await api<Truck>(`/trucks/${truck.id}`, {
            method: 'PATCH',
            body: JSON.stringify({ ...common, ...(busy ? {} : { status: v.status }) }),
          })
        : await api<Truck>('/trucks', {
            method: 'POST',
            body: JSON.stringify({ ...common, registration: v.registration }),
          })
      onSaved(saved)
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not save the truck.')
    }
  })

  return (
    <Modal
      title={editing ? `Edit ${truck.registration}` : 'Add Truck'}
      description={editing ? 'Update details, driver assignment or availability.' : 'Register a truck in the fleet.'}
      onClose={onClose}
    >
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <Field id="truck-registration" label="Registration number" error={errors.registration?.message}
          hint={editing ? 'Registration cannot be changed.' : 'e.g. KDA 123A'}>
          <input {...a11y('truck-registration', errors.registration?.message, true)} {...register('registration')}
            readOnly={editing} className={`${inputClass} uppercase read-only:bg-slate-50`} autoComplete="off" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="truck-make" label="Make (optional)">
            <input id="truck-make" {...register('make')} className={inputClass} placeholder="Isuzu" />
          </Field>
          <Field id="truck-model" label="Model (optional)">
            <input id="truck-model" {...register('model')} className={inputClass} placeholder="FVZ" />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="truck-capacity" label="Capacity (tonnes)" error={errors.capacity_tonnes?.message}>
            <input type="number" step="0.5" min="0" inputMode="decimal"
              {...a11y('truck-capacity', errors.capacity_tonnes?.message)} {...register('capacity_tonnes')}
              className={inputClass} />
          </Field>
          <Field id="truck-driver" label="Assigned driver"
            hint={drivers.data && drivers.data.length === 0 && !truck?.driver ? 'No unassigned drivers — add one first.' : undefined}>
            <select {...a11y('truck-driver', undefined, true)} {...register('driver_id')} className={inputClass}>
              <option value="">Unassigned</option>
              {driverOptions.map((d) => (
                <option key={d.id} value={d.id}>{d.full_name}</option>
              ))}
            </select>
          </Field>
        </div>
        {editing && (
          <Field id="truck-status" label="Availability"
            hint={busy ? 'Status is controlled by the active load until it is delivered.' : undefined}>
            <select {...a11y('truck-status', undefined, busy)} {...register('status')} disabled={busy} className={inputClass}>
              {busy && <option value={truck.status}>{truck.status === 'loading' ? 'Loading' : 'In transit'}</option>}
              <option value="available">Available</option>
              <option value="maintenance">Under maintenance</option>
              <option value="out_of_service">Out of service</option>
            </select>
          </Field>
        )}
        <FormActions submitLabel={editing ? 'Save changes' : 'Register truck'} submitting={isSubmitting} onCancel={onClose} />
      </form>
    </Modal>
  )
}
