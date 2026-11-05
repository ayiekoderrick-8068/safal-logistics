import clsx from 'clsx'
import { ArrowDown, ArrowUp, Minus, type LucideIcon } from 'lucide-react'
import type { Trend } from '../../lib/format'

const TONES = {
  blue: 'bg-sky-100 text-sky-600',
  green: 'bg-emerald-100 text-emerald-600',
  amber: 'bg-amber-100 text-amber-600',
  red: 'bg-red-100 text-red-600',
  teal: 'bg-cyan-100 text-cyan-700',
} as const

export function StatCard({
  icon: Icon,
  tone,
  value,
  label,
  trend,
  note,
}: {
  icon: LucideIcon
  tone: keyof typeof TONES
  value: string
  label: string
  trend?: Trend | null
  note?: string
}) {
  const TrendIcon = trend?.direction === 'up' ? ArrowUp : trend?.direction === 'down' ? ArrowDown : Minus
  return (
    <article className="card flex items-center gap-3.5 px-4 py-4" aria-label={label}>
      <span className={clsx('grid size-13 shrink-0 place-items-center rounded-2xl', TONES[tone])}>
        <Icon className="size-7" strokeWidth={2} aria-hidden />
      </span>
      <div className="min-w-0">
        <p className="text-[1.6rem] leading-tight font-bold text-ink" data-testid="stat-value">{value}</p>
        <p className="text-[0.95rem] leading-snug text-ink">{label}</p>
        {(trend || note) && (
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[0.82rem]">
            {trend && (
              <span
                className={clsx(
                  'inline-flex items-center gap-0.5 font-semibold',
                  trend.good === null ? 'text-ink-muted' : trend.good ? 'text-emerald-600' : 'text-red-600',
                )}
              >
                <TrendIcon className="size-3.5" strokeWidth={3} aria-hidden />
                {trend.text}
              </span>
            )}
            {note && <span className="text-ink-muted">{note}</span>}
          </p>
        )}
      </div>
    </article>
  )
}
