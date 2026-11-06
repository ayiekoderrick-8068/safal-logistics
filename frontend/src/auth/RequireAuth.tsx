import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { LoadingState } from '../components/ui/States'
import type { Workspace } from '../lib/types'
import { useAuth, WORKSPACE_LOGIN } from './context'
import { WorkspaceGate } from './WorkspaceGate'

/**
 * Guards a workspace's routes. Signed out → that workspace's sign-in page (or the
 * workspace chooser for the bare home URL). Signed in to the *other* workspace → a password
 * prompt; there is never automatic cross-workspace access. The API enforces the same rule.
 */
export function RequireAuth({ children, workspace = 'logistics' }: { children: ReactNode; workspace?: Workspace }) {
  const { status, workspace: current } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="workspace-gradient flex min-h-screen items-center justify-center">
        <LoadingState label="Checking your session…" />
      </div>
    )
  }
  if (status === 'anonymous') {
    if (location.pathname === '/') return <Navigate to="/welcome" replace />
    return <Navigate to={WORKSPACE_LOGIN[workspace]} replace state={{ from: location.pathname + location.search }} />
  }
  if (current !== workspace) return <WorkspaceGate target={workspace} />
  return <>{children}</>
}
