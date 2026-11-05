import { LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { btnPrimary, btnSecondary } from './buttons'

export function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string
  label: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-semibold text-ink">{label}</label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-sm text-red-600">{error}</p>
      ) : (
        hint && <p id={`${id}-hint`} className="mt-1 text-xs text-ink-muted">{hint}</p>
      )}
    </div>
  )
}


export function FormError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
    </div>
  )
}

export function FormActions({
  submitLabel,
  submitting,
  onCancel,
}: {
  submitLabel: string
  submitting: boolean
  onCancel: () => void
}) {
  return (
    <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
      <button type="button" onClick={onCancel} className={`${btnSecondary} border-line`}>Cancel</button>
      <button type="submit" disabled={submitting} className={btnPrimary}>
        {submitting && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
        {submitLabel}
      </button>
    </div>
  )
}
