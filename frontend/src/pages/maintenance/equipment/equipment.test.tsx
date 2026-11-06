import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../../../auth/AuthContext'
import { AppRoutes } from '../../../App'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ME = {
  id: 1, email: 'd@example.com', username: 'derrick', full_name: 'Derrick Ayieko', role: 'admin', status: 'active',
  last_login_at: null, maintenance_role: null, workspaces: ['logistics', 'maintenance'], workspace: 'maintenance',
}
const EQ = {
  id: 7, code: 'CMP-002', name: 'Air compressor 2', category: 'compressor', manufacturer: 'Atlas Copco', model: 'GA30',
  serial_number: 'AC-30-221', facility: 'Nairobi Plant', department: 'Utilities', location: 'Compressor house',
  installed_on: '2024-02-01', status: 'operational', assigned_technician: { id: 3, full_name: 'Tess Tech' },
  last_service_on: '2026-08-01', next_service_on: '2026-11-01', notes: null, archived_at: null,
  created_at: '2026-11-01T08:00:00Z', updated_at: '2026-11-01T08:00:00Z', service_state: 'overdue', days_until_service: -5,
}
const SUMMARY = {
  total: 1, operational: 1, under_maintenance: 0, out_of_service: 0, service_overdue: 1, service_due_soon: 0,
  archived: 0, due_soon_days: 14,
}

function setup(permissions: string[]) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/auth/me') return Promise.resolve(json(ME))
    if (url === '/api/maintenance/access') return Promise.resolve(json({ maintenance_role: 'manager', permissions }))
    if (url.startsWith('/api/maintenance/equipment/summary')) return Promise.resolve(json(SUMMARY))
    if (url.startsWith('/api/maintenance/equipment/options')) {
      return Promise.resolve(json({ facilities: ['Nairobi Plant'], departments: [], locations: [], technicians: [] }))
    }
    if (url.startsWith('/api/maintenance/equipment/7')) {
      return Promise.resolve(json({ ...EQ, history: [
        { id: 1, occurred_at: '2026-11-01T08:00:00Z', kind: 'created', summary: 'CMP-002 registered (operational)', changes: null, actor: { id: 1, full_name: 'Derrick Ayieko' } },
      ] }))
    }
    if (url.startsWith('/api/maintenance/equipment') && init?.method === 'POST') {
      return Promise.resolve(json({ detail: 'That Equipment ID is already registered.' }, 409))
    }
    if (url.startsWith('/api/maintenance/equipment')) return Promise.resolve(json({ items: [EQ], total: 1, limit: 10, offset: 0 }))
    return Promise.resolve(json({}))
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/maintenance/equipment']}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>)
  return fetchMock
}

describe('equipment register', () => {
  it('lists equipment with live counts, service state and history', async () => {
    setup(['view'])
    // First render also loads the lazy page chunk (slow under a full parallel test run).
    expect(await screen.findByRole('heading', { name: 'Equipment Register' }, { timeout: 8000 })).toBeInTheDocument()
    const slow = { timeout: 8000 } // several requests resolve after the page chunk loads
    const overdue = await screen.findByRole('article', { name: 'Service Overdue' }, slow)
    expect(within(overdue).getByTestId('stat-value')).toHaveTextContent('1')
    expect((await screen.findAllByText('5 days overdue', {}, slow)).length).toBeGreaterThan(0)
    expect(await screen.findByRole('list', { name: 'Maintenance history' }, slow)).toHaveTextContent('CMP-002 registered')
    // Read-only role: no management actions offered.
    expect(screen.queryByRole('button', { name: /Add Equipment/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('validates the form and shows server errors', async () => {
    setup(['view', 'equipment.manage'])
    await userEvent.click(await screen.findByRole('button', { name: /Add Equipment/ }, { timeout: 8000 }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Register equipment' }))
    expect(await within(dialog).findByText(/2–30 characters/)).toBeInTheDocument()
    expect(within(dialog).getByText('Enter the facility')).toBeInTheDocument()

    await userEvent.type(within(dialog).getByLabelText('Equipment ID'), 'cmp-002')
    await userEvent.type(within(dialog).getByLabelText('Equipment name'), 'Air compressor 2')
    await userEvent.type(within(dialog).getByLabelText('Facility'), 'Nairobi Plant')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Register equipment' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('That Equipment ID is already registered.')
  })
})
