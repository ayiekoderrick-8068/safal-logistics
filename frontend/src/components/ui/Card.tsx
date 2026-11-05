import clsx from 'clsx'
import type { ReactNode } from 'react'

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={clsx('card p-5', className)}>{children}</section>
}

export function CardHeader({
  title,
  subtitle,
  action,
  id,
}: {
  title: ReactNode
  subtitle?: string
  action?: ReactNode
  id?: string
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <h2 id={id} className="text-lg font-bold text-ink">{title}</h2>
        {subtitle && <p className="text-sm text-ink-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}
