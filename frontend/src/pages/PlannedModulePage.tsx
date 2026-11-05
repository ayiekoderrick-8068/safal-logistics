import { CircleCheck, Hammer } from 'lucide-react'
import { Card } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import type { NavItem } from '../nav'

/** Real route for a module that is not built yet. Shows no figures, only the plan. */
export function PlannedModulePage({ item }: { item: NavItem }) {
  const plan = item.planned!
  return (
    <>
      <PageHeader title={item.title} description={item.description} />
      <Card className="max-w-3xl">
        <div className="flex items-start gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-sky-100 text-sky-700">
            <Hammer className="size-6" aria-hidden />
          </span>
          <div>
            <p className="text-xs font-semibold tracking-wide text-primary uppercase">{plan.milestone}</p>
            <h2 className="text-lg font-bold text-ink">This module is under construction</h2>
            <p className="mt-1 text-sm text-ink-muted">
              No data is displayed here until the module is built. LogiTrack never shows placeholder
              figures as live data.
            </p>
            <h3 className="mt-5 text-sm font-semibold text-ink">Planned capabilities</h3>
            <ul className="mt-2 space-y-2">
              {plan.features.map((f) => (
                <li key={f} className="flex items-start gap-2 text-sm text-ink">
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
                  {f}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>
    </>
  )
}
