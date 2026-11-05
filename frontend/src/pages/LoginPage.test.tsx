import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { AppRoutes } from '../App'

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMIN = {
  id: 1, email: 'd@example.com', username: 'derrick', full_name: 'Derrick Ayieko',
  role: 'admin', status: 'active', last_login_at: null,
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('login flow', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  it('redirects anonymous users to the sign-in page', async () => {
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: 'Not authenticated' }))
    renderAt('/fleet')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('validates required fields before calling the API', async () => {
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: 'Not authenticated' }))
    renderAt('/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter your username or email')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
    expect(screen.getByLabelText('Username or email')).toHaveAttribute('aria-invalid', 'true')
    expect(fetchMock).toHaveBeenCalledTimes(1) // only the initial /auth/me session check
  })

  it('shows the server error for bad credentials', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'Not authenticated' }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'Invalid username or password' }))
    renderAt('/login')
    await userEvent.type(await screen.findByLabelText('Username or email'), 'derrick')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password')
  })

  it('returns the user to the page they originally requested', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'Not authenticated' }))
      .mockResolvedValueOnce(jsonResponse(200, { user: ADMIN, expires_in_seconds: 3600 }))
    renderAt('/tasks')
    await userEvent.type(await screen.findByLabelText('Username or email'), 'derrick')
    await userEvent.type(screen.getByLabelText('Password'), 'Secret-123!')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Tasks' })).toBeInTheDocument()
    expect(screen.getByText('This module is under construction')).toBeInTheDocument()

    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toBe('/api/auth/login')
    expect(JSON.parse(init.body)).toEqual({ username: 'derrick', password: 'Secret-123!' })
  })

  it('hides admin-only modules from other roles', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ...ADMIN, role: 'viewer' }))
    renderAt('/users')
    expect(await screen.findByRole('heading', { name: 'Access restricted' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'User Management' })).not.toBeInTheDocument()
  })
})
