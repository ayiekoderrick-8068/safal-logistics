import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { AuthProvider } from './auth/AuthContext'
import { useAuth } from './auth/context'
import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './components/layout/AppLayout'
import { LoadingState } from './components/ui/States'
import { ALL_NAV_ITEMS, type NavItem } from './nav'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { PlannedModulePage } from './pages/PlannedModulePage'

// Charting code is heavy: load it only once the user reaches a dashboard.
const OverviewPage = lazy(() =>
  import('./pages/overview/OverviewPage').then((m) => ({ default: m.OverviewPage })),
)

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
        <Route
          index
          element={
            <Suspense fallback={<LoadingState label="Loading dashboard…" />}>
              <OverviewPage />
            </Suspense>
          }
        />
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
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
