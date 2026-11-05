import { CircleCheck, Download, History, Plus, RefreshCw, ShieldAlert, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { btnSmallGhost, btnSmallPrimary } from '../../components/ui/buttons'
import { FormError } from '../../components/ui/Form'
import { Modal } from '../../components/ui/Modal'
import { LoadingState } from '../../components/ui/States'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { useToast } from '../../components/ui/toastContext'
import { useApi } from '../../hooks/useApi'
import { ApiError } from '../../lib/api'
import { DOC_LABELS, formatBytes, formatDate } from '../../lib/format'
import type { ComplianceDocument, DocType, VehicleCompliance } from '../../lib/types'
import { DocumentFormModal } from './DocumentFormModal'
import { ACCEPTED_FILES, uploadDocumentFile, validateFile } from './files'

const STATE_LABEL = { valid: 'Valid', expiring: 'Expiring soon', expired: 'Expired', missing: 'Missing', not_required: 'Not required' }

export function VehicleDocumentsModal({
  truckId,
  canEdit,
  onClose,
  onChanged,
}: {
  truckId: number
  canEdit: boolean
  onClose: () => void
  onChanged: () => void
}) {
  const [version, setVersion] = useState(0)
  const summary = useApi<VehicleCompliance>(`/trucks/${truckId}/compliance?v=${version}`)
  const docs = useApi<ComplianceDocument[]>(`/trucks/${truckId}/documents?v=${version}`)
  const [form, setForm] = useState<{ mode: 'add' | 'renew'; docType?: DocType; previous?: ComplianceDocument } | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const uploadTarget = useRef<ComplianceDocument | null>(null)
  const toast = useToast()

  const refresh = () => {
    setVersion((v) => v + 1)
    onChanged()
  }
  const current = docs.data?.filter((d) => d.is_current) ?? []
  const history = docs.data?.filter((d) => !d.is_current) ?? []
  const missing = summary.data?.items.filter((i) => i.state === 'missing') ?? []

  async function onFile(file: File | undefined) {
    const target = uploadTarget.current
    if (!file || !target) return
    const err = validateFile(file)
    if (err) {
      setUploadError(err)
      return
    }
    setUploadError(null)
    try {
      await uploadDocumentFile(target.id, file)
      toast.success(`File attached to ${DOC_LABELS[target.doc_type].toLowerCase()}`)
      refresh()
    } catch (e) {
      setUploadError(e instanceof ApiError ? e.message : 'Upload failed.')
    }
  }

  if (form) {
    return (
      <DocumentFormModal mode={form.mode} truckId={truckId} docType={form.docType} previous={form.previous}
        onClose={() => setForm(null)}
        onSaved={(d, fileError) => {
          setForm(null)
          refresh()
          toast.success(form.mode === 'renew' ? `${DOC_LABELS[d.doc_type]} renewed` : `${DOC_LABELS[d.doc_type]} added`)
          if (fileError) setUploadError(`Record saved, but the file was not attached: ${fileError}`)
        }} />
    )
  }

  const s = summary.data
  return (
    <Modal title={s ? `${s.truck.label} — compliance documents` : 'Compliance documents'} wide onClose={onClose}
      description={s?.driver_name ? `Driver: ${s.driver_name}` : undefined}>
      {!s || !docs.data ? (
        summary.error || docs.error ? <FormError message={(summary.error ?? docs.error)!.message} /> : <LoadingState />
      ) : (
        <div className="space-y-5">
          {s.eligible ? (
            <p className="flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-800">
              <CircleCheck className="size-5" aria-hidden /> Eligible for dispatch
            </p>
          ) : (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              <p className="flex items-center gap-2 font-semibold"><ShieldAlert className="size-5" aria-hidden /> Blocked from dispatch</p>
              <ul className="mt-1 list-disc pl-9">{s.blockers.map((b) => <li key={b}>{b}</li>)}</ul>
            </div>
          )}
          <FormError message={uploadError} />
          <input ref={fileInput} type="file" accept={ACCEPTED_FILES} className="sr-only" tabIndex={-1} aria-hidden
            onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = '' }} />

          <div className="-mx-2 overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm whitespace-nowrap">
              <caption className="sr-only">Current documents</caption>
              <thead>
                <tr className="bg-surface-muted text-ink">
                  {['Document', 'Reference', 'Issued', 'Expires', 'Status', 'File', ''].map((h, i) => (
                    <th key={i} scope="col" className="px-3 py-2 font-semibold first:rounded-l-xl last:rounded-r-xl">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {current.map((d) => (
                  <tr key={d.id} className="border-b border-line">
                    <td className="px-3 py-2.5 font-semibold text-ink">
                      {DOC_LABELS[d.doc_type]}
                      {d.issuing_authority && <span className="block text-xs font-normal text-ink-muted">{d.issuing_authority}</span>}
                    </td>
                    <td className="px-3 py-2.5">{d.reference_number}</td>
                    <td className="px-3 py-2.5">{formatDate(d.issued_on)}</td>
                    <td className="px-3 py-2.5">
                      {formatDate(d.expires_on)}
                      <span className="block text-xs text-ink-muted">
                        {d.days_remaining < 0 ? `${-d.days_remaining} days ago` : `in ${d.days_remaining} days`}
                      </span>
                    </td>
                    <td className="px-3 py-2.5"><StatusBadge status={d.state} label={STATE_LABEL[d.state]} /></td>
                    <td className="px-3 py-2.5">
                      {d.file ? (
                        <a href={`/api/compliance/documents/${d.id}/file`} className="inline-flex items-center gap-1 font-semibold text-primary hover:underline"
                          aria-label={`Download ${d.file.name}`}>
                          <Download className="size-4" aria-hidden /> {formatBytes(d.file.size)}
                        </a>
                      ) : <span className="text-ink-muted">None</span>}
                    </td>
                    <td className="px-3 py-2.5">
                      {canEdit && (
                        <div className="flex gap-1.5">
                          {d.doc_type !== 'other' && (
                            <button type="button" className={btnSmallPrimary} onClick={() => setForm({ mode: 'renew', previous: d })}>
                              <RefreshCw className="size-3.5" aria-hidden /> Renew
                            </button>
                          )}
                          <button type="button" className={btnSmallGhost}
                            onClick={() => { uploadTarget.current = d; fileInput.current?.click() }}>
                            <Upload className="size-3.5" aria-hidden /> {d.file ? 'Replace file' : 'Upload'}
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {missing.map((i) => (
                  <tr key={i.doc_type} className="border-b border-line bg-red-50/50">
                    <td className="px-3 py-2.5 font-semibold text-ink">{DOC_LABELS[i.doc_type]}</td>
                    <td className="px-3 py-2.5 text-ink-muted" colSpan={3}>No document on record (mandatory)</td>
                    <td className="px-3 py-2.5"><StatusBadge status="expired" label="Missing" /></td>
                    <td />
                    <td className="px-3 py-2.5">
                      {canEdit && (
                        <button type="button" className={btnSmallPrimary} onClick={() => setForm({ mode: 'add', docType: i.doc_type })}>
                          <Plus className="size-3.5" aria-hidden /> Add
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {current.length === 0 && missing.length === 0 && (
                  <tr><td colSpan={7} className="px-3 py-6 text-center text-ink-muted">No documents on record.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <button type="button" className={btnSmallGhost} aria-expanded={showHistory} onClick={() => setShowHistory((v) => !v)}
              disabled={history.length === 0}>
              <History className="size-3.5" aria-hidden /> History ({history.length})
            </button>
            {canEdit && (
              <button type="button" className={btnSmallPrimary} onClick={() => setForm({ mode: 'add' })}>
                <Plus className="size-3.5" aria-hidden /> Add document
              </button>
            )}
          </div>
          {showHistory && (
            <ul className="divide-y divide-line rounded-xl border border-line text-sm">
              {history.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
                  <span className="font-semibold text-ink">{DOC_LABELS[d.doc_type]}</span>
                  <span>{d.reference_number}</span>
                  <span className="text-ink-muted">{formatDate(d.issued_on)} – {formatDate(d.expires_on)}</span>
                  <span className="text-ink-muted">replaced {d.superseded_at ? formatDate(d.superseded_at.slice(0, 10)) : ''}</span>
                  {d.file && (
                    <a href={`/api/compliance/documents/${d.id}/file`} className="ml-auto inline-flex items-center gap-1 text-primary hover:underline">
                      <Download className="size-4" aria-hidden /> File
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Modal>
  )
}
