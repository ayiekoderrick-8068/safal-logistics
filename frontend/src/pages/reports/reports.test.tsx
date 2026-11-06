import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fromSearchParams, toQuery, validate, EMPTY_FILTERS } from './filters'
import { ReportsPage } from './ReportsPage'

const SUMMARY = {
  filters: {}, applied: [{ label: 'Period', value: '30 Oct 2026 – 5 Nov 2026 (7 days, Africa/Nairobi)' }], timezone: 'Africa/Nairobi',
  kpis: { loads_processed: 51, completed_dispatches: 50, pending_deliveries: 1, on_time_pct: 74, avg_turnaround_minutes: 131.3,
    delayed_loads: 35, bay_utilization_pct: 45.2, compliance_interruptions: 2, delay_incidents: 16 },
  dispatch_outcomes: [{ status: 'on_time', count: 37 }, { status: 'late', count: 13 }],
  trend: [{ day: '2026-11-05', loads: 3, avg_turnaround_minutes: 120, on_time_pct: 50, delays: 1 }],
  target_minutes: 120,
}
const CATALOGUE = [
  { key: 'executive', title: 'Executive Operations Summary', formats: ['pdf'] },
  { key: 'turnaround', title: 'Truck Turnaround Performance', formats: ['pdf', 'csv'] },
]
const TURNAROUND = {
  ...SUMMARY, target_minutes: 120, completed_loads: 0, ongoing_loads: 0, within_target_pct: null,
  components: Object.fromEntries(['waiting', 'loading', 'post_load', 'turnaround', 'delivery'].map((k) =>
    [k, { count: 0, avg: null, median: null, min: null, max: null }])),
  daily: [], weekly: [], by_truck: [], by_route: [], by_bay: [],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function routeFetch(overrides: Record<string, () => Response> = {}) {
  return vi.fn((url: string) => {
    for (const [prefix, make] of Object.entries(overrides)) if (url.startsWith(prefix)) return Promise.resolve(make())
    if (url.startsWith('/api/reports/summary')) return Promise.resolve(json(SUMMARY))
    if (url.startsWith('/api/reports/catalogue')) return Promise.resolve(json(CATALOGUE))
    if (url.startsWith('/api/reports/history')) return Promise.resolve(json([]))
    if (url.startsWith('/api/reports/turnaround')) return Promise.resolve(json(TURNAROUND))
    if (url.startsWith('/api/trucks')) return Promise.resolve(json({ items: [{ id: 7, registration: 'KDG 752R' }], total: 1, limit: 100, offset: 0 }))
    return Promise.resolve(json([]))
  })
}

function renderPage(path = '/reports') {
  return render(<MemoryRouter initialEntries={[path]}><ReportsPage /></MemoryRouter>)
}

describe('report filter helpers', () => {
  it('builds API queries from applied filters only', () => {
    expect(toQuery(EMPTY_FILTERS)).toBe('period=last_7_days')
    expect(toQuery({ ...EMPTY_FILTERS, period: 'custom', start: '2026-11-01', end: '2026-11-03', truck_id: '7', delay_cause: 'traffic' }))
      .toBe('period=custom&start=2026-11-01&end=2026-11-03&truck_id=7&delay_cause=traffic')
    expect(toQuery({ ...EMPTY_FILTERS, period: 'today', start: '2026-11-01' })).toBe('period=today') // dates ignored
  })
  it('validates custom ranges', () => {
    expect(validate({ ...EMPTY_FILTERS, period: 'custom' })).toMatch(/both a start and an end/)
    expect(validate({ ...EMPTY_FILTERS, period: 'custom', start: '2026-11-05', end: '2026-11-01' })).toMatch(/on or before/)
    expect(validate({ ...EMPTY_FILTERS, period: 'custom', start: '2024-01-01', end: '2026-01-01' })).toMatch(/366/)
    expect(validate({ ...EMPTY_FILTERS, period: 'custom', start: '2026-11-01', end: '2026-11-01' })).toBeNull()
  })
  it('reads filters back from the URL and rejects unknown periods', () => {
    expect(fromSearchParams(new URLSearchParams('period=bogus&bay_id=3'))).toMatchObject({ period: 'last_7_days', bay_id: '3' })
  })
})

describe('ReportsPage', () => {
  let fetchMock: ReturnType<typeof routeFetch>
  beforeEach(() => {
    fetchMock = routeFetch()
    vi.stubGlobal('fetch', fetchMock)
  })

  it('renders KPIs from the API and exports that carry the filters', async () => {
    renderPage('/reports?period=last_30_days&truck_id=7')
    const loads = await screen.findByRole('article', { name: 'Loads Processed' })
    expect(within(loads).getByTestId('stat-value')).toHaveTextContent('51')
    expect(within(screen.getByRole('article', { name: 'On-Time Delivery' })).getByTestId('stat-value')).toHaveTextContent('74.0%')
    expect(within(screen.getByRole('article', { name: 'Avg Turnaround' })).getByTestId('stat-value')).toHaveTextContent('2.2 h')
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/reports/summary?period=last_30_days&truck_id=7')).toBe(true)
    const pdf = await screen.findByRole('link', { name: 'Executive summary PDF' })
    expect(pdf).toHaveAttribute('href', '/api/reports/export/executive.pdf?period=last_30_days&truck_id=7')
  })

  it('validates and applies combined filters', async () => {
    renderPage()
    await screen.findByRole('article', { name: 'Loads Processed' })
    await userEvent.selectOptions(screen.getByLabelText('Period'), 'custom')
    await userEvent.click(screen.getByRole('button', { name: 'Apply Filters' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose both a start and an end date')

    await userEvent.selectOptions(screen.getByLabelText('Period'), 'yesterday')
    await waitFor(() => expect(screen.getByLabelText('Truck')).toHaveTextContent('KDG 752R'))
    await userEvent.selectOptions(screen.getByLabelText('Truck'), '7')
    await userEvent.selectOptions(screen.getByLabelText('Delay category'), 'traffic')
    await userEvent.click(screen.getByRole('button', { name: 'Apply Filters' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) =>
      u === '/api/reports/summary?period=yesterday&truck_id=7&delay_cause=traffic')).toBe(true))
  })

  it('switching tabs loads that analysis (chart data follows the filters)', async () => {
    renderPage('/reports?period=today')
    await screen.findByRole('article', { name: 'Loads Processed' })
    await userEvent.click(screen.getByRole('tab', { name: 'Turnaround' }))
    expect(await screen.findByText('Turnaround Components')).toBeInTheDocument()
    expect(screen.getByText('No completed loads in this period')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/reports/turnaround?period=today')).toBe(true)
  })

  it('shows loading then a retryable error', async () => {
    vi.stubGlobal('fetch', routeFetch({ '/api/reports/summary': () => json({ detail: 'boom' }, 500) }))
    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent('Building report')
    expect(await screen.findByText('Could not load data')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('compliance-only roles see just their permitted exports', async () => {
    vi.stubGlobal('fetch', routeFetch({
      '/api/reports/summary': () => json({ detail: 'Your role does not have access to this report' }, 403),
      '/api/reports/catalogue': () => json([{ key: 'compliance', title: 'Compliance Summary', formats: ['pdf', 'csv', 'xlsx'] }]),
    }))
    renderPage()
    expect(await screen.findByText('Reports available to your role')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute('href', '/api/reports/export/compliance.pdf?period=last_7_days')
    expect(screen.getByRole('link', { name: 'Excel' })).toHaveAttribute('href', '/api/reports/export/compliance.xlsx?period=last_7_days')
    expect(screen.getByRole('link', { name: 'CSV' })).toHaveAttribute('href', '/api/reports/export/compliance.csv?period=last_7_days')
    expect(screen.queryByRole('button', { name: 'Apply Filters' })).not.toBeInTheDocument()
  })

  it('offers Excel next to CSV on the records tab only when the catalogue allows it', async () => {
    vi.stubGlobal('fetch', routeFetch({
      '/api/reports/catalogue': () => json([{ key: 'turnaround', title: 'Truck Turnaround Performance', formats: ['pdf', 'csv', 'xlsx'] }]),
      '/api/reports/records': () => json({ type: 'turnaround', total: 0, limit: 20, offset: 0, items: [] }),
    }))
    renderPage('/reports?period=today&truck_id=7')
    await screen.findByRole('article', { name: 'Loads Processed' })
    await userEvent.click(screen.getByRole('tab', { name: 'Records & Export' }))
    expect(await screen.findByRole('link', { name: 'Export Excel' }))
      .toHaveAttribute('href', '/api/reports/export/turnaround.xlsx?period=today&truck_id=7')
    expect(screen.getByRole('link', { name: 'Export CSV' }))
      .toHaveAttribute('href', '/api/reports/export/turnaround.csv?period=today&truck_id=7')
  })
})
