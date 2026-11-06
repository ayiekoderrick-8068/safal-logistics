import clsx from 'clsx'
import { humanize } from '../../lib/format'
import { statusTone, type Tone } from '../../lib/statusColors'

const TONE_CLASSES: Record<Tone, string> = {
  green: 'bg-emerald-100 text-emerald-800',
  amber: 'bg-amber-100 text-amber-800',
  red: 'bg-red-100 text-red-700',
  blue: 'bg-sky-100 text-sky-800',
  slate: 'bg-slate-100 text-slate-700',
}
const DOT_CLASSES: Record<Tone, string> = {
  green: 'bg-emerald-500',
  amber: 'bg-amber-500',
  red: 'bg-red-500',
  blue: 'bg-sky-500',
  slate: 'bg-slate-400',
}

export function StatusBadge({ status, label, tone: toneOverride }: { status: string; label?: string; tone?: Tone }) {
  const tone = toneOverride ?? statusTone(status)
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap',
        TONE_CLASSES[tone],
      )}
    >
      <span className={clsx('size-1.5 rounded-full', DOT_CLASSES[tone])} aria-hidden />
      {label ?? humanize(status)}
    </span>
  )
}
