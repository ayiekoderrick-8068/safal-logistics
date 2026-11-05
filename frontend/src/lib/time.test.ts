import { describe, expect, it } from 'vitest'
import { nextEvent } from '../pages/loading/events'
import { truckSchema } from '../pages/fleet/truckSchema'
import { formatClock, minutesBetween, toZonedInput, tzOffsetMinutes, zonedInputToIso } from './time'

describe('operations timezone helpers', () => {
  it('treats form input as Nairobi wall-clock time (UTC+3), whatever the browser zone', () => {
    expect(zonedInputToIso('2026-11-05T08:30')).toBe('2026-11-05T05:30:00.000Z')
    expect(tzOffsetMinutes(new Date('2026-11-05T05:30:00Z'))).toBe(180)
  })
  it('round-trips through the input format', () => {
    const d = new Date('2026-11-04T22:15:00Z') // 01:15 next day in Nairobi
    expect(toZonedInput(d)).toBe('2026-11-05T01:15')
    expect(zonedInputToIso(toZonedInput(d))).toBe(d.toISOString())
  })
  it('works for zones with DST', () => {
    expect(zonedInputToIso('2026-07-01T12:00', 'Europe/London')).toBe('2026-07-01T11:00:00.000Z')
    expect(zonedInputToIso('2026-12-01T12:00', 'Europe/London')).toBe('2026-12-01T12:00:00.000Z')
  })
  it('formats clock times and durations', () => {
    expect(formatClock('2026-11-05T05:30:00Z')).toBe('08:30')
    expect(minutesBetween('2026-11-05T05:30:00Z', '2026-11-05T07:54:00Z')).toBe(144)
  })
  it('rejects malformed input', () => {
    expect(() => zonedInputToIso('5/11/2026 08:30')).toThrow()
  })
})

describe('loading workflow steps', () => {
  it('follows arrival -> loading start -> loading finish', () => {
    expect(nextEvent('scheduled')).toBe('arrived')
    expect(nextEvent('arrived')).toBe('loading_started')
    expect(nextEvent('loading')).toBe('loading_finished')
    expect(nextEvent('loaded')).toBeNull() // next step is dispatch
    expect(nextEvent('departed')).toBeNull()
  })
})

describe('truck form validation', () => {
  const base = { registration: 'KDA 123A', make: '', model: '', capacity_tonnes: '16', driver_id: '', status: 'available' as const }
  it('accepts a valid truck', () => {
    expect(truckSchema.safeParse(base).success).toBe(true)
  })
  it('rejects bad registrations and capacities', () => {
    expect(truckSchema.safeParse({ ...base, registration: 'KD@ 1' }).success).toBe(false)
    expect(truckSchema.safeParse({ ...base, capacity_tonnes: '0' }).success).toBe(false)
    expect(truckSchema.safeParse({ ...base, capacity_tonnes: '250' }).success).toBe(false)
  })
})
