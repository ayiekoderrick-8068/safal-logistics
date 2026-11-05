import { APP_TIMEZONE } from '../../lib/format'

export const PERIODS = [
  { value: '7', label: 'Last 7 days' },
  { value: '14', label: 'Last 14 days' },
  { value: '30', label: 'Last 30 days' },
] as const

export type PeriodValue = (typeof PERIODS)[number]['value']

/** Today's calendar date (YYYY-MM-DD) in the operations timezone. */
export function todayIn(timeZone = APP_TIMEZONE, now = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
}

export function addDays(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

export function periodRange(days: number, today = todayIn()): { start: string; end: string } {
  return { start: addDays(today, -(days - 1)), end: today }
}
