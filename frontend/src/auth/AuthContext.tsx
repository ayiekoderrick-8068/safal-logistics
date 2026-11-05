import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, setUnauthorizedHandler } from '../lib/api'
import type { Role, User } from '../lib/types'
import { AuthContext, type AuthStatus } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')

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
    setUnauthorizedHandler(() => {
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
    setStatus('authenticated')
    return res.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await api<void>('/auth/logout', { method: 'POST' })
    } finally {
      setUser(null)
      setStatus('anonymous')
    }
  }, [])

  const hasRole = useCallback(
    (...roles: Role[]) => !!user && (user.role === 'admin' || roles.includes(user.role)),
    [user],
  )

  const value = useMemo(
    () => ({ status, user, login, logout, hasRole }),
    [status, user, login, logout, hasRole],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
