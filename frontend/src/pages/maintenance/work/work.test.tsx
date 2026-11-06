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
const WO = {
  id: 21, number: 'WO-2026-00021', equipment: { id: 7, code: 'CNV-001', name: 'Line 1 conveyor' },
  maintenance_type: 'corrective', priority: 'critical', status: 'in_progress', fault_description: 'Motor tripped',
  assigned_technician: { id: 3, full_name: 'Tess Tech' }, scheduled_on: null, overdue: false,
  created_at: '2026-11-06T06:00:00Z', created_by: { id: 1, full_name: 'Derrick Ayieko' },
  started_at: '2026-11-06T07:00:00Z', completed_at: null, repair_minutes: null, work_performed: null,
  completion_notes: null, cancel_reason: null,
  breakdown: { id: 5, number: 'BD-2026-00005', is_open: true, started_at: '2026-11-06T05:30:00Z', restored_at: null },
  allowed_transitions: ['awaiting_parts', 'completed', 'cancelled'],
  history: [{ id: 1, occurred_at: '2026-11-06T06:00:00Z', from_status: null, to_status: 'open', summary: 'Work order raised', note: null, actor: null }],
}

function setup() {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/auth/me') return Promise.resolve(json(ME))
    if (url === '/api/maintenance/access') {
      return Promise.resolve(json({ maintenance_role: 'technician', permissions: ['view', 'work_orders.create', 'work_orders.work', 'breakdowns.log'] }))
    }
    if (url.startsWith('/api/maintenance/work-orders/summary')) {
      return Promise.resolve(json({ open: 0, assigned: 0, in_progress: 1, awaiting_parts: 0, completed_last_30_days: 0, overdue: 0, critical_open: 1 }))
    }
    if (url === '/api/maintenance/work-orders/21/complete' && init?.method === 'POST') {
      return Promise.resolve(json({ ...WO, status: 'completed', allowed_transitions: [] }))
    }
    if (url.startsWith('/api/maintenance/work-orders/21/parts')) {
      return Promise.resolve(json({ work_order: { id: 21, number: WO.number, status: WO.status }, lines: [], movements: [], total_cost: 0, can_issue: true }))
    }
    if (url.startsWith('/api/maintenance/work-orders/21')) return Promise.resolve(json(WO))
    if (url.startsWith('/api/maintenance/work-orders')) return Promise.resolve(json({ items: [WO], total: 1, limit: 10, offset: 0 }))
    return Promise.resolve(json({}))
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/maintenance/work-orders']}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>)
  return fetchMock
}

// The page is lazy-loaded by the router; load it once up front so the first test does not
// pay the module-transform cost inside its own timeout.
beforeAll(async () => {
  await import('./WorkOrdersPage')
}, 60_000)

describe('work orders', () => {
  it('lets the assigned technician progress work but not cancel or reassign it', async () => {
    setup()
    // Look inside the detail panel: the filter chips have similar names ("Awaiting parts", "Completed").
    const history = await screen.findByRole('list', { name: 'Status history' }, { timeout: 8000 })
    const panel = within(history.closest('section')!)
    expect(panel.getByRole('button', { name: 'Complete' })).toBeInTheDocument()
    expect(panel.getByRole('button', { name: 'Awaiting parts' })).toBeInTheDocument()
    expect(panel.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
    expect(panel.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(panel.queryByRole('button', { name: 'Assign' })).not.toBeInTheDocument()
    expect(screen.getByText('Equipment down')).toBeInTheDocument()
  })

  it('validates completion and can restore the linked breakdown', async () => {
    const fetchMock = setup()
    await userEvent.click(await screen.findByRole('button', { name: 'Complete' }, { timeout: 8000 }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Work performed/), 'Reset')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Complete work order' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('at least 10 characters')
    await userEvent.type(within(dialog).getByLabelText(/Work performed/), ' breaker; replaced the contactor')
    expect(within(dialog).getByRole('checkbox', { name: /Equipment is back in service/ })).toBeChecked()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Complete work order' }))
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/complete'))!
    const body = JSON.parse(String(call[1]!.body))
    expect(body.restore_breakdown).toBe(true)
    expect(body.work_performed).toBe('Reset breaker; replaced the contactor')
  })
})
