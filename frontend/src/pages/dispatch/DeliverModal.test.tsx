import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Dispatch } from '../../lib/types'
import { DeliverModal } from './DispatchModals'

const DISPATCH: Dispatch = {
  id: 7, load_ref: 'LD-261105-001', schedule_id: 3, truck: { id: 1, label: 'KCA 204T' }, driver_name: 'James Otieno',
  route: { id: 2, label: 'Nairobi → Nakuru' }, dispatched_at: '2026-11-05T05:00:00Z',
  expected_arrival_at: '2026-11-05T06:15:00Z', actual_arrival_at: null, status: 'in_transit', is_delayed: false,
  is_overdue: false, delay_minutes: 0, delivery_minutes: null, turnaround_minutes: 23, delay_cause: null,
}

describe('DeliverModal', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...DISPATCH, status: 'delivered' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
  })

  function setArrival(value: string) {
    fireEvent.change(screen.getByLabelText('Actual arrival time (EAT)'), { target: { value } })
  }

  it('on-time delivery needs no cause', async () => {
    const onSaved = vi.fn()
    render(<DeliverModal dispatch={DISPATCH} graceMinutes={15} onClose={() => {}} onSaved={onSaved} />)
    setArrival('2026-11-05T09:20') // ETA 09:15 EAT, 5 min after -> within grace
    expect(screen.getByText(/within the 15-min grace/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Delay cause')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delivery' }))
    expect(onSaved).toHaveBeenCalled()
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toEqual({ actual_arrival_at: '2026-11-05T06:20:00.000Z', delay_cause: null, delay_notes: null })
  })

  it('late delivery requires a delay cause before submitting', async () => {
    render(<DeliverModal dispatch={DISPATCH} graceMinutes={15} onClose={() => {}} onSaved={() => {}} />)
    setArrival('2026-11-05T09:55') // 40 min late
    expect(screen.getByText(/40 min late/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delivery' }))
    expect(await screen.findByText('Select why the delivery was late')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()

    await userEvent.selectOptions(screen.getByLabelText('Delay cause'), 'traffic')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delivery' }))
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).delay_cause).toBe('traffic')
  })
})
