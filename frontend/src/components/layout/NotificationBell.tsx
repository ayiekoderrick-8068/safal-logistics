import { Bell } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { useApi } from '../../hooks/useApi'
import type { AlertSummary } from '../../lib/types'
import { AlertItem } from '../alerts/AlertList'

const POLL_MS = 60_000

/** Top-bar alert bell: unread badge (critical + warning) and a dropdown of the latest alerts. */
export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [tick, setTick] = useState(0)
  const location = useLocation()
  const ref = useRef<HTMLDivElement>(null)
  const { data } = useApi<AlertSummary>(`/alerts/summary?t=${tick}`)

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), POLL_MS)
    return () => window.clearInterval(id)
  }, [])
  // Close on navigation (render-time adjustment instead of an effect).
  const [path, setPath] = useState(location.pathname)
  if (path !== location.pathname) {
    setPath(location.pathname)
    setOpen(false)
  }
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  const urgent = data ? data.critical + data.warning : 0
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={`Alerts${urgent ? `: ${urgent} need attention` : ''}`}
        className="relative rounded-lg p-2 text-white/90 hover:bg-white/10"
      >
        <Bell className="size-6" />
        {urgent > 0 && (
          <span className="absolute -top-0.5 -right-0.5 grid min-w-5 place-items-center rounded-full bg-red-500 px-1 text-[0.7rem] font-bold text-white ring-2 ring-topbar"
            data-testid="alert-badge">
            {urgent > 99 ? '99+' : urgent}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-[22rem] max-w-[calc(100vw-2rem)] rounded-2xl border border-line bg-white p-3 text-ink shadow-xl">
          <div className="mb-2 flex items-center justify-between px-1">
            <p className="font-semibold">Alerts</p>
            {data && (
              <p className="text-xs text-ink-muted">
                <span className="font-semibold text-red-600">{data.critical} critical</span> · {data.warning} warning · {data.info} info
              </p>
            )}
          </div>
          {!data ? <p className="px-1 py-4 text-sm text-ink-muted">Loading…</p>
            : data.latest.length === 0 ? <p className="px-1 py-4 text-sm text-ink-muted">No open alerts.</p>
            : <ul className="max-h-96 space-y-2 overflow-y-auto">{data.latest.map((a) => <AlertItem key={a.id} alert={a} />)}</ul>}
          <Link to="/alerts" className="mt-3 block rounded-xl bg-surface-muted px-3 py-2 text-center text-sm font-semibold text-primary hover:bg-sky-100">
            View all alerts
          </Link>
        </div>
      )}
    </div>
  )
}
