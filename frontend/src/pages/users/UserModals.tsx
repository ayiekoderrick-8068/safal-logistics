import { zodResolver } from '@hookform/resolvers/zod'
import { Copy, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { btnSmallGhost, inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { a11y } from '../../components/ui/formA11y'
import { Modal } from '../../components/ui/Modal'
import { api, ApiError } from '../../lib/api'
import { MAINTENANCE_ROLE_LABELS, ROLE_LABELS } from '../../lib/format'
import { generatePassword, passwordRule } from '../../lib/passwords'
import type { AdminUser, MaintenanceRole, Role } from '../../lib/types'

const ROLES = Object.keys(ROLE_LABELS) as Role[]
const MAINTENANCE_ROLES = Object.keys(MAINTENANCE_ROLE_LABELS) as MaintenanceRole[]
const MAINTENANCE_HELP: Record<MaintenanceRole | '', string> = {
  '': 'No access to the Maintenance workspace.',
  manager: 'Everything in Maintenance, including settings.',
  planner: 'Equipment, preventive plans, work-order planning and assignment, reports.',
  technician: 'Work on assigned orders, log breakdowns, use spare parts.',
  storekeeper: 'Spare-parts stock and consumption, reports.',
  viewer: 'Read-only access to maintenance records and reports.',
}
const ROLE_HELP: Record<Role, string> = {
  admin: 'Full access, including user management.',
  operations: 'Bays, schedules, dispatch, delivery and operational reports.',
  fleet_manager: 'Trucks, drivers, compliance documents and reports.',
  compliance: 'Compliance documents, requirements and compliance reports.',
  viewer: 'Read-only access to dashboards and analytics.',
}

function TempPasswordField({
  id, value, error, onChange,
}: { id: string; value: string; error?: string; onChange: (v: string) => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <Field id={id} label="Temporary password" error={error}
      hint="The user must change it at first sign-in. Share it through a secure channel.">
      <div className="flex gap-2">
        <input {...a11y(id, error)} value={value} onChange={(e) => onChange(e.target.value)}
          autoComplete="off" spellCheck={false} className={`${inputClass} font-mono`} />
        <button type="button" className={btnSmallGhost} onClick={() => { onChange(generatePassword()); setCopied(false) }}
          aria-label="Generate a temporary password">
          <RefreshCw className="size-3.5" aria-hidden /> Generate
        </button>
        <button type="button" className={btnSmallGhost} disabled={!value}
          onClick={async () => { await navigator.clipboard?.writeText(value); setCopied(true) }}
          aria-label="Copy the temporary password">
          <Copy className="size-3.5" aria-hidden /> {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </Field>
  )
}

const createSchema = z.object({
  full_name: z.string().trim().min(2, 'Enter the person’s full name').max(120),
  username: z.string().trim().toLowerCase()
    .regex(/^[a-z0-9][a-z0-9._-]{2,49}$/, '3–50 characters: letters, numbers, dot, dash or underscore'),
  email: z.string().trim().email('Enter a valid email address'),
  role: z.enum(ROLES as [Role, ...Role[]]),
  // Optional: the select is disabled (no value submitted) for administrators.
  maintenance_role: z.enum(['', ...MAINTENANCE_ROLES] as ['', ...MaintenanceRole[]]).optional(),
  temporary_password: passwordRule,
})
const editSchema = createSchema.pick({ full_name: true, role: true, maintenance_role: true })
type CreateValues = z.infer<typeof createSchema>

export function UserFormModal({
  user, isSelf, onClose, onSaved,
}: {
  user?: AdminUser
  isSelf: boolean
  onClose: () => void
  onSaved: (u: AdminUser, created: boolean) => void
}) {
  const editing = !!user
  const [serverError, setServerError] = useState<string | null>(null)
  const { register, handleSubmit, control, setValue, formState: { errors, isSubmitting } } = useForm<CreateValues>({
    // Editing validates only the editable fields.
    resolver: zodResolver(editing ? (editSchema as unknown as typeof createSchema) : createSchema),
    defaultValues: {
      full_name: user?.full_name ?? '',
      username: user?.username ?? '',
      email: user?.email ?? '',
      role: user?.role ?? 'viewer',
      maintenance_role: user?.maintenance_role ?? '',
      temporary_password: '',
    },
  })
  const role = useWatch({ control, name: 'role' })
  const maintenanceRole = useWatch({ control, name: 'maintenance_role' })
  const tempPassword = useWatch({ control, name: 'temporary_password' })

  const submit = handleSubmit(async (v) => {
    setServerError(null)
    const maintenance_role = v.maintenance_role || null
    try {
      const saved = editing
        ? await api<AdminUser>(`/users/${user.id}`, {
            method: 'PATCH',
            body: JSON.stringify(
              isSelf
                ? { full_name: v.full_name }
                : { full_name: v.full_name, role: v.role, maintenance_role },
            ),
          })
        : await api<AdminUser>('/users', { method: 'POST', body: JSON.stringify({ ...v, maintenance_role }) })
      onSaved(saved, !editing)
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not save the user.')
    }
  })

  return (
    <Modal title={editing ? 'Edit User' : 'Add User'}
      description={editing ? `${user.username} · ${user.email}` : 'The account is active immediately with a temporary password.'}
      onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <Field id="user-name" label="Full name" error={errors.full_name?.message}>
          <input {...a11y('user-name', errors.full_name?.message)} {...register('full_name')} className={inputClass} />
        </Field>
        {!editing && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="user-username" label="Username" error={errors.username?.message}>
              <input {...a11y('user-username', errors.username?.message)} {...register('username')}
                autoCapitalize="none" spellCheck={false} className={inputClass} />
            </Field>
            <Field id="user-email" label="Email" error={errors.email?.message}>
              <input type="email" {...a11y('user-email', errors.email?.message)} {...register('email')} className={inputClass} />
            </Field>
          </div>
        )}
        <Field id="user-role" label="Role" error={errors.role?.message}
          hint={isSelf ? 'You cannot change your own role.' : ROLE_HELP[role]}>
          <select id="user-role" {...register('role')} disabled={isSelf} className={inputClass}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
          </select>
        </Field>
        <Field id="user-maintenance-role" label="Maintenance workspace"
          hint={role === 'admin'
            ? 'Administrators always have full access to Maintenance.'
            : MAINTENANCE_HELP[maintenanceRole ?? '']}>
          <select id="user-maintenance-role" {...register('maintenance_role')}
            disabled={isSelf || role === 'admin'} className={inputClass}>
            <option value="">No access</option>
            {MAINTENANCE_ROLES.map((r) => <option key={r} value={r}>{MAINTENANCE_ROLE_LABELS[r]}</option>)}
          </select>
        </Field>
        {!editing && (
          <TempPasswordField id="user-temp-password" value={tempPassword}
            error={errors.temporary_password?.message}
            onChange={(v) => setValue('temporary_password', v, { shouldValidate: true })} />
        )}
        <FormActions submitLabel={editing ? 'Save changes' : 'Create user'} submitting={isSubmitting} onCancel={onClose} />
      </form>
    </Modal>
  )
}

export function ResetPasswordModal({
  user, onClose, onSaved,
}: { user: AdminUser; onClose: () => void; onSaved: (u: AdminUser) => void }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | undefined>()
  const [serverError, setServerError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const check = passwordRule.safeParse(value)
    if (!check.success) {
      setError(check.error.issues[0]?.message)
      return
    }
    setError(undefined)
    setServerError(null)
    setBusy(true)
    try {
      onSaved(await api<AdminUser>(`/users/${user.id}/reset-password`, {
        method: 'POST',
        body: JSON.stringify({ temporary_password: value }),
      }))
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not reset the password.')
      setBusy(false)
    }
  }

  return (
    <Modal title="Reset Password"
      description={`${user.full_name} will be signed out and must choose a new password at next sign-in.`}
      onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={serverError} />
        <TempPasswordField id="reset-temp-password" value={value} error={error} onChange={setValue} />
        <FormActions submitLabel="Set temporary password" submitting={busy} onCancel={onClose} />
      </form>
    </Modal>
  )
}
