import { CalendarClock } from 'lucide-react'
import { useEffect } from 'react'
import { Link, useLocation } from 'react-router'
import { useApi } from '../../hooks/useApi'
import { MAINTENANCE_CHANGED, type PmSummary } from '../../lib/maintenance'

const REFRESH_MS = 60_000

/** Top-bar indicator for overdue and due-today preventive maintenance (live counts). */
export function MaintenanceAlerts() {
  const location = useLocation()
  // Refetch on navigation (e.g. after completing a task) and every minute.
  const { data, refetch } = useApi<PmSummary>(`/maintenance/pm/summary?at=${encodeURIComponent(location.key)}`)
  useEffect(() => {
    const id = window.setInterval(refetch, REFRESH_MS)
    window.addEventListener(MAINTENANCE_CHANGED, refetch)
    return () => {
      window.clearInterval(id)
      window.removeEventListener(MAINTENANCE_CHANGED, refetch)
    }
  }, [refetch])

  const overdue = data?.overdue ?? 0
  const today = data?.due_today ?? 0
  const label = data
    ? `${overdue} overdue and ${today} due today preventive maintenance tasks`
    : 'Preventive maintenance alerts'
  return (
    <Link
      to={`/maintenance/preventive?view=${overdue ? 'overdue' : 'due_today'}`}
      className="relative rounded-full p-2 hover:bg-white/10"
      aria-label={label}
      title={label}
    >
      <CalendarClock className="size-6" aria-hidden />
      {overdue + today > 0 && (
        <span
          className={`absolute -top-0.5 -right-0.5 grid min-w-5 place-items-center rounded-full px-1 text-[0.7rem] font-bold text-white ${overdue ? 'bg-red-500' : 'bg-amber-500'}`}
          data-testid="pm-alert-count"
        >
          {overdue + today}
        </span>
      )}
    </Link>
  )
}
