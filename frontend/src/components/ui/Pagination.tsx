import clsx from 'clsx'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export function Pagination({
  total,
  limit,
  offset,
  noun,
  onChange,
}: {
  total: number
  limit: number
  offset: number
  noun: string
  onChange: (offset: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / limit))
  const current = Math.floor(offset / limit) + 1
  const first = Math.max(1, Math.min(current - 2, pages - 4))
  const visible = Array.from({ length: Math.min(5, pages) }, (_, i) => first + i)
  const box = 'grid size-9 place-items-center rounded-lg border text-sm font-semibold'

  return (
    <nav aria-label={`${noun} pages`} className="mt-4 flex flex-col items-center justify-between gap-3 sm:flex-row">
      <p className="text-sm text-ink-muted">
        {total === 0 ? `No ${noun}` : `Showing ${offset + 1} – ${Math.min(offset + limit, total)} of ${total} ${noun}`}
      </p>
      {pages > 1 && (
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label="Previous page" disabled={current === 1}
            onClick={() => onChange(offset - limit)}
            className={clsx(box, 'border-line bg-white text-ink disabled:opacity-40')}>
            <ChevronLeft className="size-4" />
          </button>
          {visible.map((p) => (
            <button key={p} type="button" onClick={() => onChange((p - 1) * limit)}
              aria-current={p === current ? 'page' : undefined}
              className={clsx(box, p === current ? 'border-primary bg-primary text-white' : 'border-line bg-white text-ink hover:bg-surface-muted')}>
              {p}
            </button>
          ))}
          <button type="button" aria-label="Next page" disabled={current === pages}
            onClick={() => onChange(offset + limit)}
            className={clsx(box, 'border-line bg-white text-ink disabled:opacity-40')}>
            <ChevronRight className="size-4" />
          </button>
        </div>
      )}
    </nav>
  )
}
