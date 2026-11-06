import { ArrowLeft, LockKeyhole, Truck } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { SwitchWorkspaceForm } from '../components/account/SwitchWorkspaceForm'
import { WORKSPACE_LABELS } from '../lib/format'
import type { Workspace } from '../lib/types'
import { useAuth, WORKSPACE_HOME } from './context'

/** Shown when a URL belongs to the workspace this session is *not* bound to. */
export function WorkspaceGate({ target }: { target: Workspace }) {
  const { workspace, canAccess } = useAuth()
  const location = useLocation()
  const current = workspace ?? 'logistics'
  const allowed = canAccess(target)
  const back = (
    <Link to={WORKSPACE_HOME[current]} className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline">
      <ArrowLeft className="size-4" aria-hidden /> Back to {WORKSPACE_LABELS[current]}
    </Link>
  )

  return (
    <div className="workspace-gradient flex min-h-screen items-center justify-center px-5 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-xl bg-gradient-to-br from-cyan-300 to-accent text-sidebar">
            <Truck className="size-6" aria-hidden />
          </span>
          <div>
            <p className="text-xl leading-tight font-bold text-ink">LogiTrack</p>
            <p className="text-sm text-ink-muted">Operations Portal</p>
          </div>
        </div>
        <div className="card p-7 sm:p-9">
          <span className="mb-4 grid size-12 place-items-center rounded-2xl bg-sky-100 text-primary">
            <LockKeyhole className="size-6" aria-hidden />
          </span>
          {allowed ? (
            <>
              <h1 className="text-2xl font-bold text-ink">Confirm it's you</h1>
              <p className="mt-1 mb-5 text-sm text-ink-muted">
                You are signed in to {WORKSPACE_LABELS[current]}. Enter your password to open{' '}
                {WORKSPACE_LABELS[target]}.
              </p>
              <SwitchWorkspaceForm target={target} redirectTo={location.pathname + location.search} />
              <p className="mt-5 border-t border-line pt-4">{back}</p>
            </>
          ) : (
            <>
              <h1 className="text-2xl font-bold text-ink">Access restricted</h1>
              <p className="mt-1 mb-5 text-sm text-ink-muted">
                Your account does not have access to {WORKSPACE_LABELS[target]}. Ask an administrator to grant it.
              </p>
              {back}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
