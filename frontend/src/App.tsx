import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { AuthProvider } from './auth/AuthContext'
import { useAuth } from './auth/context'
import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './components/layout/AppLayout'
import { LoadingState } from './components/ui/States'
import { ToastProvider } from './components/ui/Toast'
import { ALL_MAINTENANCE_ITEMS } from './maintenanceNav'
import { ALL_NAV_ITEMS, type NavItem } from './nav'
import { LoginPage, MaintenanceLoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { PlannedModulePage } from './pages/PlannedModulePage'
import { WelcomePage } from './pages/WelcomePage'

// Charting code is heavy: load module pages only when they are opened.
const OverviewPage = lazy(() => import('./pages/overview/OverviewPage').then((m) => ({ default: m.OverviewPage })))
const FleetPage = lazy(() => import('./pages/fleet/FleetPage').then((m) => ({ default: m.FleetPage })))
const LoadingBaysPage = lazy(() =>
  import('./pages/loading/LoadingBaysPage').then((m) => ({ default: m.LoadingBaysPage })),
)
const DispatchPage = lazy(() => import('./pages/dispatch/DispatchPage').then((m) => ({ default: m.DispatchPage })))
const TurnaroundAnalyticsPage = lazy(() =>
  import('./pages/turnaround/TurnaroundAnalyticsPage').then((m) => ({ default: m.TurnaroundAnalyticsPage })),
)
const ReportsPage = lazy(() => import('./pages/reports/ReportsPage').then((m) => ({ default: m.ReportsPage })))
const AlertsPage = lazy(() => import('./pages/alerts/AlertsPage').then((m) => ({ default: m.AlertsPage })))
const DelayReportsPage = lazy(() => import('./pages/delays/DelayReportsPage').then((m) => ({ default: m.DelayReportsPage })))
const UsersPage = lazy(() => import('./pages/users/UsersPage').then((m) => ({ default: m.UsersPage })))
const ComplianceRecordsPage = lazy(() =>
  import('./pages/compliance/ComplianceRecordsPage').then((m) => ({ default: m.ComplianceRecordsPage })),
)

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<LoadingState label="Loading…" />}>{children}</Suspense>
}

/** Hides administrator pages from other roles (the API enforces this independently). */
function AdminOnly({ children }: { children: ReactNode }) {
  const { hasRole } = useAuth()
  return hasRole() ? <>{children}</> : <NotFoundPage forbidden />
}

function ModuleRoute({ item }: { item: NavItem }) {
  const { hasRole } = useAuth()
  if (item.roles && !hasRole(...item.roles)) return <NotFoundPage forbidden />
  return <PlannedModulePage item={item} />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/welcome" element={<WelcomePage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/maintenance/login" element={<MaintenanceLoginPage />} />

      {/* Maintenance Operations: its own session; the API refuses logistics sessions here. */}
      <Route
        path="/maintenance"
        element={
          <RequireAuth workspace="maintenance">
            <AppLayout workspace="maintenance" />
          </RequireAuth>
        }
      >
        {ALL_MAINTENANCE_ITEMS.filter((i) => i.planned).map((item) =>
          item.to === '/maintenance' ? (
            <Route key={item.to} index element={<ModuleRoute item={item} />} />
          ) : (
            <Route key={item.to} path={item.to.slice('/maintenance/'.length)} element={<ModuleRoute item={item} />} />
          ),
        )}
        <Route path="*" element={<NotFoundPage />} />
      </Route>

      {/* Logistics Operations */}
      <Route
        element={
          <RequireAuth workspace="logistics">
            <AppLayout workspace="logistics" />
          </RequireAuth>
        }
      >
        <Route index element={<Lazy><OverviewPage /></Lazy>} />
        <Route path="fleet" element={<Lazy><FleetPage /></Lazy>} />
        <Route path="loading-bays" element={<Lazy><LoadingBaysPage /></Lazy>} />
        <Route path="dispatch" element={<Lazy><DispatchPage /></Lazy>} />
        <Route path="compliance" element={<Lazy><ComplianceRecordsPage /></Lazy>} />
        <Route path="delays" element={<Lazy><DelayReportsPage /></Lazy>} />
        <Route path="alerts" element={<Lazy><AlertsPage /></Lazy>} />
        <Route path="reports" element={<Lazy><ReportsPage /></Lazy>} />
        <Route path="turnaround" element={<Lazy><TurnaroundAnalyticsPage /></Lazy>} />
        <Route path="users" element={<AdminOnly><Lazy><UsersPage /></Lazy></AdminOnly>} />
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
