import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Incident } from '../../lib/types'
import { UpdateIncidentModal } from './IncidentModals'

const INCIDENT: Incident = {
  id: 4, source: 'loading', truck: { id: 1, label: 'KCY 406B' }, operation: 'Loading at Bay 04', load_ref: null,
  schedule_id: 7, dispatch_id: null, cause: 'loading_congestion', status: 'open', started_at: '2026-11-05T05:00:00Z',
  resolved_at: null, duration_minutes: 95, is_ongoing: true, impact_minutes: 28, description: 'Queue at bay 4',
  resolution_notes: null, assigned_to: null, reported_by: 'Mary Otieno', created_at: '2026-11-05T05:05:00Z',
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('UpdateIncidentModal', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn((url: string) =>
      Promise.resolve(url.includes('/users/assignable')
        ? json([{ id: 2, label: 'Peter Karanja', role: 'operations' }])
        : json({ ...INCIDENT, status: 'resolved' })))
    vi.stubGlobal('fetch', fetchMock)
  })

  it('requires resolution notes and a time before resolving, then sends both', async () => {
    const onSaved = vi.fn()
    render(<UpdateIncidentModal incident={INCIDENT} onClose={() => {}} onSaved={onSaved} />)
    expect(await screen.findByText(/Queue at bay 4/)).toBeInTheDocument()
    expect(screen.getByText('1.6 h')).toBeInTheDocument() // 95 min ongoing

    await userEvent.selectOptions(screen.getByLabelText('Status'), 'resolved')
    await userEvent.selectOptions(screen.getByLabelText('Responsible staff member'), '2')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Describe how the delay was resolved')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1) // only the assignee list

    await userEvent.type(screen.getByLabelText('Resolution notes'), 'Extra forklift deployed')
    fireEvent.change(screen.getByLabelText('Resolved at (EAT)'), { target: { value: '2026-11-05T09:15' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(onSaved).toHaveBeenCalled()
    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toBe('/api/incidents/4')
    expect(JSON.parse(init.body)).toMatchObject({
      status: 'resolved', assigned_to_id: 2, resolution_notes: 'Extra forklift deployed', resolved_at: '2026-11-05T06:15:00.000Z',
    })
  })
})
