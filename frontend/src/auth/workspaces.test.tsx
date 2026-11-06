import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { AuthProvider } from './AuthContext'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMIN = {
  id: 1, email: 'd@example.com', username: 'derrick', full_name: 'Derrick Ayieko', role: 'admin',
  status: 'active', last_login_at: null, maintenance_role: null, workspaces: ['logistics', 'maintenance'],
}
const OPS = { ...ADMIN, id: 2, username: 'ops', role: 'operations', workspaces: ['logistics'] }

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('workspaces', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  it('sends signed-out visitors of the home page to the workspace chooser', async () => {
    fetchMock.mockResolvedValue(json(401, { detail: 'Not authenticated' }))
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'Choose your workspace' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Logistics Operations/ })).toHaveAttribute('href', '/login')
    expect(screen.getByRole('link', { name: /Maintenance Operations/ })).toHaveAttribute('href', '/maintenance/login')
  })

  it('sends signed-out visitors of a maintenance page to the maintenance sign-in', async () => {
    fetchMock.mockResolvedValue(json(401, { detail: 'Not authenticated' }))
    renderAt('/maintenance/equipment')
    expect(await screen.findByText('Sign in to Maintenance Operations with your LogiTrack account.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Reliable equipment. Preventive maintenance. Measurable uptime.',
    )
  })

  it('signs in to the maintenance workspace with username and password', async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: 'Not authenticated' }))
      .mockResolvedValueOnce(json(200, { user: { ...ADMIN, workspace: 'maintenance' }, expires_in_seconds: 3600 }))
    renderAt('/maintenance/login')
    await userEvent.type(await screen.findByLabelText('Username or email'), 'derrick')
    await userEvent.type(screen.getByLabelText('Password'), 'Secret-123!')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Maintenance Dashboard' })).toBeInTheDocument()
    expect(screen.getByTestId('workspace-name')).toHaveTextContent('Maintenance Operations')
    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toBe('/api/auth/login')
    expect(JSON.parse(init.body)).toEqual({ username: 'derrick', password: 'Secret-123!', workspace: 'maintenance' })
  })

  it('never opens the other workspace without the password', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { ...ADMIN, workspace: 'logistics' })) // signed in: logistics
      .mockResolvedValueOnce(json(400, { detail: 'The password is incorrect.' }))
      .mockResolvedValueOnce(json(200, { user: { ...ADMIN, workspace: 'maintenance' }, expires_in_seconds: 3600 }))
    renderAt('/maintenance/work-orders')
    expect(await screen.findByRole('heading', { name: "Confirm it's you" })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Work Orders' })).not.toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Open Maintenance Operations' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The password is incorrect.')
    expect(screen.queryByRole('heading', { name: 'Work Orders' })).not.toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Password'), 'Secret-123!')
    await userEvent.click(screen.getByRole('button', { name: 'Open Maintenance Operations' }))
    expect(await screen.findByRole('heading', { name: 'Work Orders' })).toBeInTheDocument()
    const [url, init] = fetchMock.mock.calls[2]
    expect(url).toBe('/api/auth/switch-workspace')
    expect(JSON.parse(init.body)).toEqual({ workspace: 'maintenance', password: 'Secret-123!' })
  })

  it('tells users without a maintenance role that access is restricted', async () => {
    fetchMock.mockResolvedValue(json(200, { ...OPS, workspace: 'logistics' }))
    renderAt('/maintenance')
    expect(await screen.findByRole('heading', { name: 'Access restricted' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Back to Logistics Operations/ })).toHaveAttribute('href', '/')
  })

  it('keeps a maintenance session out of logistics pages', async () => {
    fetchMock.mockResolvedValue(json(200, { ...ADMIN, workspace: 'maintenance' }))
    renderAt('/fleet')
    expect(await screen.findByRole('heading', { name: "Confirm it's you" })).toBeInTheDocument()
    expect(screen.getByText(/signed in to Maintenance Operations/)).toBeInTheDocument()
  })
})
