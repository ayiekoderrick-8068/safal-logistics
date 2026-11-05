import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { AuthProvider } from './auth/AuthContext'
import { useAuth } from './auth/context'
import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './components/layout/AppLayout'
import { LoadingState } from './components/ui/States'
import { ToastProvider } from './components/ui/Toast'
import { ALL_NAV_ITEMS, type NavItem } from './nav'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { PlannedModulePage } from './pages/PlannedModulePage'

// Charting code is heavy: load module pages only when they are opened.
const OverviewPage = lazy(() => import('./pages/overview/OverviewPage').then((m) => ({ default: m.OverviewPage })))
const FleetPage = lazy(() => import('./pages/fleet/FleetPage').then((m) => ({ default: m.FleetPage })))
const LoadingBaysPage = lazy(() =>
  import('./pages/loading/LoadingBaysPage').then((m) => ({ default: m.LoadingBaysPage })),
)
const DispatchPage = lazy(() => import('./pages/dispatch/DispatchPage').then((m) => ({ default: m.DispatchPage })))
const ComplianceRecordsPage = lazy(() =>
  import('./pages/compliance/ComplianceRecordsPage').then((m) => ({ default: m.ComplianceRecordsPage })),
)

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<LoadingState label="Loading…" />}>{children}</Suspense>
}

function ModuleRoute({ item }: { item: NavItem }) {
  const { hasRole } = useAuth()
  if (item.roles && !hasRole(...item.roles)) return <NotFoundPage forbidden />
  return <PlannedModulePage item={item} />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Lazy><OverviewPage /></Lazy>} />
        <Route path="fleet" element={<Lazy><FleetPage /></Lazy>} />
        <Route path="loading-bays" element={<Lazy><LoadingBaysPage /></Lazy>} />
        <Route path="dispatch" element={<Lazy><DispatchPage /></Lazy>} />
        <Route path="compliance" element={<Lazy><ComplianceRecordsPage /></Lazy>} />
        {ALL_NAV_ITEMS.filter((i) => i.planned).map((item) => (
          <Route key={item.to} path={item.to.slice(1)} element={<ModuleRoute item={item} />} />
        ))}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <AppRoutes />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
