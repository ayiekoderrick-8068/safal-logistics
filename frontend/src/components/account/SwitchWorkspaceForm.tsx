import { Eye, EyeOff, LoaderCircle } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { useAuth, WORKSPACE_HOME } from '../../auth/context'
import { ApiError } from '../../lib/api'
import { WORKSPACE_LABELS } from '../../lib/format'
import type { Workspace } from '../../lib/types'
import { btnPrimary, inputClass } from '../ui/buttons'
import { FormError } from '../ui/Form'

/**
 * Password confirmation for moving the session to another workspace. Used by the
 * account menu and by the gate shown when a URL belongs to the other workspace.
 */
export function SwitchWorkspaceForm({
  target,
  redirectTo,
  footer,
}: {
  target: Workspace
  /** Where to go after switching; defaults to the target workspace's home. */
  redirectTo?: string
  footer?: ReactNode
}) {
  const { user, switchWorkspace } = useAuth()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!password) {
      setError('Enter your password to continue.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await switchWorkspace(target, password)
      navigate(redirectTo ?? WORKSPACE_HOME[target], { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not switch workspace. Please try again.')
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={error} />
      {/* Lets password managers attach the password to the right account. */}
      <input type="text" name="username" autoComplete="username" value={user?.username ?? ''} readOnly hidden />
      <div>
        <label htmlFor="switch-password" className="mb-1.5 block text-sm font-semibold text-ink">Password</label>
        <div className="relative">
          <input
            id="switch-password"
            type={show ? 'text' : 'password'}
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy}
            className={`${inputClass} pr-12`}
          />
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            className="absolute inset-y-0 right-0 grid w-12 place-items-center text-ink-muted hover:text-ink"
            aria-label={show ? 'Hide password' : 'Show password'}
            aria-pressed={show}
          >
            {show ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
          </button>
        </div>
      </div>
      <div className={`flex flex-col-reverse gap-3 pt-1 sm:flex-row sm:items-center ${footer ? 'sm:justify-between' : ''}`}>
        {footer}
        <button type="submit" disabled={busy} className={`${btnPrimary} ${footer ? '' : 'w-full'}`}>
          {busy && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
          Open {WORKSPACE_LABELS[target]}
        </button>
      </div>
    </form>
  )
}
