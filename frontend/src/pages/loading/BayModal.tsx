import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { a11y } from '../../components/ui/formA11y'
import { Modal } from '../../components/ui/Modal'
import { api, ApiError } from '../../lib/api'
import type { Bay } from '../../lib/types'

const schema = z.object({
  code: z.string().trim().min(2, 'Enter a short code, e.g. BAY-05').max(20),
  name: z.string().trim().min(2, 'Enter a display name').max(80),
  target: z.string().refine((v) => v === '' || (Number.isInteger(Number(v)) && Number(v) > 0 && Number(v) <= 1440),
    'Whole minutes between 1 and 1440'),
})
type Values = z.infer<typeof schema>

export function BayModal({ onClose, onSaved }: { onClose: () => void; onSaved: (b: Bay) => void }) {
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { code: '', name: '', target: '' },
  })
  const submit = handleSubmit(async (v) => {
    setServerError(null)
    try {
      onSaved(await api<Bay>('/bays', {
        method: 'POST',
        body: JSON.stringify({ code: v.code, name: v.name, target_turnaround_minutes: v.target ? Number(v.target) : null }),
      }))
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not save the bay.')
    }
  })
  return (
    <Modal title="Add Loading Bay" onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="bay-code" label="Code" error={errors.code?.message}>
            <input {...a11y('bay-code', errors.code?.message)} {...register('code')} className={`${inputClass} uppercase`} placeholder="BAY-05" />
          </Field>
          <Field id="bay-name" label="Name" error={errors.name?.message}>
            <input {...a11y('bay-name', errors.name?.message)} {...register('name')} className={inputClass} placeholder="Bay 05" />
          </Field>
        </div>
        <Field id="bay-target" label="Turnaround target in minutes (optional)" error={errors.target?.message}
          hint="Leave blank to use the global target.">
          <input type="number" min="1" {...a11y('bay-target', errors.target?.message, true)} {...register('target')} className={inputClass} />
        </Field>
        <FormActions submitLabel="Add bay" submitting={isSubmitting} onCancel={onClose} />
      </form>
    </Modal>
  )
}
