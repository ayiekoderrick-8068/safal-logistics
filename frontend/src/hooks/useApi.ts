import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'

interface ApiState<T> {
  /** Latest successful data; kept while a new request is in flight (shown as stale). */
  data: T | undefined
  error: ApiError | undefined
  loading: boolean
  refetch: () => void
}

interface Result<T> {
  key: string | null
  data?: T
  error?: ApiError
}

/** Fetch JSON from the API; re-runs when `path` changes. Pass null to skip. */
export function useApi<T>(path: string | null): ApiState<T> {
  const [nonce, setNonce] = useState(0)
  const key = path === null ? null : `${nonce}:${path}`
  const [result, setResult] = useState<Result<T>>({ key: null })

  useEffect(() => {
    if (path === null || key === null) return
    const controller = new AbortController()
    api<T>(path, { signal: controller.signal })
      .then((data) => setResult({ key, data }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        const error = err instanceof ApiError ? err : new ApiError(0, 'Unexpected error')
        setResult((prev) => ({ key, data: prev.data, error }))
      })
    return () => controller.abort()
  }, [path, key])

  const refetch = useCallback(() => setNonce((n) => n + 1), [])
  const settled = result.key === key
  return {
    data: result.data,
    error: settled ? result.error : undefined,
    loading: key !== null && !settled,
    refetch,
  }
}
