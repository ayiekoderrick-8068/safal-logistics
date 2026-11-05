import { APP_TIMEZONE } from './format'

/**
 * Form inputs (datetime-local) are interpreted in the operations timezone, not the
 * browser's, so a dispatcher abroad still records Nairobi times correctly.
 */

interface Parts {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
}

function zonedParts(date: Date, timeZone: string): Parts {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(date)
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value)
  return { year: get('year'), month: get('month'), day: get('day'), hour: get('hour'), minute: get('minute'), second: get('second') }
}

/** Minutes the timezone is ahead of UTC at the given instant (Nairobi: 180). */
export function tzOffsetMinutes(date: Date, timeZone = APP_TIMEZONE): number {
  const p = zonedParts(date, timeZone)
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second)
  const exact = Math.floor(date.getTime() / 1000) * 1000
  return Math.round((asUtc - exact) / 60000)
}

const pad = (n: number) => String(n).padStart(2, '0')

/** Date -> "YYYY-MM-DDTHH:mm" wall-clock value in the timezone (for datetime-local inputs). */
export function toZonedInput(date: Date, timeZone = APP_TIMEZONE): string {
  const p = zonedParts(date, timeZone)
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`
}

/** "YYYY-MM-DDTHH:mm" in the timezone -> ISO-8601 UTC string. */
export function zonedInputToIso(value: string, timeZone = APP_TIMEZONE): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value)
  if (!m) throw new Error('Invalid date/time')
  const guess = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  const offset = tzOffsetMinutes(new Date(guess), timeZone)
  return new Date(guess - offset * 60_000).toISOString()
}

export function formatClock(iso: string | null | undefined, timeZone = APP_TIMEZONE): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone }).format(
    new Date(iso),
  )
}

export function minutesBetween(fromIso: string, toIso: string): number {
  return Math.round((new Date(toIso).getTime() - new Date(fromIso).getTime()) / 60_000)
}

export function isValidZonedInput(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)
}
