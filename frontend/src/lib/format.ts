export const APP_TIMEZONE = 'Africa/Nairobi'

export function formatNumber(value: number | null | undefined): string {
  return value == null ? '—' : new Intl.NumberFormat('en-KE').format(value)
}

export function formatPercent(value: number | null | undefined): string {
  return value == null ? '—' : `${value.toFixed(1)}%`
}

/** 144 -> "2.4 h", 45 -> "45 min" */
export function formatDuration(minutes: number | null | undefined): string {
  if (minutes == null) return '—'
  if (minutes < 60) return `${Math.round(minutes)} min`
  return `${(minutes / 60).toFixed(1)} h`
}

export function formatDateTime(iso: string | null | undefined, timeZone = APP_TIMEZONE): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone,
  }).format(new Date(iso))
}

export function formatDate(isoDate: string): string {
  // Plain dates (YYYY-MM-DD) are calendar days: format without timezone shifting.
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
    .format(new Date(Date.UTC(y, m - 1, d)))
}

export function formatDayLabel(isoDate: string): { weekday: string; date: string } {
  const [y, m, d] = isoDate.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  return {
    weekday: dt.toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' }),
    date: dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }),
  }
}

export type Trend = { text: string; direction: 'up' | 'down' | 'flat'; good: boolean | null }

/**
 * Describe the change between two periods.
 * mode "pct" = relative % change; "pp" = percentage-point difference; "abs" = absolute.
 * higherIsBetter decides whether the change is coloured as good or bad.
 */
export function describeChange(
  current: number | null,
  previous: number | null,
  mode: 'pct' | 'pp' | 'abs',
  higherIsBetter: boolean,
): Trend | null {
  if (current == null || previous == null) return null
  const diff = current - previous
  if (Math.abs(diff) < 1e-9) return { text: 'No change', direction: 'flat', good: null }
  const direction = diff > 0 ? 'up' : 'down'
  const good = diff > 0 === higherIsBetter
  const sign = diff > 0 ? '+' : '−'
  let text: string
  if (mode === 'pct') {
    if (previous === 0) return { text: 'New activity', direction, good }
    text = `${sign}${Math.abs((diff / previous) * 100).toFixed(0)}%`
  } else if (mode === 'pp') {
    text = `${sign}${Math.abs(diff).toFixed(1)} pp`
  } else {
    text = `${sign}${formatNumber(Math.abs(diff))}`
  }
  return { text, direction, good }
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
}

export const ROLE_LABELS: Record<string, string> = {
  admin: 'Administrator',
  operations: 'Operations',
  fleet_manager: 'Fleet Manager',
  compliance: 'Compliance',
  viewer: 'Viewer',
}

export const DELAY_CAUSE_LABELS: Record<string, string> = {
  loading_congestion: 'Loading congestion',
  documentation: 'Documentation issue',
  truck_unavailability: 'Truck unavailability',
  equipment_breakdown: 'Equipment breakdown',
  traffic: 'Traffic / road conditions',
  other: 'Other',
}

export function humanize(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
