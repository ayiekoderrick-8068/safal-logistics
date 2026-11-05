import { describe, expect, it } from 'vitest'
import { addDays, periodRange, todayIn } from '../pages/overview/period'
import { describeChange, formatDuration, formatPercent, initials } from './format'

describe('formatDuration', () => {
  it('shows hours with one decimal from 60 minutes up', () => {
    expect(formatDuration(144)).toBe('2.4 h')
    expect(formatDuration(45)).toBe('45 min')
  })
  it('renders missing values as a dash, never zero', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatPercent(undefined)).toBe('—')
  })
})

describe('describeChange', () => {
  it('treats a lower turnaround as an improvement', () => {
    expect(describeChange(118, 144, 'pct', false)).toEqual({ text: '−18%', direction: 'down', good: true })
  })
  it('reports percentage-point differences', () => {
    expect(describeChange(92.3, 86.5, 'pp', true)).toEqual({ text: '+5.8 pp', direction: 'up', good: true })
  })
  it('returns null when either period has no data', () => {
    expect(describeChange(null, 3, 'abs', false)).toBeNull()
    expect(describeChange(3, null, 'abs', false)).toBeNull()
  })
  it('does not divide by zero', () => {
    expect(describeChange(5, 0, 'pct', true)?.text).toBe('New activity')
  })
})

describe('period helpers', () => {
  it('uses the Nairobi calendar day', () => {
    // 22:30 UTC on Nov 4 is already Nov 5 in Nairobi (UTC+3)
    expect(todayIn('Africa/Nairobi', new Date('2026-11-04T22:30:00Z'))).toBe('2026-11-05')
  })
  it('builds inclusive ranges across month boundaries', () => {
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31')
    expect(periodRange(7, '2026-11-07')).toEqual({ start: '2026-11-01', end: '2026-11-07' })
  })
})

it('builds avatar initials', () => {
  expect(initials('Derrick  Ayieko')).toBe('DA')
})
