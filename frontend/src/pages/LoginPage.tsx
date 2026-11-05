import { zodResolver } from '@hookform/resolvers/zod'
import {
  BarChart3,
  CircleAlert,
  Clock,
  Eye,
  EyeOff,
  LoaderCircle,
  LockKeyhole,
  ShieldCheck,
  Timer,
  Truck,
  TriangleAlert,
  Warehouse,
} from 'lucide-react'
import { useEffect, useState, type KeyboardEvent } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { z } from 'zod'
import { useAuth } from '../auth/context'
import { ApiError } from '../lib/api'

const schema = z.object({
  username: z.string().trim().min(1, 'Enter your username or email'),
  password: z.string().min(1, 'Enter your password'),
})
type FormValues = z.infer<typeof schema>

const HIGHLIGHTS = [
  { icon: Warehouse, title: 'Loading bays', text: 'Book bays and record every loading step' },
  { icon: Timer, title: 'Turnaround', text: 'Measured from recorded arrival and departure' },
  { icon: ShieldCheck, title: 'Compliance', text: 'Expired documents block dispatch automatically' },
  { icon: BarChart3, title: 'Reports', text: 'Filter, analyse and export CSV, Excel and PDF' },
]

const YEAR = new Date().getFullYear()
const clock = () => Date.now()

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/** Decorative route illustration (no data). */
function RouteArt() {
  return (
    <svg viewBox="0 0 520 180" className="w-full max-w-xl text-cyan-200/70" aria-hidden>
      <path d="M10 150 C120 150 140 60 260 60 S420 140 510 40" fill="none" stroke="currentColor" strokeWidth="3"
        strokeDasharray="10 10" strokeLinecap="round" />
      <circle cx="10" cy="150" r="9" className="fill-cyan-300" />
      <circle cx="510" cy="40" r="9" className="fill-emerald-300" />
      <g transform="translate(218 22)" className="text-white">
        <rect x="0" y="10" width="58" height="34" rx="5" className="fill-white/90" />
        <path d="M58 20 h18 l12 12 v12 h-30z" className="fill-cyan-300" />
        <circle cx="16" cy="48" r="7" className="fill-sidebar stroke-white" strokeWidth="3" />
        <circle cx="70" cy="48" r="7" className="fill-sidebar stroke-white" strokeWidth="3" />
      </g>
    </svg>
  )
}

export function LoginPage() {
  const { login, status, sessionExpired } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const [serverError, setServerError] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const [capsLock, setCapsLock] = useState(false)
  const [lockedUntil, setLockedUntil] = useState<number | null>(null)
  const [now, setNow] = useState(clock)

  useEffect(() => {
    if (lockedUntil === null) return
    const id = window.setInterval(() => {
      const t = clock()
      setNow(t)
      if (t >= lockedUntil) {
        setLockedUntil(null)
        setServerError(null)
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [lockedUntil])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { username: '', password: '' } })

  if (status === 'authenticated') return <Navigate to={from} replace />

  const remaining = lockedUntil ? Math.max(0, Math.ceil((lockedUntil - now) / 1000)) : 0
  const locked = remaining > 0

  const onSubmit = handleSubmit(async ({ username, password }) => {
    setServerError(null)
    try {
      await login(username, password)
      navigate(from, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        const t = clock()
        setNow(t)
        setLockedUntil(t + (err.retryAfter ?? 900) * 1000)
        setServerError(err.message)
      } else if (err instanceof ApiError && err.status === 401) {
        setServerError('The username or password is incorrect.')
      } else {
        setServerError(err instanceof ApiError ? err.message : 'Sign-in failed. Please try again.')
      }
    }
  })

  const onPasswordKey = (e: KeyboardEvent<HTMLInputElement>) => setCapsLock(e.getModifierState?.('CapsLock') ?? false)
  const field =
    'h-12 w-full rounded-xl border border-slate-300 bg-white px-4 text-ink shadow-sm transition focus:border-accent focus:ring-4 focus:ring-accent/20 focus:outline-none aria-invalid:border-red-400 aria-invalid:ring-red-100 disabled:bg-slate-50'

  return (
    <div className="grid min-h-screen bg-sidebar-deep lg:grid-cols-[1.1fr_1fr]">
      {/* Brand panel */}
      <section className="sidebar-gradient relative hidden flex-col overflow-hidden px-12 py-10 text-white lg:flex xl:px-16">
        <div className="pointer-events-none absolute -top-40 -right-40 size-[28rem] rounded-full bg-accent/15 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-24 size-96 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <span className="grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-cyan-300 to-accent text-sidebar shadow-lg shadow-cyan-500/20">
            <Truck className="size-8" strokeWidth={2.2} aria-hidden />
          </span>
          <div>
            <p className="text-2xl leading-tight font-bold">LogiTrack</p>
            <p className="text-white/75">Operations Portal</p>
          </div>
        </div>

        <div className="relative my-auto max-w-xl py-10">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-semibold tracking-wide text-cyan-200 uppercase">
            Logistics operations
          </p>
          <h1 className="text-4xl leading-tight font-bold xl:text-5xl">
            Faster loading.<br />Reliable dispatch.<br /><span className="text-cyan-300">Measurable turnaround.</span>
          </h1>
          <div className="mt-8"><RouteArt /></div>
          <ul className="mt-8 grid grid-cols-2 gap-3">
            {HIGHLIGHTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="rounded-2xl border border-white/10 bg-white/[0.06] p-4 backdrop-blur-sm">
                <Icon className="mb-2 size-5 text-cyan-300" aria-hidden />
                <p className="font-semibold">{title}</p>
                <p className="text-sm text-white/70">{text}</p>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/50">© {YEAR} LogiTrack · Logistics Operations</p>
      </section>

      {/* Sign-in panel */}
      <section className="workspace-gradient flex items-center justify-center px-5 py-10 lg:rounded-l-[32px]">
        <div className="w-full max-w-md">
          <div className="mb-6 flex items-center gap-3 lg:hidden">
            <span className="grid size-12 place-items-center rounded-xl bg-gradient-to-br from-cyan-300 to-accent text-sidebar">
              <Truck className="size-7" aria-hidden />
            </span>
            <div>
              <p className="text-xl leading-tight font-bold text-ink">LogiTrack</p>
              <p className="text-sm text-ink-muted">Operations Portal</p>
            </div>
          </div>

          <div className="card p-8 sm:p-10">
            <span className="mb-4 grid size-12 place-items-center rounded-2xl bg-sky-100 text-primary">
              <LockKeyhole className="size-6" aria-hidden />
            </span>
            <h2 className="text-2xl font-bold text-ink">Sign in</h2>
            <p className="mt-1 text-sm text-ink-muted">Use the account your administrator created for you.</p>

            {sessionExpired && !serverError && (
              <div role="status" className="mt-5 flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
                <Clock className="mt-0.5 size-5 shrink-0 text-sky-600" aria-hidden />
                <p><strong className="font-semibold">Your session has expired.</strong> Sign in again to continue where you left off.</p>
              </div>
            )}

            {serverError && (
              <div role="alert" className={`mt-5 flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${locked
                ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-red-200 bg-red-50 text-red-700'}`}>
                {locked ? <TriangleAlert className="mt-0.5 size-5 shrink-0 text-amber-600" aria-hidden />
                  : <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />}
                <div>
                  <p>{serverError}</p>
                  {locked && (
                    <p className="mt-1 font-semibold" aria-live="off">
                      You can try again in <span data-testid="lockout-countdown">{formatCountdown(remaining)}</span>.
                    </p>
                  )}
                </div>
              </div>
            )}

            <form onSubmit={onSubmit} noValidate className="mt-6 space-y-5" aria-busy={isSubmitting}>
              <div>
                <label htmlFor="username" className="mb-1.5 block text-sm font-semibold text-ink">Username or email</label>
                <input
                  id="username"
                  autoComplete="username"
                  autoFocus
                  autoCapitalize="none"
                  spellCheck={false}
                  disabled={isSubmitting}
                  aria-invalid={!!errors.username}
                  aria-describedby={errors.username ? 'username-error' : undefined}
                  {...register('username')}
                  className={field}
                />
                {errors.username && <p id="username-error" className="mt-1 text-sm text-red-600">{errors.username.message}</p>}
              </div>

              <div>
                <label htmlFor="password" className="mb-1.5 block text-sm font-semibold text-ink">Password</label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    disabled={isSubmitting}
                    aria-invalid={!!errors.password}
                    aria-describedby={[errors.password && 'password-error', capsLock && 'caps-warning'].filter(Boolean).join(' ') || undefined}
                    onKeyUp={onPasswordKey}
                    {...register('password')}
                    className={`${field} pr-12`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((s) => !s)}
                    className="absolute inset-y-0 right-0 grid w-12 place-items-center text-ink-muted hover:text-ink"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    aria-pressed={showPassword}
                  >
                    {showPassword ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
                  </button>
                </div>
                {errors.password && <p id="password-error" className="mt-1 text-sm text-red-600">{errors.password.message}</p>}
                {capsLock && <p id="caps-warning" className="mt-1 text-sm text-amber-700">Caps Lock is on.</p>}
              </div>

              <button
                type="submit"
                disabled={isSubmitting || locked}
                className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary font-semibold text-white shadow-md shadow-primary/20 transition hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSubmitting && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
                {isSubmitting ? 'Signing in…' : locked ? 'Sign-in paused' : 'Sign in'}
              </button>
            </form>

            <p className="mt-6 border-t border-line pt-4 text-xs text-ink-muted">
              Forgotten your password or locked out? Contact your LogiTrack administrator. Sign-in attempts are monitored and
              repeated failures pause sign-in temporarily.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
