import clsx from 'clsx'
import { BarChart3, Cog, X } from 'lucide-react'
import { NavLink } from 'react-router'
import { useAuth, WORKSPACE_HOME } from '../../auth/context'
import { Logo } from '../brand/Logo'
import { WORKSPACE_LABELS } from '../../lib/format'
import type { Workspace } from '../../lib/types'
import { MAINTENANCE_NAV } from '../../maintenanceNav'
import { NAV } from '../../nav'

export function Sidebar({
  workspace = 'logistics',
  collapsed,
  mobileOpen,
  onClose,
}: {
  workspace?: Workspace
  collapsed: boolean
  mobileOpen: boolean
  onClose: () => void
}) {
  const { hasRole } = useAuth()
  const sections = workspace === 'maintenance' ? MAINTENANCE_NAV : NAV
  const home = WORKSPACE_HOME[workspace]
  const FooterIcon = workspace === 'maintenance' ? Cog : BarChart3

  return (
    <>
      {mobileOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={onClose} aria-hidden />
      )}
      <aside
        id="app-sidebar"
        className={clsx(
          'sidebar-gradient fixed inset-y-0 left-0 z-40 flex w-64 flex-col text-white transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
          collapsed && 'lg:w-[84px]',
        )}
      >
        <div className="flex items-center gap-3 px-5 pt-4 pb-4">
          <NavLink to={home} onClick={onClose} className="rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300">
            <Logo variant="compact" surface="dark" className={clsx('h-11', collapsed && 'lg:hidden')} />
            <Logo variant="icon" className={clsx('hidden size-11', collapsed && 'lg:block')} />
          </NavLink>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto rounded-lg p-1.5 text-white/80 hover:bg-white/10 lg:hidden"
            aria-label="Close navigation"
          >
            <X className="size-5" />
          </button>
        </div>

        <nav aria-label="Main navigation" className="flex-1 overflow-y-auto px-3 pb-4">
          {sections.map((section) => {
            const items = section.items.filter((item) => !item.roles || hasRole(...item.roles))
            if (items.length === 0) return null
            return (
              <div key={section.label} className="border-t border-white/10 pt-3 pb-2 first:border-t-0">
                <p
                  className={clsx(
                    'px-3 pb-1.5 text-[0.8rem] font-semibold tracking-wide text-white/85 uppercase',
                    collapsed && 'lg:sr-only',
                  )}
                >
                  {section.label}
                </p>
                <ul className="space-y-0.5">
                  {items.map((item) => (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        end={item.to === home}
                        onClick={onClose}
                        title={collapsed ? item.label : undefined}
                        className={({ isActive }) =>
                          clsx(
                            'flex items-center gap-3 rounded-xl px-3 py-2 text-[0.97rem] transition-colors',
                            isActive ? 'nav-active font-semibold text-white' : 'text-white/90 hover:bg-white/10',
                            collapsed && 'lg:justify-center',
                          )
                        }
                      >
                        <item.icon className="size-5 shrink-0" aria-hidden />
                        <span className={clsx(collapsed && 'lg:sr-only')}>{item.label}</span>
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </nav>

        <div className={clsx('m-4 rounded-2xl border border-white/10 bg-white/5 p-3', collapsed && 'lg:hidden')}>
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-lg bg-sky-500/30 text-cyan-200">
              <FooterIcon className="size-5" aria-hidden />
            </span>
            <div>
              <p className="text-sm font-semibold">LogiTrack v{__APP_VERSION__}</p>
              <p className="text-xs text-white/75">{WORKSPACE_LABELS[workspace]}</p>
            </div>
          </div>
        </div>
      </aside>
    </>
  )
}
