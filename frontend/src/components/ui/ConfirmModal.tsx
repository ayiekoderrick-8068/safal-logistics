import { LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { ApiError } from '../../lib/api'
import { btnPrimary, btnSecondary } from './buttons'
import { FormError } from './Form'
import { Modal } from './Modal'

export function ConfirmModal({
  title,
  message,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  title: string
  message: string
  confirmLabel: string
  onConfirm: () => Promise<void>
  onClose: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-4">
        <FormError message={error} />
        <p className="text-ink">{message}</p>
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className={`${btnSecondary} border-line`}>Keep it</button>
          <button
            type="button"
            disabled={busy}
            className={`${btnPrimary} bg-red-600 hover:bg-red-700`}
            onClick={async () => {
              setBusy(true)
              setError(null)
              try {
                await onConfirm()
              } catch (err) {
                setError(err instanceof ApiError ? err.message : 'Something went wrong.')
                setBusy(false)
              }
            }}
          >
            {busy && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}
