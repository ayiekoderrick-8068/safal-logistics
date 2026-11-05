import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DriverHistory } from './DriverHistory'

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const HISTORY = [
  {
    id: 2, driver: { id: 2, label: 'Ben Kamau' }, truck: { id: 7, label: 'KAA 100A' },
    assigned_at: '2026-11-02T09:00:00Z', released_at: null, is_current: true,
    assigned_by: 'Fleet Lead', released_by: null, note: 'Shift swap', source: 'manual',
  },
  {
    id: 1, driver: { id: 1, label: 'Ann Wanjiru' }, truck: { id: 7, label: 'KAA 100A' },
    assigned_at: '2026-10-01T06:00:00Z', released_at: '2026-11-02T09:00:00Z', is_current: false,
    assigned_by: null, released_by: 'Fleet Lead', note: null, source: 'backfill',
  },
]

describe('DriverHistory', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  it('lists assignments newest first with current marker and periods', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, HISTORY))
    render(<DriverHistory truckId={7} version={0} />)
    const list = await screen.findByTestId('driver-history')
    const items = within(list).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Ben Kamau')
    expect(items[0]).toHaveTextContent('Current')
    expect(items[0]).toHaveTextContent('present')
    expect(items[0]).toHaveTextContent('Shift swap')
    expect(items[1]).toHaveTextContent('Ann Wanjiru')
    expect(items[1]).not.toHaveTextContent('Current')
    expect(items[1]).toHaveTextContent('Released by Fleet Lead')
    expect(items[1]).toHaveTextContent('Start date estimated')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/trucks/7/assignments')
  })

  it('shows an empty state', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, []))
    render(<DriverHistory truckId={7} version={0} />)
    expect(await screen.findByText('No driver has been assigned to this truck.')).toBeInTheDocument()
  })
})
