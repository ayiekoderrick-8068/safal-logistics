import { useState } from 'react'
import { Outlet } from 'react-router'
import { useMaintenanceAccess } from '../../lib/maintenance'
import type { Workspace } from '../../lib/types'
import { SampleDataBanner } from '../ui/SampleDataBanner'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

/** Every maintenance page says so while the demonstration dataset is loaded. */
function MaintenanceSampleBanner() {
  const { sampleData } = useMaintenanceAccess()
  return sampleData ? <SampleDataBanner subject="maintenance records" command="clear-maintenance-sample" /> : null
}

export function AppLayout({ workspace = 'logistics' }: { workspace?: Workspace }) {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  function toggleNav() {
    if (window.matchMedia('(min-width: 1024px)').matches) setCollapsed((c) => !c)
    else setMobileOpen((o) => !o)
  }

  return (
    <div className="flex min-h-screen bg-sidebar-deep">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-white px-4 py-2 text-ink focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <Sidebar
        workspace={workspace}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col bg-topbar">
        <Topbar workspace={workspace} onToggleNav={toggleNav} />
        <main
          id="main"
          className="workspace-gradient flex-1 px-4 py-5 md:px-6 md:py-6 lg:rounded-tl-[28px]"
        >
          {workspace === 'maintenance' && <MaintenanceSampleBanner />}
          <Outlet />
        </main>
      </div>
    </div>
  )
}
