import clsx from 'clsx'
import { KeyRound, Pencil, Search, ShieldCheck, UserCheck, UserPlus, UserX, Users } from 'lucide-react'
import { useState } from 'react'
import { useAuth } from '../../auth/context'
import { ConfirmModal } from '../../components/ui/ConfirmModal'
import { btnPrimary, btnSmall, btnSmallGhost } from '../../components/ui/buttons'
import { Card, CardHeader } from '../../components/ui/Card'
import { FilterSelect } from '../../components/ui/FilterSelect'
import { PageHeader } from '../../components/ui/PageHeader'
import { StatCard } from '../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useToast } from '../../components/ui/toastContext'
import { useApi } from '../../hooks/useApi'
import { useDebounced } from '../../hooks/useDebounced'
import { api } from '../../lib/api'
import { formatDateTime, formatNumber, MAINTENANCE_ROLE_LABELS, ROLE_LABELS } from '../../lib/format'
import type { AdminUser } from '../../lib/types'
import { ResetPasswordModal, UserFormModal } from './UserModals'

const ROLE_OPTIONS = [
  { value: '', label: 'Role: All' },
  ...Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label })),
]
const STATUS_OPTIONS = [
  { value: '', label: 'Status: All' },
  { value: 'active', label: 'Active' },
  { value: 'deactivated', label: 'Deactivated' },
]

type Dialog =
  | { kind: 'create' }
  | { kind: 'edit'; user: AdminUser }
  | { kind: 'reset'; user: AdminUser }
  | { kind: 'status'; user: AdminUser }
  | null

export function UsersPage() {
  const { user: me } = useAuth()
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [dialog, setDialog] = useState<Dialog>(null)
  const [version, setVersion] = useState(0)
  const q = useDebounced(query.trim())

  const params = new URLSearchParams({ v: String(version) })
  if (q) params.set('q', q)
  if (role) params.set('role', role)
  if (status) params.set('status', status)
  const list = useApi<AdminUser[]>(`/users?${params}`)
  const all = useApi<AdminUser[]>(`/users?v=${version}`) // unfiltered, for the KPI cards
  const reload = () => setVersion((v) => v + 1)

  const users = all.data ?? []
  const count = (pred: (u: AdminUser) => boolean) => (all.data ? users.filter(pred).length : undefined)

  return (
    <>
      <PageHeader
        title="User Management"
        description="Create accounts, assign roles and control access to LogiTrack."
        actions={
          <button type="button" className={btnPrimary} onClick={() => setDialog({ kind: 'create' })}>
            <UserPlus className="size-4" aria-hidden /> Add User
          </button>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={Users} tone="blue" label="Total Users" value={formatNumber(count(() => true))} note="All accounts" />
        <StatCard icon={UserCheck} tone="green" label="Active" value={formatNumber(count((u) => u.status === 'active'))}
          note="Can sign in" />
        <StatCard icon={ShieldCheck} tone="teal" label="Administrators"
          value={formatNumber(count((u) => u.role === 'admin' && u.status === 'active'))} note="Active admins" />
        <StatCard icon={UserX} tone="red" label="Deactivated" value={formatNumber(count((u) => u.status === 'deactivated'))}
          note="Access revoked" />
      </div>

      <div className="mt-4 flex flex-col gap-3 md:flex-row">
        <label className="relative flex-1">
          <span className="sr-only">Search users</span>
          <Search className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-ink-muted" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, username or email…"
            className="h-11 w-full rounded-xl border border-white bg-white pr-4 pl-12 text-ink shadow-sm placeholder:text-ink-muted"
          />
        </label>
        <FilterSelect label="Filter by role" value={role} options={ROLE_OPTIONS} onChange={setRole} />
        <FilterSelect label="Filter by status" value={status} options={STATUS_OPTIONS} onChange={setStatus} />
      </div>

      <Card className="mt-4">
        <CardHeader title="Users" subtitle="Role and status changes sign the user out immediately." />
        {list.error && !list.data ? (
          <ErrorState message={list.error.message} onRetry={list.refetch} />
        ) : !list.data ? (
          <LoadingState />
        ) : list.data.length === 0 ? (
          <EmptyState title={q || role || status ? 'No users match your filters' : 'No users yet'} />
        ) : (
          <div className="-mx-2 overflow-x-auto">
            <table className="w-full min-w-[940px] text-left text-sm whitespace-nowrap">
              <thead>
                <tr className="bg-surface-muted text-ink">
                  {['Name', 'Username', 'Role', 'Maintenance', 'Status', 'Last sign-in', 'Actions'].map((h) => (
                    <th key={h} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {list.data.map((u) => {
                  const self = u.id === me?.id
                  return (
                    <tr key={u.id} className="border-b border-line last:border-0">
                      <td className="px-3 py-2.5">
                        <p className="font-semibold text-ink">{u.full_name}{self && <span className="ml-1.5 text-xs font-normal text-ink-muted">(you)</span>}</p>
                        <p className="text-xs text-ink-muted">{u.email}</p>
                      </td>
                      <td className="px-3 py-2.5">{u.username}</td>
                      <td className="px-3 py-2.5">{ROLE_LABELS[u.role]}</td>
                      <td className="px-3 py-2.5">
                        {u.role === 'admin'
                          ? MAINTENANCE_ROLE_LABELS.manager
                          : u.maintenance_role
                            ? MAINTENANCE_ROLE_LABELS[u.maintenance_role]
                            : <span className="text-ink-muted">No access</span>}
                      </td>
                      <td className="px-3 py-2.5">
                        <StatusBadge status={u.status} />
                        {u.must_change_password && (
                          <span className="mt-0.5 block text-xs font-semibold text-amber-700">Temporary password</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">{u.last_login_at ? formatDateTime(u.last_login_at) : <span className="text-ink-muted">Never</span>}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex gap-1.5">
                          <button type="button" className={btnSmallGhost} aria-label={`Edit ${u.full_name}`}
                            onClick={() => setDialog({ kind: 'edit', user: u })}>
                            <Pencil className="size-3.5" aria-hidden /> Edit
                          </button>
                          <button type="button" className={btnSmallGhost} aria-label={`Reset password for ${u.full_name}`}
                            onClick={() => setDialog({ kind: 'reset', user: u })}>
                            <KeyRound className="size-3.5" aria-hidden /> Reset password
                          </button>
                          {!self && (
                            <button type="button"
                              className={clsx(btnSmall, 'border border-line bg-white hover:bg-surface-muted',
                                u.status === 'active' ? 'text-red-700' : 'text-emerald-700')}
                              aria-label={`${u.status === 'active' ? 'Deactivate' : 'Activate'} ${u.full_name}`}
                              onClick={() => setDialog({ kind: 'status', user: u })}>
                              {u.status === 'active'
                                ? <><UserX className="size-3.5" aria-hidden /> Deactivate</>
                                : <><UserCheck className="size-3.5" aria-hidden /> Activate</>}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {(dialog?.kind === 'create' || dialog?.kind === 'edit') && (
        <UserFormModal
          user={dialog.kind === 'edit' ? dialog.user : undefined}
          isSelf={dialog.kind === 'edit' && dialog.user.id === me?.id}
          onClose={() => setDialog(null)}
          onSaved={(u, created) => {
            setDialog(null)
            reload()
            toast.success(created ? `${u.full_name} added. Share the temporary password securely.` : `${u.full_name} updated`)
          }}
        />
      )}
      {dialog?.kind === 'reset' && (
        <ResetPasswordModal
          user={dialog.user}
          onClose={() => setDialog(null)}
          onSaved={(u) => {
            setDialog(null)
            reload()
            toast.success(`Temporary password set for ${u.full_name}. They have been signed out.`)
          }}
        />
      )}
      {dialog?.kind === 'status' && (
        <ConfirmModal
          title={dialog.user.status === 'active' ? 'Deactivate user' : 'Activate user'}
          message={
            dialog.user.status === 'active'
              ? `${dialog.user.full_name} will be signed out immediately and will not be able to sign in. Their history is kept.`
              : `${dialog.user.full_name} will be able to sign in again with their existing password.`
          }
          confirmLabel={dialog.user.status === 'active' ? 'Deactivate' : 'Activate'}
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const next = dialog.user.status === 'active' ? 'deactivated' : 'active'
            const u = await api<AdminUser>(`/users/${dialog.user.id}`, {
              method: 'PATCH',
              body: JSON.stringify({ status: next }),
            })
            setDialog(null)
            reload()
            toast.success(`${u.full_name} ${next === 'active' ? 'activated' : 'deactivated'}`)
          }}
        />
      )}
    </>
  )
}
