import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../../../auth/AuthContext'
import { AppRoutes } from '../../../App'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ME = {
  id: 3, email: 't@example.com', username: 'tess', full_name: 'Tess Tech', role: 'viewer', status: 'active',
  last_login_at: null, maintenance_role: 'technician', workspaces: ['logistics', 'maintenance'], workspace: 'maintenance',
}
const TASK = {
  id: 11, plan_id: 4, equipment: { id: 7, code: 'CMP-002', name: 'Air compressor 2' }, title: 'Monthly compressor service',
  instructions: 'Drain condensate; check belt tension.', due_on: '2026-11-01', status: 'scheduled', state: 'overdue',
  days_until_due: -5, assigned_technician: { id: 3, full_name: 'Tess Tech' }, completed_on: null, completed_by: null,
  completed_on_time: null, work_notes: null, cancel_reason: null,
}
const SUMMARY = {
  overdue: 1, due_today: 0, due_next_7_days: 2, open: 3, active_plans: 2, completed_last_30_days: 4,
  compliance: { window_days: 90, due: 0, completed_on_time: 0, completed_late: 0, not_completed: 0, pct: null },
}

function setup() {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/auth/me') return Promise.resolve(json(ME))
    if (url === '/api/maintenance/access') {
      return Promise.resolve(json({ maintenance_role: 'technician', permissions: ['view', 'work_orders.work'] }))
    }
    if (url.startsWith('/api/maintenance/pm/summary')) return Promise.resolve(json(SUMMARY))
    if (url === '/api/maintenance/tasks/11/complete' && init?.method === 'POST') {
      return Promise.resolve(json({ ...TASK, status: 'completed', state: 'completed', completed_on: '2026-11-06' }))
    }
    if (url.startsWith('/api/maintenance/tasks')) return Promise.resolve(json({ items: [TASK], total: 1, limit: 12, offset: 0 }))
    return Promise.resolve(json({}))
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/maintenance/preventive?view=overdue']}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>)
  return fetchMock
}

// The page is lazy-loaded by the router; load it once up front so the first test does not
// pay the module-transform cost inside its own timeout.
beforeAll(async () => {
  await import('./PreventivePage')
}, 60_000)

describe('preventive maintenance', () => {
  it('shows overdue work, honest compliance and technician actions only', async () => {
    setup()
    // First render also loads the lazy page chunk.
    expect(await screen.findByText('5 days overdue', {}, { timeout: 8000 })).toBeInTheDocument()
    expect(await screen.findByText('No tasks fell due in the last 90 days')).toBeInTheDocument()
    expect(screen.getByTestId('pm-alert-count')).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: 'Complete' })).toBeInTheDocument()
    // Technicians cannot plan, reschedule or cancel.
    expect(screen.queryByRole('button', { name: 'Reschedule' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New plan/ })).not.toBeInTheDocument()
  })

  it('requires the work performed before completing', async () => {
    const fetchMock = setup()
    await userEvent.click(await screen.findByRole('button', { name: 'Complete' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Drain condensate; check belt tension.')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Mark as completed' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Describe the work performed.')
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/complete'))).toBe(false)

    await userEvent.type(within(dialog).getByLabelText('Work performed'), 'Drained, belt re-tensioned')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Mark as completed' }))
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/complete'))!
    expect(JSON.parse(String(call[1]!.body)).work_notes).toBe('Drained, belt re-tensioned')
  })
})
