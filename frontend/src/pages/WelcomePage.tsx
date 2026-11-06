import { ArrowRight, Cog, Truck, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router'
import { useAuth, WORKSPACE_HOME, WORKSPACE_LOGIN } from '../auth/context'
import { WORKSPACE_LABELS } from '../lib/format'
import type { Workspace } from '../lib/types'

const YEAR = new Date().getFullYear()

const WORKSPACES: { id: Workspace; icon: LucideIcon; summary: string; modules: string }[] = [
  {
    id: 'logistics',
    icon: Truck,
    summary: 'Fleet, loading bays, dispatch, compliance and turnaround analytics.',
    modules: 'Fleet · Loading bays · Dispatch · Reports',
  },
  {
    id: 'maintenance',
    icon: Cog,
    summary: 'Equipment register, preventive maintenance, work orders and breakdowns.',
    modules: 'Equipment · Work orders · Spare parts · Reports',
  },
]

/**
 * Public entry point: pick a workspace, then sign in to it. Each workspace has its own
 * sign-in and its own session; moving between them always asks for the password again.
 */
export function WelcomePage() {
  const { status, workspace } = useAuth()

  return (
    <div className="sidebar-gradient flex min-h-screen flex-col text-white">
      <header className="flex items-center gap-3 px-3.5 pt-3.5 sm:px-4 sm:pt-4 lg:px-5 lg:pt-5">
        <span className="grid size-11 place-items-center rounded-xl bg-gradient-to-br from-cyan-300 to-accent text-sidebar shadow-lg shadow-cyan-500/20 lg:size-14 lg:rounded-2xl">
          <Truck className="size-6 lg:size-8" strokeWidth={2.2} aria-hidden />
        </span>
        <div>
          <p className="text-xl leading-tight font-bold lg:text-2xl">LogiTrack</p>
          <p className="text-sm text-white/75 lg:text-base">Operations Portal</p>
        </div>
      </header>

      <main className="flex flex-1 flex-col items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-4xl">
          <h1 className="text-center text-3xl font-bold sm:text-4xl">Choose your workspace</h1>
          <p className="mx-auto mt-2 max-w-xl text-center text-white/75">
            Each workspace has its own sign-in. Switching between them always asks for your password.
          </p>

          <ul className="mt-8 grid gap-4 sm:mt-10 md:grid-cols-2 md:gap-6">
            {WORKSPACES.map(({ id, icon: Icon, summary, modules }) => {
              const here = status === 'authenticated' && workspace === id
              return (
                <li key={id}>
                  <Link
                    to={here ? WORKSPACE_HOME[id] : WORKSPACE_LOGIN[id]}
                    className="group flex h-full flex-col rounded-3xl bg-white p-6 text-ink shadow-xl shadow-black/20 ring-accent/60 transition hover:-translate-y-0.5 hover:shadow-2xl focus-visible:ring-4 focus-visible:outline-none sm:p-8"
                  >
                    <span className="grid size-14 place-items-center rounded-2xl bg-sky-100 text-primary">
                      <Icon className="size-7" aria-hidden />
                    </span>
                    <h2 className="mt-5 text-xl font-bold">{WORKSPACE_LABELS[id]}</h2>
                    <p className="mt-1.5 text-sm text-ink-muted">{summary}</p>
                    <p className="mt-3 text-xs font-semibold tracking-wide text-primary uppercase">{modules}</p>
                    <span className="mt-6 inline-flex items-center gap-2 pt-1 font-semibold text-primary sm:mt-auto">
                      {here ? 'Continue' : 'Sign in'}
                      <ArrowRight className="size-4 transition group-hover:translate-x-0.5" aria-hidden />
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      </main>

      <footer className="px-5 pb-5 text-center text-xs text-white/55">© {YEAR} LogiTrack · Operations Portal</footer>
    </div>
  )
}
