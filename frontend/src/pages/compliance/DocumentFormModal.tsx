import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { inputClass } from '../../components/ui/buttons'
import { Field, FormActions, FormError } from '../../components/ui/Form'
import { a11y } from '../../components/ui/formA11y'
import { Modal } from '../../components/ui/Modal'
import { LoadingState } from '../../components/ui/States'
import { useApi } from '../../hooks/useApi'
import { api, ApiError } from '../../lib/api'
import { DOC_LABELS, formatDate } from '../../lib/format'
import type { ComplianceDocument, DocType, Page, Truck } from '../../lib/types'
import { todayIn } from '../overview/period'
import { ACCEPTED_FILES, uploadDocumentFile, validateFile } from './files'

const schema = z
  .object({
    truck_id: z.string().min(1, 'Select a truck'),
    doc_type: z.string().min(1, 'Select a document type'),
    reference_number: z.string().trim().min(1, 'Enter the document reference').max(80),
    issuing_authority: z.string().trim().max(120),
    issued_on: z.string().min(1, 'Enter the issue date'),
    expires_on: z.string().min(1, 'Enter the expiry date'),
    notes: z.string().max(1000),
  })
  .refine((v) => !v.issued_on || !v.expires_on || v.expires_on > v.issued_on, {
    message: 'Expiry must be after the issue date',
    path: ['expires_on'],
  })
type Values = z.infer<typeof schema>

/**
 * Add a new document (mode "add") or renew a current one (mode "renew"). Renewal creates a
 * new record and keeps the previous one as history.
 */
export function DocumentFormModal({
  mode,
  truckId,
  docType,
  previous,
  onClose,
  onSaved,
}: {
  mode: 'add' | 'renew'
  truckId?: number
  docType?: DocType
  previous?: ComplianceDocument
  onClose: () => void
  onSaved: (d: ComplianceDocument, fileError?: string) => void
}) {
  // The truck is already known when renewing or adding from a vehicle view.
  const knownTruck = truckId ?? previous?.truck.id
  const trucks = useApi<Page<Truck>>(knownTruck ? null : '/trucks?limit=100')
  const title = mode === 'renew' ? `Renew ${DOC_LABELS[previous!.doc_type].toLowerCase()}` : 'Add Compliance Record'
  return (
    <Modal title={title} wide
      description={mode === 'renew'
        ? `${previous!.truck.label} · current ${previous!.reference_number} expires ${formatDate(previous!.expires_on)}. The current record is kept as history.`
        : 'Record a vehicle document. Attach the scanned certificate if available.'}
      onClose={onClose}>
      {knownTruck || trucks.data ? (
        <DocumentForm mode={mode} truckId={truckId} docType={docType} previous={previous}
          trucks={trucks.data?.items ?? []} onClose={onClose} onSaved={onSaved} />
      ) : trucks.error ? <FormError message={trucks.error.message} /> : <LoadingState />}
    </Modal>
  )
}

function DocumentForm({
  mode, truckId, docType, previous, trucks, onClose, onSaved,
}: {
  mode: 'add' | 'renew'
  truckId?: number
  docType?: DocType
  previous?: ComplianceDocument
  trucks: Truck[]
  onClose: () => void
  onSaved: (d: ComplianceDocument, fileError?: string) => void
}) {
  const [serverError, setServerError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string>()
  const [today] = useState(() => todayIn())
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      truck_id: String(previous?.truck.id ?? truckId ?? ''),
      doc_type: previous?.doc_type ?? docType ?? '',
      reference_number: '',
      issuing_authority: previous?.issuing_authority ?? '',
      issued_on: today,
      expires_on: '',
      notes: '',
    },
  })

  const submit = handleSubmit(async (v) => {
    const fErr = validateFile(file)
    setFileError(fErr)
    if (fErr) return
    setServerError(null)
    const fields = {
      reference_number: v.reference_number, issuing_authority: v.issuing_authority || null,
      issued_on: v.issued_on, expires_on: v.expires_on, notes: v.notes.trim() || null,
    }
    let saved: ComplianceDocument
    try {
      saved = mode === 'renew'
        ? await api<ComplianceDocument>(`/compliance/documents/${previous!.id}/renew`, { method: 'POST', body: JSON.stringify(fields) })
        : await api<ComplianceDocument>('/compliance/documents', {
            method: 'POST', body: JSON.stringify({ ...fields, truck_id: Number(v.truck_id), doc_type: v.doc_type }),
          })
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not save the document.')
      return
    }
    if (file) {
      try {
        saved = await uploadDocumentFile(saved.id, file)
      } catch (err) {
        // The record is saved; report the file problem without losing it.
        onSaved(saved, err instanceof ApiError ? err.message : 'The file could not be uploaded.')
        return
      }
    }
    onSaved(saved)
  })

  const locked = mode === 'renew' || !!truckId
  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={serverError} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="doc-truck" label="Truck" error={errors.truck_id?.message}>
          <select {...a11y('doc-truck', errors.truck_id?.message)} {...register('truck_id')} disabled={locked} className={inputClass}>
            <option value="">Select truck…</option>
            {previous && <option value={previous.truck.id}>{previous.truck.label}</option>}
            {!previous && truckId && !trucks.length && <option value={truckId}>Selected truck</option>}
            {trucks.map((t) => <option key={t.id} value={t.id}>{t.registration}</option>)}
          </select>
        </Field>
        <Field id="doc-type" label="Document type" error={errors.doc_type?.message}>
          <select {...a11y('doc-type', errors.doc_type?.message)} {...register('doc_type')} disabled={mode === 'renew' || !!docType}
            className={inputClass}>
            <option value="">Select type…</option>
            {Object.entries(DOC_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field id="doc-ref" label="Document reference" error={errors.reference_number?.message}>
          <input {...a11y('doc-ref', errors.reference_number?.message)} {...register('reference_number')} className={inputClass}
            placeholder="e.g. POL-2026-00123" />
        </Field>
        <Field id="doc-authority" label="Issuing authority (optional)" error={errors.issuing_authority?.message}>
          <input {...a11y('doc-authority', errors.issuing_authority?.message)} {...register('issuing_authority')}
            className={inputClass} placeholder="e.g. NTSA" />
        </Field>
        <Field id="doc-issued" label="Issue date" error={errors.issued_on?.message}>
          <input type="date" {...a11y('doc-issued', errors.issued_on?.message)} {...register('issued_on')} className={inputClass} />
        </Field>
        <Field id="doc-expires" label="Expiry date" error={errors.expires_on?.message}
          hint={previous ? `Must be after ${formatDate(previous.expires_on)}` : undefined}>
          <input type="date" {...a11y('doc-expires', errors.expires_on?.message, !!previous)} {...register('expires_on')} className={inputClass} />
        </Field>
      </div>
      <Field id="doc-file" label="Supporting document (optional)" error={fileError} hint="PDF, PNG or JPEG, up to 10 MB.">
        <input type="file" accept={ACCEPTED_FILES} {...a11y('doc-file', fileError, true)}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-ink file:mr-3 file:rounded-lg file:border-0 file:bg-surface-muted file:px-3 file:py-2 file:font-semibold file:text-ink" />
      </Field>
      <Field id="doc-notes" label="Notes (optional)" error={errors.notes?.message}>
        <textarea {...a11y('doc-notes', errors.notes?.message)} {...register('notes')} rows={2} className={`${inputClass} h-auto py-2`} />
      </Field>
      <FormActions submitLabel={mode === 'renew' ? 'Save renewal' : 'Save record'} submitting={isSubmitting} onCancel={onClose} />
    </form>
  )
}
