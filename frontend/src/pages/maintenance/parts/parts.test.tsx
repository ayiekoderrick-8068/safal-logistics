import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../../../auth/AuthContext'
import { AppRoutes } from '../../../App'
import { qty, quantityProblem } from '../../../lib/maintenance'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ME = {
  id: 4, email: 'k@example.com', username: 'kim', full_name: 'Kim Keeper', role: 'viewer', status: 'active',
  last_login_at: null, maintenance_role: 'storekeeper', workspaces: ['logistics', 'maintenance'], workspace: 'maintenance',
}
const PART = {
  id: 9, part_number: 'BRG-6205', name: 'Bearing 6205-2RS', description: null, category: 'Bearings', unit: 'each',
  on_hand: 3, reorder_level: 4, reorder_quantity: 10, location: 'Store A / Bin 3', supplier: null, unit_cost: 350,
  is_active: true, stock_state: 'low', stock_value: 1050,
}

function setup() {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/auth/me') return Promise.resolve(json(ME))
    if (url === '/api/maintenance/access') {
      return Promise.resolve(json({ maintenance_role: 'storekeeper', permissions: ['view', 'parts.manage', 'parts.consume'] }))
    }
    if (url.startsWith('/api/maintenance/parts/summary')) {
      return Promise.resolve(json({ active_parts: 1, low_stock: 1, out_of_stock: 0, stock_value: 1050, parts_without_cost: 0 }))
    }
    if (url === '/api/maintenance/parts/9/adjust' && init?.method === 'POST') return Promise.resolve(json({ ...PART, on_hand: 2 }))
    if (url.startsWith('/api/maintenance/parts/9')) {
      return Promise.resolve(json({ ...PART, issued_last_90_days: 6, movements: [
        { id: 1, occurred_at: '2026-11-01T08:00:00Z', kind: 'receipt', quantity: 9, balance_after: 9, work_order: null, reference: 'GRN-1042', note: null, actor: null },
        { id: 2, occurred_at: '2026-11-03T08:00:00Z', kind: 'issue', quantity: -6, balance_after: 3, work_order: { id: 21, number: 'WO-2026-00021', status: 'completed' }, reference: null, note: null, actor: null },
      ] }))
    }
    if (url.startsWith('/api/maintenance/parts')) return Promise.resolve(json({ items: [PART], total: 1, limit: 12, offset: 0 }))
    return Promise.resolve(json({}))
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/maintenance/spare-parts']}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>)
  return fetchMock
}

// The page is lazy-loaded by the router; load it once up front so the first test does not
// pay the module-transform cost inside its own timeout.
beforeAll(async () => {
  await import('./SparePartsPage')
}, 60_000)

describe('spare parts', () => {
  it('validates quantities like the server', () => {
    expect(quantityProblem('2', 'each')).toBeNull()
    expect(quantityProblem('1.5', 'each')).toMatch(/whole number/)
    expect(quantityProblem('1.25', 'litre')).toBeNull()
    expect(quantityProblem('1.2345', 'litre')).toMatch(/3 decimals/)
    expect(quantityProblem('0', 'each')).toMatch(/more than zero/)
    expect(quantityProblem('0', 'each', 'counted quantity', true)).toBeNull()
    expect(qty(18.75, 'litre')).toBe('18.75 litre')
  })

  it('shows the reorder alert and the signed movement ledger', async () => {
    setup()
    expect(await screen.findByText(/1 part needs reordering/, {}, { timeout: 8000 })).toBeInTheDocument()
    const ledger = await screen.findByRole('list', { name: 'Stock movements' }, { timeout: 8000 })
    expect(ledger).toHaveTextContent('+9 each')
    expect(ledger).toHaveTextContent('-6 each')
    expect(ledger).toHaveTextContent('WO-2026-00021')
  })

  it('requires a reason for a stock count and sends one request id per action', async () => {
    const fetchMock = setup()
    await userEvent.click(await screen.findByRole('button', { name: 'Stock count' }, { timeout: 8000 }))
    const dialog = await screen.findByRole('dialog')
    const input = within(dialog).getByLabelText(/Counted quantity/)
    await userEvent.clear(input)
    await userEvent.type(input, '2')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Record count' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Give the reason')
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'Quarterly stock take')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Record count' }))
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/adjust'))!
    const body = JSON.parse(String(call[1]!.body))
    expect(body).toMatchObject({ counted_quantity: '2', reason: 'Quarterly stock take' })
    expect(body.request_id).toMatch(/^[A-Za-z0-9-]{8,}$/)
  })
})
