import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { a11y } from '../../components/ui/formA11y'
import { Modal } from '../../components/ui/Modal'
import { api, ApiError } from '../../lib/api'
import type { Driver } from '../../lib/types'

const schema = z.object({
  full_name: z.string().trim().min(2, 'Enter the driver’s full name').max(120),
  phone: z
    .string()
    .trim()
    .refine((v) => v === '' || /^\+?[0-9 ]{7,20}$/.test(v), 'Use 7–20 digits, optionally starting with +'),
  licence_number: z.string().trim().min(3, 'Enter the driving licence number').max(50),
  licence_expiry: z.string(),
})
type Values = z.infer<typeof schema>

export function DriverFormModal({ onClose, onSaved }: { onClose: () => void; onSaved: (d: Driver) => void }) {
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: '', phone: '', licence_number: '', licence_expiry: '' },
  })

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    try {
      const driver = await api<Driver>('/drivers', {
        method: 'POST',
        body: JSON.stringify({
          full_name: v.full_name,
          phone: v.phone || null,
          licence_number: v.licence_number,
          licence_expiry: v.licence_expiry || null,
        }),
      })
      onSaved(driver)
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not save the driver.')
    }
  })

  return (
    <Modal title="Add Driver" description="Drivers can then be assigned to a truck." onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <Field id="driver-name" label="Full name" error={errors.full_name?.message}>
          <input {...a11y('driver-name', errors.full_name?.message)} {...register('full_name')} className={inputClass} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="driver-licence" label="Licence number" error={errors.licence_number?.message}>
            <input {...a11y('driver-licence', errors.licence_number?.message)} {...register('licence_number')}
              className={`${inputClass} uppercase`} />
          </Field>
          <Field id="driver-licence-expiry" label="Licence expiry (optional)">
            <input type="date" id="driver-licence-expiry" {...register('licence_expiry')} className={inputClass} />
          </Field>
        </div>
        <Field id="driver-phone" label="Phone (optional)" error={errors.phone?.message}>
          <input type="tel" {...a11y('driver-phone', errors.phone?.message)} {...register('phone')}
            placeholder="+254 7XX XXX XXX" className={inputClass} />
        </Field>
        <FormActions submitLabel="Save driver" submitting={isSubmitting} onCancel={onClose} />
      </form>
    </Modal>
  )
}
