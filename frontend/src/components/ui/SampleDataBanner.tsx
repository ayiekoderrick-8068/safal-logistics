import { FlaskConical } from 'lucide-react'

/** Shown whenever the API reports the database holds the demonstration dataset. */
export function SampleDataBanner() {
  return (
    <div
      role="note"
      data-testid="sample-data-banner"
      className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-300 bg-amber-50/95 px-4 py-3 text-sm text-amber-900 shadow-sm"
    >
      <FlaskConical className="mt-0.5 size-5 shrink-0 text-amber-600" aria-hidden />
      <p>
        <strong className="font-semibold">Sample data.</strong> These figures are calculated from a
        demonstration dataset, not live operations. An administrator can remove it with{' '}
        <code className="rounded bg-amber-100 px-1">python -m app.cli clear-sample --yes</code>.
      </p>
    </div>
  )
}
