import { CircleAlert, Inbox, LoaderCircle, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center justify-center gap-3 py-10 text-ink-muted">
      <LoaderCircle className="size-5 animate-spin text-accent" aria-hidden />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <span className="grid size-11 place-items-center rounded-full bg-surface-muted text-ink-muted">
        <Inbox className="size-5" aria-hidden />
      </span>
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="max-w-sm text-sm text-ink-muted">{children}</div>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
      <span className="grid size-11 place-items-center rounded-full bg-red-50 text-red-600">
        <CircleAlert className="size-5" aria-hidden />
      </span>
      <p className="font-semibold text-ink">Could not load data</p>
      <p className="max-w-sm text-sm text-ink-muted">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-2 rounded-xl border border-line bg-white px-4 py-2 text-sm font-semibold text-ink shadow-sm hover:bg-surface-muted"
        >
          <RefreshCw className="size-4" aria-hidden /> Try again
        </button>
      )}
    </div>
  )
}
