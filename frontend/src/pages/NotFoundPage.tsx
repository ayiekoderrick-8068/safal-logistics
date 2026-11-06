import { Link } from 'react-router'
import { useAuth, WORKSPACE_HOME } from '../auth/context'
import { Card } from '../components/ui/Card'

export function NotFoundPage({ forbidden = false }: { forbidden?: boolean }) {
  const { workspace } = useAuth()
  const maintenance = workspace === 'maintenance'
  return (
    <Card className="mx-auto mt-10 max-w-lg text-center">
      <h1 className="text-2xl font-bold text-ink">{forbidden ? 'Access restricted' : 'Page not found'}</h1>
      <p className="mt-2 text-ink-muted">
        {forbidden
          ? 'Your role does not have access to this area. Contact an administrator if you need it.'
          : 'The page you are looking for does not exist.'}
      </p>
      <Link
        to={WORKSPACE_HOME[maintenance ? 'maintenance' : 'logistics']}
        className="mt-5 inline-block rounded-xl bg-primary px-5 py-2.5 font-semibold text-white hover:bg-primary-hover"
      >
        {maintenance ? 'Back to Dashboard' : 'Back to Overview'}
      </Link>
    </Card>
  )
}
