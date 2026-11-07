/**
 * Chart building blocks for the maintenance dashboard and reports, following the dataviz
 * method: one hue for single-series magnitude, reserved status colours only for equipment
 * state, thin marks (<= 24px, 4px rounded data-end), hairline solid grid, hover tooltips,
 * and a table view for every chart so no value depends on colour or hover alone.
 * Colours and their validation results: ./chartColors.ts
 */
import clsx from 'clsx'
import { BarChart3, Table2 } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardHeader } from '../../../components/ui/Card'
import { GRID, MUTED, SERIES } from './chartColors'

/** Card with a Chart | Table switch; the table is the accessible twin of the chart. */
export function ChartCard({ title, subtitle, table, children, className }: {
  title: string
  subtitle?: string
  table: { columns: string[]; rows: (string | number)[][] }
  children: ReactNode
  className?: string
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const id = useId()
  return (
    <Card className={className}>
      <CardHeader title={title} subtitle={subtitle} id={id}
        action={
          <span className="inline-flex rounded-lg border border-line p-0.5" role="group" aria-label={`${title} view`}>
            {(['chart', 'table'] as const).map((v) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
                className={clsx('inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-semibold',
                  view === v ? 'bg-primary text-white' : 'text-ink-muted hover:text-ink')}>
                {v === 'chart' ? <BarChart3 className="size-3.5" aria-hidden /> : <Table2 className="size-3.5" aria-hidden />}
                {v === 'chart' ? 'Chart' : 'Table'}
              </button>
            ))}
          </span>
        } />
      {view === 'chart' ? children : (
        <div className="-mx-2 max-h-80 overflow-auto">
          <table className="w-full text-left text-sm" aria-labelledby={id}>
            <thead>
              <tr className="bg-surface-muted text-ink">
                {table.columns.map((c) => <th key={c} scope="col" className="px-3 py-2 font-semibold">{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i} className="border-b border-line last:border-0">
                  {r.map((v, j) => <td key={j} className={clsx('px-3 py-1.5', j > 0 && 'tabular-nums')}>{v}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

/** Tall segmented bar: one whole split into <= 6 parts, counts inside where they fit. */
export function SegmentedBar({ parts, label }: {
  parts: { name: string; value: number; color: string; dark?: boolean }[]
  label: string
}) {
  const total = parts.reduce((s, p) => s + p.value, 0)
  if (!total) return <p className="text-sm text-ink-muted">No equipment registered yet.</p>
  return (
    <div>
      <div className="flex h-7 gap-0.5" role="img"
        aria-label={`${label}: ${parts.map((p) => `${p.name} ${p.value} of ${total}`).join(', ')}`}>
        {parts.filter((p) => p.value > 0).map((p) => {
          const share = p.value / total
          return (
            <div key={p.name} title={`${p.name}: ${p.value} (${Math.round(share * 100)}%)`}
              className="flex items-center rounded px-2 text-xs font-bold"
              style={{ width: `${share * 100}%`, background: p.color, color: p.dark ? '#0f2b3d' : '#ffffff' }}>
              {share >= 0.12 ? p.value : ''}
            </div>
          )
        })}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-sm text-ink">
        {parts.map((p) => (
          <li key={p.name} className="flex items-center gap-2">
            <span className="size-3 rounded-sm" style={{ background: p.color }} aria-hidden />
            {p.name} <span className="font-semibold tabular-nums">{p.value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Horizontal bars on one baseline, one hue, value at the tip. */
export function HBars({ items, unit, empty }: {
  items: { label: string; sub?: string; value: number; note?: string }[]
  unit?: (v: number) => string
  empty: string
}) {
  if (!items.length) return <p className="text-sm text-ink-muted">{empty}</p>
  const max = Math.max(...items.map((i) => i.value), 1)
  return (
    <ul className="space-y-2.5">
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[minmax(0,9rem)_1fr] items-center gap-3 text-sm sm:grid-cols-[minmax(0,12rem)_1fr]"
          title={`${i.label}: ${unit ? unit(i.value) : i.value}${i.note ? ` · ${i.note}` : ''}`}>
          <span className="min-w-0">
            <span className="block truncate font-medium text-ink">{i.label}</span>
            {i.sub && <span className="block truncate text-xs text-ink-muted">{i.sub}</span>}
          </span>
          <span className="flex items-center gap-2">
            <span className="h-3 rounded-r" style={{ width: `${Math.max((i.value / max) * 100, i.value ? 2 : 0)}%`, background: SERIES }} />
            <span className="shrink-0 font-semibold text-ink tabular-nums">{unit ? unit(i.value) : i.value}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Daily columns (single series). The plot height includes the axis band - no nested scroll. */
export function DailyColumns({ data, format }: {
  data: { label: string; value: number }[]
  format: (v: number) => string
}) {
  if (!data.some((d) => d.value > 0)) {
    return <p className="py-8 text-center text-sm text-ink-muted">No downtime recorded in this period.</p>
  }
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: GRID }} tick={{ fill: MUTED, fontSize: 11 }}
            interval="preserveStartEnd" minTickGap={18} />
          <YAxis tickLine={false} axisLine={false} tick={{ fill: MUTED, fontSize: 11 }} width={48}
            tickFormatter={(v: number) => format(v)} allowDecimals={false} />
          <Tooltip cursor={{ fill: 'rgba(8, 145, 178, 0.08)' }}
            formatter={(v) => [format(Number(v)), 'Downtime']}
            contentStyle={{ borderRadius: 12, border: `1px solid ${GRID}`, fontSize: 12 }} />
          <Bar dataKey="value" fill={SERIES} maxBarSize={24} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
