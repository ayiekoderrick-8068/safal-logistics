import { zodResolver } from '@hookform/resolvers/zod'
import { LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { btnPrimary, btnSecondary, inputClass } from '../ui/buttons'
import { Field, FormActions, FormError } from '../ui/Form'
import { a11y } from '../ui/formA11y'
import { Modal } from '../ui/Modal'
import { api, ApiError } from '../../lib/api'
import { passwordRule } from '../../lib/passwords'
import type { User } from '../../lib/types'

const schema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password'),
    new_password: passwordRule,
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'The passwords do not match' })
  .refine((v) => v.new_password !== v.current_password, {
    path: ['new_password'],
    message: 'Choose a password different from the current one',
  })
type Values = z.infer<typeof schema>

/**
 * Change your own password. With `required` (temporary password issued by an administrator)
 * the dialog cannot be dismissed; the only other way out is signing out.
 */
export function ChangePasswordModal({
  required = false,
  onClose,
  onChanged,
  onSignOut,
}: {
  required?: boolean
  onClose: () => void
  onChanged: (u: User) => void
  onSignOut?: () => void
}) {
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { current_password: '', new_password: '', confirm: '' },
  })

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    try {
      const user = await api<User>('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: v.current_password, new_password: v.new_password }),
      })
      onChanged(user)
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not change the password.')
    }
  })

  return (
    <Modal
      title={required ? 'Set a new password' : 'Change password'}
      description={
        required
          ? 'An administrator issued you a temporary password. Choose your own to continue.'
          : 'Other devices signed in to your account will be signed out.'
      }
      onClose={required ? () => {} : onClose}
    >
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <Field id="pw-current" label={required ? 'Temporary password' : 'Current password'}
          error={errors.current_password?.message}>
          <input type="password" autoComplete="current-password"
            {...a11y('pw-current', errors.current_password?.message)} {...register('current_password')}
            className={inputClass} />
        </Field>
        <Field id="pw-new" label="New password" error={errors.new_password?.message}
          hint="At least 8 characters, with letters, numbers and a symbol.">
          <input type="password" autoComplete="new-password"
            {...a11y('pw-new', errors.new_password?.message)} {...register('new_password')} className={inputClass} />
        </Field>
        <Field id="pw-confirm" label="Confirm new password" error={errors.confirm?.message}>
          <input type="password" autoComplete="new-password"
            {...a11y('pw-confirm', errors.confirm?.message)} {...register('confirm')} className={inputClass} />
        </Field>
        {required ? (
          <div className="flex flex-col-reverse items-stretch gap-3 pt-2 sm:flex-row sm:items-center sm:justify-between">
            <button type="button" onClick={onSignOut} className={`${btnSecondary} border-line`}>Sign out instead</button>
            <button type="submit" disabled={isSubmitting} className={btnPrimary}>
              {isSubmitting && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
              Save password
            </button>
          </div>
        ) : (
          <FormActions submitLabel="Save password" submitting={isSubmitting} onCancel={onClose} />
        )}
      </form>
    </Modal>
  )
}
