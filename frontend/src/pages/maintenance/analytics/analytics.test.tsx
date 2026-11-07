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
const KPIS = {
  window: { start: '2026-10-08', end: '2026-11-06', days: 30 }, equipment: 2,
  availability: { pct: 99.2, observed_hours: 1440, downtime_minutes: 690 },
  mtbf: { hours: 238, failures: 2, operating_hours: 476 },
  mttr: { minutes: null, repairs: 0 },
  time_to_restore: { minutes: 100, restorations: 3 },
  pm_compliance: { due: 0, on_time: 0, late: 0, missed: 0, pct: null },
  work_order_completion: { pct: null, raised: 0, completed: 0 },
  definitions: ['Availability = (observed − downtime) ÷ observed.'],
}
const DASH = {
  window_days: 30,
  kpis: { equipment_total: 5, operational: 3, under_maintenance: 1, out_of_service: 1, open_work_orders: 2,
    overdue_tasks: 3, overdue_pm_tasks: 2, overdue_work_orders: 1, scheduled_pm_next_30_days: 4,
    downtime_minutes: 690, completion_rate_pct: null, completion_sample: 0 },
  schedule: { overdue: 2, due_today: 1, next_7_days: 3 },
  work_orders: { open: 1, assigned: 1, in_progress: 0, awaiting_parts: 0, completed_in_window: 0 },
  metrics: { availability: KPIS.availability, mtbf: KPIS.mtbf, mttr: KPIS.mttr, pm_compliance: KPIS.pm_compliance },
  top_failing: [{ code: 'CNV-001', name: 'Line 1 conveyor', breakdowns: 2, downtime_minutes: 180 }],
  fault_categories: [{ category: 'electrical', breakdowns: 2, downtime_minutes: 180 }],
  downtime_trend: [{ day: '2026-11-05', downtime_minutes: 120 }, { day: '2026-11-06', downtime_minutes: 60 }],
  recent_activity: [{ id: 1, occurred_at: '2026-11-06T08:00:00Z', kind: 'breakdown_logged', summary: 'Breakdown BD-2026-00001 logged',
    equipment: { id: 7, code: 'CNV-001', name: 'Line 1 conveyor' }, actor: 'Derrick Ayieko' }],
  definitions: KPIS.definitions,
}

function setup(path: string, permissions = ['view'], sample_data = false) {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url === '/api/auth/me') return Promise.resolve(json(ME))
    if (url === '/api/maintenance/access') {
      return Promise.resolve(json({ maintenance_role: 'technician', permissions, sample_data }))
    }
    if (url.startsWith('/api/maintenance/dashboard')) return Promise.resolve(json(DASH))
    if (url.startsWith('/api/maintenance/analytics')) return Promise.resolve(json({ kpis: KPIS, equipment: [] }))
    if (url === '/api/maintenance/reports') {
      return Promise.resolve(json([{ key: 'equipment-downtime', title: 'Equipment downtime and availability', description: 'Per asset.' }]))
    }
    if (url.startsWith('/api/maintenance/reports/')) {
      return Promise.resolve(json({ key: 'equipment-downtime', title: 'Equipment downtime and availability', description: '',
        window: KPIS.window, columns: [{ label: 'Equipment', key: 'code' }], rows: [{ code: 'CNV-001' }], total: 1, kpis: KPIS }))
    }
    return Promise.resolve(json({}))
  }))
  render(<MemoryRouter initialEntries={[path]}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>)
}

beforeAll(async () => {
  await import('./MaintenanceDashboardPage')
  await import('./MaintenanceReportsPage')
}, 60_000)

describe('maintenance analytics', () => {
  it('dashboard shows live figures and says when data is insufficient', async () => {
    setup('/maintenance')
    const mttr = await screen.findByRole('article', { name: 'MTTR' }, { timeout: 8000 })
    expect(within(mttr).getByTestId('metric-value')).toHaveTextContent('Insufficient data')
    expect(within(screen.getByRole('article', { name: 'PM compliance' })).getByTestId('metric-value')).toHaveTextContent('Insufficient data')
    expect(within(screen.getByRole('article', { name: 'MTBF' })).getByTestId('metric-value')).toHaveTextContent('238 h')
    expect(screen.getByRole('img', { name: /Operational 3 of 5, Under maintenance 1 of 5, Out of service 1 of 5/ })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Recent activity' })).toHaveTextContent('BD-2026-00001')
  })

  it('labels the demonstration dataset on maintenance pages, and only then', async () => {
    setup('/maintenance', ['view'], true)
    const banner = await screen.findByTestId('sample-data-banner', {}, { timeout: 8000 })
    expect(banner).toHaveTextContent('not live maintenance records')
    expect(banner).toHaveTextContent('clear-maintenance-sample')
  })

  it('shows no sample banner for live data', async () => {
    setup('/maintenance')
    await screen.findByRole('article', { name: 'MTTR' }, { timeout: 8000 })
    expect(screen.queryByTestId('sample-data-banner')).not.toBeInTheDocument()
  })

  it('shows a short MTBF in minutes, never as 0 h', async () => {
    const { hoursOrMinutes } = await import('../../../lib/maintenance')
    expect(hoursOrMinutes(0.02)).toBe('1 min')
    expect(hoursOrMinutes(0.004)).toBe('< 1 min')
    expect(hoursOrMinutes(0.5)).toBe('30 min')
    expect(hoursOrMinutes(3.71)).toBe('3.7 h')
    expect(hoursOrMinutes(1486.94)).toBe('1,486.9 h')
  })

  it('every chart has a table view', async () => {
    setup('/maintenance')
    const group = await screen.findByRole('group', { name: 'Most frequently failing view' }, { timeout: 8000 })
    await userEvent.click(within(group).getByRole('button', { name: /Table/ }))
    const table = screen.getByRole('table', { name: 'Most frequently failing' })
    expect(table).toHaveTextContent('CNV-001')
    expect(table).toHaveTextContent('3.0 h')
  })

  it('reports hide export for roles without permission and show it for those with it', async () => {
    setup('/maintenance/reports')
    expect(await screen.findByText('Your role can view but not export reports.', {}, { timeout: 8000 })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /CSV/ })).not.toBeInTheDocument()
  })

  it('export links carry the selected window', async () => {
    setup('/maintenance/reports', ['view', 'reports.export'])
    const pdf = await screen.findByRole('link', { name: /PDF/ }, { timeout: 8000 })
    expect(pdf.getAttribute('href')).toMatch(/\/api\/maintenance\/reports\/equipment-downtime\?start=\d{4}-\d{2}-\d{2}&end=\d{4}-\d{2}-\d{2}&format=pdf/)
  })
})
