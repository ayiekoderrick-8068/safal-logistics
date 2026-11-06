import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, ApiError, setUnauthorizedHandler } from '../lib/api'
import type { Role, User } from '../lib/types'
import { AuthContext, type AuthStatus } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [sessionExpired, setSessionExpired] = useState(false)
  const statusRef = useRef<AuthStatus>('loading')
  useEffect(() => {
    statusRef.current = status
  }, [status])

  useEffect(() => {
    let cancelled = false
    api<User>('/auth/me')
      .then((u) => {
        if (!cancelled) {
          setUser(u)
          setStatus('authenticated')
        }
      })
      .catch((err) => {
        if (cancelled) return
        if (!(err instanceof ApiError) || err.status !== 401) console.error(err)
        setStatus('anonymous')
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    // Any API call answered with 401 while signed in means the session expired or was revoked.
    setUnauthorizedHandler(() => {
      if (statusRef.current === 'authenticated') setSessionExpired(true)
      setUser(null)
      setStatus('anonymous')
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const res = await api<{ user: User }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setUser(res.user)
    setSessionExpired(false)
    setStatus('authenticated')
    return res.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await api<void>('/auth/logout', { method: 'POST' })
    } finally {
      setUser(null)
      setSessionExpired(false)
      setStatus('anonymous')
    }
  }, [])

  const hasRole = useCallback(
    (...roles: Role[]) => !!user && (user.role === 'admin' || roles.includes(user.role)),
    [user],
  )

  // After a password change the server returns the updated account.
  const updateUser = useCallback((u: User) => setUser(u), [])

  const value = useMemo(
    () => ({ status, user, sessionExpired, login, logout, hasRole, updateUser }),
    [status, user, sessionExpired, login, logout, hasRole, updateUser],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
