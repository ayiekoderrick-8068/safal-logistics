import { BellRing, CircleAlert, ExternalLink, Info, RefreshCw, TriangleAlert } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useAuth } from '../../auth/context'
import { btnSecondary, btnSmallGhost, btnSmallPrimary, inputClass } from '../../components/ui/buttons'
import { Card, CardHeader } from '../../components/ui/Card'
import { FilterSelect } from '../../components/ui/FilterSelect'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { Modal } from '../../components/ui/Modal'
import { PageHeader } from '../../components/ui/PageHeader'
import { Pagination } from '../../components/ui/Pagination'
import { StatCard } from '../../components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useToast } from '../../components/ui/toastContext'
import { useApi } from '../../hooks/useApi'
import { api, ApiError } from '../../lib/api'
import { formatDateTime, formatNumber, humanize } from '../../lib/format'
import type { AlertSummary, OpsAlert, Page } from '../../lib/types'

const PAGE_SIZE = 15
const TYPES = ['document_missing', 'document_expired', 'document_expiring', 'inspection_due', 'maintenance_required',
  'loading_over_target', 'missed_dispatch', 'delivery_overdue', 'incident_unresolved']

function ResolveModal({ alert, onClose, onSaved }: { alert: OpsAlert; onClose: () => void; onSaved: () => void }) {
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string>()
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (note.trim().length < 3) return setFieldError('Explain how this was resolved')
    setFieldError(undefined)
    setBusy(true)
    try {
      await api(`/alerts/${alert.id}/resolve`, { method: 'POST', body: JSON.stringify({ note }) })
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resolve the alert.')
      setBusy(false)
    }
  }
  return (
    <Modal title="Resolve alert" description={alert.title} onClose={onClose}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={error} />
        <p className="text-sm text-ink-muted">
          If the underlying condition still exists, this alert will not be raised again for 24 hours. Alerts whose
          condition clears are resolved automatically.
        </p>
        <Field id="resolve-note" label="Resolution note" error={fieldError}>
          <textarea id="resolve-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={500}
            aria-invalid={fieldError ? true : undefined} aria-describedby={fieldError ? 'resolve-note-error' : undefined}
            className={`${inputClass} h-auto py-2`} />
        </Field>
        <FormActions submitLabel="Resolve" submitting={busy} onCancel={onClose} />
      </form>
    </Modal>
  )
}

export function AlertsPage() {
  const { hasRole } = useAuth()
  const canAct = hasRole('operations', 'fleet_manager', 'compliance')
  const toast = useToast()
  const [status, setStatus] = useState('active')
  const [severity, setSeverity] = useState('')
  const [type, setType] = useState('')
  const [offset, setOffset] = useState(0)
  const [version, setVersion] = useState(0)
  const [resolving, setResolving] = useState<OpsAlert | null>(null)
  const summary = useApi<AlertSummary>(`/alerts/summary?v=${version}`)
  const qs = new URLSearchParams({ status, limit: String(PAGE_SIZE), offset: String(offset), v: String(version) })
  if (severity) qs.set('severity', severity)
  if (type) qs.set('types', type)
  const list = useApi<Page<OpsAlert>>(`/alerts?${qs}`)
  const reload = () => setVersion((v) => v + 1)
  const s = summary.data

  const [actionError, setActionError] = useState<string | null>(null)
  async function acknowledge(a: OpsAlert) {
    setActionError(null)
    try {
      await api(`/alerts/${a.id}/acknowledge`, { method: 'POST' })
      toast.success('Alert acknowledged')
      reload()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not acknowledge the alert.')
    }
  }

  return (
    <>
      <PageHeader
        title="Operational Alerts"
        description="Compliance, maintenance, loading, dispatch and delay alerts. Alerts clear automatically when the condition is fixed."
        actions={canAct && (
          <button type="button" className={btnSecondary} onClick={async () => {
            await api('/alerts/refresh', { method: 'POST' })
            reload()
            toast.success('Alerts re-evaluated')
          }}>
            <RefreshCw className="size-4" aria-hidden /> Re-check now
          </button>
        )}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={CircleAlert} tone="red" label="Critical" value={formatNumber(s?.critical)} note="Open, needs action" />
        <StatCard icon={TriangleAlert} tone="amber" label="Warning" value={formatNumber(s?.warning)} note="Open" />
        <StatCard icon={Info} tone="blue" label="Informational" value={formatNumber(s?.info)} note="Open" />
        <StatCard icon={BellRing} tone="teal" label="Acknowledged" value={formatNumber(s?.acknowledged)} note="Being handled" />
      </div>

      <Card className="mt-4">
        <CardHeader
          title="Alerts"
          action={
            <div className="flex flex-wrap gap-2">
              <FilterSelect label="Filter by status" value={status} onChange={(v) => { setStatus(v); setOffset(0) }}
                options={[{ value: 'active', label: 'Active' }, { value: 'open', label: 'Open' },
                  { value: 'acknowledged', label: 'Acknowledged' }, { value: 'resolved', label: 'Resolved (history)' }, { value: 'all', label: 'All' }]} />
              <FilterSelect label="Filter by severity" value={severity} onChange={(v) => { setSeverity(v); setOffset(0) }}
                options={[{ value: '', label: 'Severity: All' }, { value: 'critical', label: 'Critical' }, { value: 'warning', label: 'Warning' }, { value: 'info', label: 'Info' }]} />
              <FilterSelect label="Filter by type" value={type} onChange={(v) => { setType(v); setOffset(0) }}
                options={[{ value: '', label: 'Type: All' }, ...TYPES.map((t) => ({ value: t, label: humanize(t) }))]} />
            </div>
          }
        />
        <div className="mb-3"><FormError message={actionError} /></div>
        {list.error && !list.data ? <ErrorState message={list.error.message} onRetry={list.refetch} />
          : !list.data ? <LoadingState />
          : list.data.items.length === 0 ? <EmptyState title={status === 'active' ? 'No active alerts' : 'No alerts match'} />
          : (
            <>
              <div className="-mx-2 overflow-x-auto">
                <table className="w-full min-w-[1000px] text-left text-sm">
                  <thead>
                    <tr className="bg-surface-muted text-ink">
                      {['Severity', 'Alert', 'Vehicle', 'First seen', 'Last seen', 'Status', 'Actions'].map((h) => (
                        <th key={h} scope="col" className="px-3 py-2.5 font-semibold whitespace-nowrap first:rounded-l-xl last:rounded-r-xl">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {list.data.items.map((a) => (
                      <tr key={a.id} className="border-b border-line align-top last:border-0">
                        <td className="px-3 py-2.5"><StatusBadge status={a.severity} /></td>
                        <td className="px-3 py-2.5">
                          <span className="block font-semibold text-ink">{a.title}</span>
                          <span className="block text-xs text-ink-muted">{a.message}</span>
                          {a.resolution_note && (
                            <span className="block text-xs text-emerald-700">
                              {a.auto_resolved ? 'Auto-resolved' : `Resolved by ${a.resolved_by ?? 'staff'}`}: {a.resolution_note}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 whitespace-nowrap">{a.truck?.label ?? '—'}</td>
                        <td className="px-3 py-2.5 whitespace-nowrap">{formatDateTime(a.first_seen_at)}</td>
                        <td className="px-3 py-2.5 whitespace-nowrap">{formatDateTime(a.last_seen_at)}</td>
                        <td className="px-3 py-2.5"><StatusBadge status={a.status} /></td>
                        <td className="px-3 py-2.5">
                          <div className="flex gap-1.5 whitespace-nowrap">
                            <Link to={a.link} className={btnSmallGhost} aria-label={`Open ${a.title}`}>
                              <ExternalLink className="size-3.5" aria-hidden /> Open
                            </Link>
                            {canAct && a.status === 'open' && (
                              <button type="button" className={btnSmallGhost} onClick={() => void acknowledge(a)}>Acknowledge</button>
                            )}
                            {canAct && a.status !== 'resolved' && (
                              <button type="button" className={btnSmallPrimary} onClick={() => setResolving(a)}>Resolve</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} noun="alerts" onChange={setOffset} />
            </>
          )}
      </Card>
      {resolving && (
        <ResolveModal alert={resolving} onClose={() => setResolving(null)}
          onSaved={() => { setResolving(null); reload(); toast.success('Alert resolved') }} />
      )}
    </>
  )
}
