import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { statusTone } from '../../lib/statusColors'
import { StatusBadge } from './StatusBadge'

it('maps operational statuses to green / amber / red', () => {
  expect(statusTone('delivered')).toBe('green')
  expect(statusTone('in_transit')).toBe('amber')
  expect(statusTone('delayed')).toBe('red')
  expect(statusTone('something_new')).toBe('slate')
})

it('humanises the status label', () => {
  render(<StatusBadge status="in_transit" />)
  expect(screen.getByText('In Transit')).toBeInTheDocument()
})
