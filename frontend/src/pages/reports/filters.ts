/** Report filter state. The applied filters live in the URL so a report view is shareable,
 * and the same query string is sent to every analytics endpoint and export. */

export type Period = 'today' | 'yesterday' | 'last_7_days' | 'last_30_days' | 'custom'

export interface ReportFilterState {
  period: Period
  start: string
  end: string
  truck_id: string
  driver_id: string
  bay_id: string
  route_id: string
  dispatch_status: string
  delay_cause: string
}

export const PERIOD_LABELS: Record<Period, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  last_7_days: 'Last 7 days',
  last_30_days: 'Last 30 days',
  custom: 'Custom range',
}

export const EMPTY_FILTERS: ReportFilterState = {
  period: 'last_7_days', start: '', end: '', truck_id: '', driver_id: '', bay_id: '', route_id: '',
  dispatch_status: '', delay_cause: '',
}

const KEYS = Object.keys(EMPTY_FILTERS) as (keyof ReportFilterState)[]

export function fromSearchParams(params: URLSearchParams): ReportFilterState {
  const f = { ...EMPTY_FILTERS }
  for (const k of KEYS) {
    const v = params.get(k)
    if (v) (f as Record<string, string>)[k] = v
  }
  if (!(f.period in PERIOD_LABELS)) f.period = 'last_7_days'
  return f
}

/** Query string for the API (only non-empty values; dates only for custom ranges). */
export function toQuery(f: ReportFilterState): string {
  const q = new URLSearchParams({ period: f.period })
  if (f.period === 'custom') {
    if (f.start) q.set('start', f.start)
    if (f.end) q.set('end', f.end)
  }
  for (const k of ['truck_id', 'driver_id', 'bay_id', 'route_id', 'dispatch_status', 'delay_cause'] as const) {
    if (f[k]) q.set(k, f[k])
  }
  return q.toString()
}

export function validate(f: ReportFilterState): string | null {
  if (f.period !== 'custom') return null
  if (!f.start || !f.end) return 'Choose both a start and an end date for a custom range.'
  if (f.start > f.end) return 'The start date must be on or before the end date.'
  const days = (Date.parse(f.end) - Date.parse(f.start)) / 86_400_000 + 1
  if (days > 366) return 'A report can cover at most 366 days.'
  return null
}

export function activeFilterCount(f: ReportFilterState): number {
  return (['truck_id', 'driver_id', 'bay_id', 'route_id', 'dispatch_status', 'delay_cause'] as const)
    .filter((k) => f[k]).length
}
