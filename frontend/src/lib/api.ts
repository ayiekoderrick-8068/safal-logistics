export class ApiError extends Error {
  readonly status: number
  /** Seconds from a Retry-After header (e.g. sign-in lockout), if the server sent one. */
  readonly retryAfter: number | null

  constructor(status: number, message: string, retryAfter: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
  }
}

type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null

/** Registered by the auth provider so an expired session sends the user back to login. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler
}

function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  }
  if (status >= 500) return 'The server ran into a problem. Please try again.'
  return 'Request failed.'
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    // FormData (file uploads) must let the browser set the multipart boundary itself.
    const isForm = typeof FormData !== 'undefined' && init.body instanceof FormData
    res = await fetch(`/api${path}`, {
      credentials: 'same-origin',
      ...init,
      headers: {
        Accept: 'application/json',
        ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        ...init.headers,
      },
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'Cannot reach the LogiTrack server. Check that the API is running.')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null)
    if (res.status === 401 && !path.startsWith('/auth/')) onUnauthorized?.()
    const retry = Number(res.headers.get('Retry-After'))
    throw new ApiError(res.status, errorMessage(res.status, body), Number.isFinite(retry) && retry > 0 ? retry : null)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
