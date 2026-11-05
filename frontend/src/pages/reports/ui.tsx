import clsx from 'clsx'
import { Download, FileText } from 'lucide-react'
import type { ReactNode } from 'react'

export interface Col<T> {
  header: string
  cell: (row: T) => ReactNode
  className?: string
}

/** Compact report table with an explicit empty message. */
export function DataTable<T>({ cols, rows, empty, caption, minWidth = 640 }: {
  cols: Col<T>[]
  rows: T[]
  empty: string
  caption?: string
  minWidth?: number
}) {
  if (rows.length === 0) return <p className="rounded-xl bg-surface-muted px-4 py-6 text-center text-sm text-ink-muted">{empty}</p>
  return (
    <div className="-mx-2 overflow-x-auto">
      <table className="w-full text-left text-sm whitespace-nowrap" style={{ minWidth }}>
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="bg-surface-muted text-ink">
            {cols.map((c) => (
              <th key={c.header} scope="col" className="px-3 py-2.5 font-semibold first:rounded-l-xl last:rounded-r-xl">{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line last:border-0">
              {cols.map((c) => <td key={c.header} className={clsx('px-3 py-2', c.className)}>{c.cell(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Download link for a server-generated export (session cookie is sent automatically). */
export function ExportLink({ href, format, label, onClick }: {
  href: string
  format: 'csv' | 'pdf'
  label: string
  onClick?: () => void
}) {
  const Icon = format === 'pdf' ? FileText : Download
  return (
    <a href={href} download onClick={onClick}
      className={clsx('inline-flex h-10 items-center gap-2 rounded-xl border px-3.5 text-sm font-semibold shadow-sm',
        format === 'pdf' ? 'border-red-100 bg-white text-red-700 hover:bg-red-50' : 'border-emerald-100 bg-white text-emerald-700 hover:bg-emerald-50')}>
      <Icon className="size-4" aria-hidden /> {label}
    </a>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div role="tablist" aria-label="Report sections" className="mb-4 flex gap-1 overflow-x-auto rounded-2xl bg-white/70 p-1.5 shadow-sm">
      {tabs.map((t) => (
        <button key={t.value} type="button" role="tab" aria-selected={value === t.value} id={`tab-${t.value}`}
          aria-controls={`panel-${t.value}`} onClick={() => onChange(t.value)}
          className={clsx('rounded-xl px-4 py-2 text-sm font-semibold whitespace-nowrap transition-colors',
            value === t.value ? 'bg-primary text-white shadow' : 'text-ink hover:bg-white')}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-xs text-ink-muted">{children}</p>
}
