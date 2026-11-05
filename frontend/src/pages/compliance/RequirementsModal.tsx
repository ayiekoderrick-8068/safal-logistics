import { useState } from 'react'
import { btnSmallPrimary, inputClass } from '../../components/ui/buttons'
import { FormError } from '../../components/ui/Form'
import { Modal } from '../../components/ui/Modal'
import { LoadingState } from '../../components/ui/States'
import { useToast } from '../../components/ui/toastContext'
import { useApi } from '../../hooks/useApi'
import { api, ApiError } from '../../lib/api'
import type { Requirement } from '../../lib/types'

type Draft = { is_mandatory: boolean; min_capacity: string; reminder_days: string }

export function RequirementsModal({ canEdit, onClose, onSaved }: { canEdit: boolean; onClose: () => void; onSaved: () => void }) {
  const reqs = useApi<Requirement[]>('/compliance/requirements')
  return (
    <Modal title="Compliance Requirements" wide onClose={onClose}
      description="Mandatory documents must be present and unexpired before a truck can be dispatched. Requirements can apply only above a truck capacity.">
      {reqs.data ? <RequirementsTable rows={reqs.data} canEdit={canEdit} onSaved={onSaved} />
        : reqs.error ? <FormError message={reqs.error.message} /> : <LoadingState />}
    </Modal>
  )
}

function RequirementsTable({ rows, canEdit, onSaved }: { rows: Requirement[]; canEdit: boolean; onSaved: () => void }) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() => Object.fromEntries(rows.map((r) => [r.doc_type, {
    is_mandatory: r.is_mandatory, min_capacity: r.min_capacity_tonnes?.toString() ?? '', reminder_days: String(r.reminder_days),
  }])))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const toast = useToast()

  async function save(r: Requirement) {
    const d = drafts[r.doc_type]
    const reminder = Number(d.reminder_days)
    const capacity = d.min_capacity.trim() === '' ? null : Number(d.min_capacity)
    if (!Number.isInteger(reminder) || reminder < 1 || reminder > 365) return setError(`${r.label}: reminder must be 1–365 days`)
    if (capacity !== null && !(capacity > 0 && capacity <= 100)) return setError(`${r.label}: capacity must be between 0 and 100 t`)
    setError(null)
    setSaving(r.doc_type)
    try {
      await api(`/compliance/requirements/${r.doc_type}`, {
        method: 'PUT', body: JSON.stringify({ is_mandatory: d.is_mandatory, min_capacity_tonnes: capacity, reminder_days: reminder }),
      })
      toast.success(`${r.label} requirement saved`)
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save.')
    } finally {
      setSaving(null)
    }
  }

  const set = (t: string, patch: Partial<Draft>) => setDrafts((all) => ({ ...all, [t]: { ...all[t], ...patch } }))
  return (
    <div className="space-y-3">
      <FormError message={error} />
      {!canEdit && <p className="text-sm text-ink-muted">Only administrators and compliance officers can change requirements.</p>}
      <div className="-mx-2 overflow-x-auto">
        <table className="w-full min-w-[620px] text-left text-sm">
          <thead>
            <tr className="bg-surface-muted text-ink">
              {['Document type', 'Mandatory', 'Applies from (t)', 'Reminder (days)', ''].map((h, i) => (
                <th key={i} scope="col" className="px-3 py-2 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const d = drafts[r.doc_type]
              return (
                <tr key={r.doc_type} className="border-b border-line">
                  <th scope="row" className="px-3 py-2 text-left font-semibold text-ink">{r.label}</th>
                  <td className="px-3 py-2">
                    <input type="checkbox" className="size-4 accent-[#0e6481]" checked={d.is_mandatory}
                      disabled={!canEdit || r.doc_type === 'other'} aria-label={`${r.label} mandatory`}
                      onChange={(e) => set(r.doc_type, { is_mandatory: e.target.checked })} />
                  </td>
                  <td className="px-3 py-2">
                    <input type="number" min="0" step="0.5" className={`${inputClass} h-9 w-28`} placeholder="All trucks"
                      value={d.min_capacity} disabled={!canEdit || !d.is_mandatory} aria-label={`${r.label} minimum capacity`}
                      onChange={(e) => set(r.doc_type, { min_capacity: e.target.value })} />
                  </td>
                  <td className="px-3 py-2">
                    <input type="number" min="1" max="365" className={`${inputClass} h-9 w-24`} value={d.reminder_days}
                      disabled={!canEdit} aria-label={`${r.label} reminder days`}
                      onChange={(e) => set(r.doc_type, { reminder_days: e.target.value })} />
                  </td>
                  <td className="px-3 py-2">
                    {canEdit && (
                      <button type="button" className={btnSmallPrimary} disabled={saving === r.doc_type} onClick={() => void save(r)}>
                        Save
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
