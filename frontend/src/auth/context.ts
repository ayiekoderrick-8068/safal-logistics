import { createContext, useContext } from 'react'
import type { Role, SessionUser, User, Workspace } from '../lib/types'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  status: AuthStatus
  user: SessionUser | null
  /** The workspace the current session is bound to (null when signed out). */
  workspace: Workspace | null
  /** True when a signed-in session was rejected by the server (expired or revoked). */
  sessionExpired: boolean
  login: (username: string, password: string, workspace?: Workspace) => Promise<SessionUser>
  /** Move the session to another workspace. Always requires the password. */
  switchWorkspace: (workspace: Workspace, password: string) => Promise<SessionUser>
  logout: () => Promise<void>
  /** Logistics role check (administrators always pass). */
  hasRole: (...roles: Role[]) => boolean
  canAccess: (workspace: Workspace) => boolean
  updateUser: (user: User) => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

export const WORKSPACE_HOME: Record<Workspace, string> = { logistics: '/', maintenance: '/maintenance' }
export const WORKSPACE_LOGIN: Record<Workspace, string> = {
  logistics: '/login',
  maintenance: '/maintenance/login',
}
