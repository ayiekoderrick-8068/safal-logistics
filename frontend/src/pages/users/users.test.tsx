import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../../auth/AuthContext'
import { AppRoutes } from '../../App'
import { generatePassword } from '../../lib/passwords'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMIN = {
  id: 1, email: 'boss@example.com', username: 'boss', full_name: 'Boss Admin', role: 'admin',
  status: 'active', last_login_at: null, must_change_password: false,
  created_at: '2026-11-01T08:00:00Z', password_changed_at: null,
}
const OPS = { ...ADMIN, id: 2, email: 'grace@example.com', username: 'grace', full_name: 'Grace Wanjiru', role: 'operations' }

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>)
}

type Handler = (url: string, init?: RequestInit) => Response | undefined

function routeFetch(me: object, extra: Handler = () => undefined) {
  return vi.fn((url: string, init?: RequestInit) => {
    const hit = extra(url, init)
    if (hit) return Promise.resolve(hit)
    if (url === '/api/auth/me') return Promise.resolve(json(me))
    if (url.startsWith('/api/users')) return Promise.resolve(json([ADMIN, OPS]))
    if (url.startsWith('/api/alerts/summary')) return Promise.resolve(json({ open: 0, critical: 0, warning: 0, info: 0, items: [] }))
    return Promise.resolve(json({}))
  })
}

describe('generatePassword', () => {
  it('always satisfies the password policy', () => {
    for (let i = 0; i < 50; i++) {
      const p = generatePassword()
      expect(p.length).toBeGreaterThanOrEqual(8)
      expect(p).toMatch(/[A-Za-z]/)
      expect(p).toMatch(/\d/)
      expect(p).toMatch(/[^A-Za-z0-9]/)
    }
  })
})

describe('User Management', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('lists users with roles and does not offer self-deactivation', async () => {
    vi.stubGlobal('fetch', routeFetch(ADMIN))
    renderAt('/users')
    // The page is lazy-loaded; the first render in a test file includes that import.
    expect(await screen.findByRole('heading', { level: 1, name: 'User Management' }, { timeout: 10_000 }))
      .toBeInTheDocument()
    const grace = (await screen.findByText('Grace Wanjiru')).closest('tr')!
    expect(within(grace).getByText('Operations')).toBeInTheDocument()
    expect(within(grace).getByRole('button', { name: 'Deactivate Grace Wanjiru' })).toBeInTheDocument()
    const me = screen.getByText('Boss Admin').closest('tr')!
    expect(within(me).queryByRole('button', { name: /Deactivate/ })).not.toBeInTheDocument()
  })

  it('validates and creates a user with a generated temporary password', async () => {
    const fetchMock = routeFetch(ADMIN, (url, init) =>
      url === '/api/users' && init?.method === 'POST' ? json({ ...OPS, id: 3, ...JSON.parse(String(init.body)) }, 201) : undefined)
    vi.stubGlobal('fetch', fetchMock)
    renderAt('/users')
    await userEvent.click(await screen.findByRole('button', { name: 'Add User' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create user' }))
    expect(await within(dialog).findByText('Enter the person’s full name')).toBeInTheDocument()

    await userEvent.type(within(dialog).getByLabelText('Full name'), 'Peter Mwangi')
    await userEvent.type(within(dialog).getByLabelText('Username'), 'Peter.M')
    await userEvent.type(within(dialog).getByLabelText('Email'), 'peter@example.com')
    await userEvent.selectOptions(within(dialog).getByLabelText('Role'), 'fleet_manager')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Generate a temporary password' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const [, init] = fetchMock.mock.calls.find(([u, i]) => u === '/api/users' && i?.method === 'POST')!
    const sent = JSON.parse(String(init!.body))
    expect(sent).toMatchObject({ full_name: 'Peter Mwangi', username: 'peter.m', email: 'peter@example.com', role: 'fleet_manager' })
    expect(sent.temporary_password).toMatch(/[^A-Za-z0-9]/)
  })

  it('shows server errors such as a duplicate username', async () => {
    vi.stubGlobal('fetch', routeFetch(ADMIN, (url, init) =>
      url === '/api/users' && init?.method === 'POST' ? json({ detail: 'That username or email is already in use.' }, 409) : undefined))
    renderAt('/users')
    await userEvent.click(await screen.findByRole('button', { name: 'Add User' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Full name'), 'Grace Again')
    await userEvent.type(within(dialog).getByLabelText('Username'), 'grace')
    await userEvent.type(within(dialog).getByLabelText('Email'), 'grace@example.com')
    await userEvent.type(within(dialog).getByLabelText('Temporary password'), 'Temp-Pass-123!')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create user' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('already in use')
  })
})

describe('temporary password', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('forces a password change before continuing and cannot be dismissed', async () => {
    const fetchMock = routeFetch({ ...OPS, must_change_password: true }, (url) =>
      url === '/api/auth/change-password' ? json({ ...OPS, must_change_password: false }) : undefined)
    vi.stubGlobal('fetch', fetchMock)
    renderAt('/page-without-data') // any signed-in page; this one makes no data requests
    const dialog = await screen.findByRole('dialog', { name: 'Set a new password' })
    await userEvent.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: 'Set a new password' })).toBeInTheDocument()

    await userEvent.type(within(dialog).getByLabelText('Temporary password'), 'Temp-Pass-123!')
    await userEvent.type(within(dialog).getByLabelText('New password'), 'short')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save password' }))
    expect(await within(dialog).findByText('Use at least 8 characters')).toBeInTheDocument()

    await userEvent.clear(within(dialog).getByLabelText('New password'))
    await userEvent.type(within(dialog).getByLabelText('New password'), 'My-Own-Pass-9!')
    await userEvent.type(within(dialog).getByLabelText('Confirm new password'), 'My-Own-Pass-9!')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save password' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const [, init] = fetchMock.mock.calls.find(([u]) => u === '/api/auth/change-password')!
    expect(JSON.parse(String(init!.body))).toEqual({ current_password: 'Temp-Pass-123!', new_password: 'My-Own-Pass-9!' })
  })
})
