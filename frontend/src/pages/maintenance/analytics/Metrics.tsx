import { Info } from 'lucide-react'
import { formatDuration, formatNumber, formatPercent } from '../../../lib/format'
import { hoursOrMinutes, type MaintenanceKpis } from '../../../lib/maintenance'

type Metrics = Pick<MaintenanceKpis, 'availability' | 'mtbf' | 'mttr' | 'pm_compliance'>

function Metric({ label, value, sample, how }: { label: string; value: string | null; sample: string; how: string }) {
  return (
    <article className="card px-4 py-4" aria-label={label}>
      <p className="text-[0.95rem] text-ink">{label}</p>
      {value == null ? (
        <p className="mt-1 text-lg font-bold text-ink-muted" data-testid="metric-value">Insufficient data</p>
      ) : (
        <p className="mt-0.5 text-[1.6rem] leading-tight font-bold text-ink" data-testid="metric-value">{value}</p>
      )}
      <p className="mt-0.5 text-[0.82rem] text-ink-muted">{sample}</p>
      <p className="mt-2 flex gap-1.5 border-t border-line pt-2 text-xs text-ink-muted">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden />{how}
      </p>
    </article>
  )
}

/** Availability, MTBF, MTTR and PM compliance - each with its sample size and definition. */
export function ReliabilityMetrics({ m }: { m: Metrics }) {
  const pm = m.pm_compliance
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 xl:grid-cols-4">
      <Metric label="Availability" value={m.availability.pct == null ? null : formatPercent(m.availability.pct)}
        sample={`${formatDuration(m.availability.downtime_minutes)} down in ${formatNumber(m.availability.observed_hours)} h observed`}
        how="(observed − downtime) ÷ observed; equipment assumed scheduled 24 h a day." />
      <Metric label="MTBF" value={m.mtbf.hours == null ? null : hoursOrMinutes(m.mtbf.hours)}
        sample={m.mtbf.failures ? `${m.mtbf.failures} failure${m.mtbf.failures === 1 ? '' : 's'} in ${m.mtbf.operating_hours > 0 ? hoursOrMinutes(m.mtbf.operating_hours) : 'no'} operating time` : 'No stopping failures in this period'}
        how="Operating time ÷ failures. Calendar-based: there are no run-hour meters." />
      <Metric label="MTTR" value={m.mttr.minutes == null ? null : formatDuration(m.mttr.minutes)}
        sample={m.mttr.repairs ? `${m.mttr.repairs} completed repair${m.mttr.repairs === 1 ? '' : 's'}` : 'No corrective work completed in this period'}
        how="Mean start-to-completion time of completed corrective work orders." />
      <Metric label="PM compliance" value={pm.pct == null ? null : formatPercent(pm.pct)}
        sample={pm.due ? `${pm.on_time} of ${pm.due} on time · ${pm.late} late · ${pm.missed} not done` : 'No preventive tasks fell due in this period'}
        how="Preventive tasks due in the period completed by their due date." />
    </div>
  )
}
