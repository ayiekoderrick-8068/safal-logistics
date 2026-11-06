import { zodResolver } from '@hookform/resolvers/zod'
import {
  ArrowLeft,
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
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useState, useSyncExternalStore, type KeyboardEvent } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { z } from 'zod'
import fleetJpg from '../assets/login/fleet-highway.jpg'
import fleet480 from '../assets/login/fleet-highway-480.webp'
import fleet736 from '../assets/login/fleet-highway-736.webp'
import { useAuth, WORKSPACE_HOME } from '../auth/context'
import TextType from '../components/reactbits/TextType/TextType'
import { ApiError } from '../lib/api'
import { WORKSPACE_LABELS } from '../lib/format'
import type { Workspace } from '../lib/types'

const schema = z.object({
  username: z.string().trim().min(1, 'Enter your username or email'),
  password: z.string().min(1, 'Enter your password'),
})
type FormValues = z.infer<typeof schema>

interface Highlight {
  icon: LucideIcon
  title: string
  text: string
}

/** Everything that differs between the workspace sign-in pages; the form is shared. */
interface LoginConfig {
  workspace: Workspace
  label: string
  /** Typed headline phrases and their colours (same length). */
  phrases: string[]
  colors: string[]
  photo?: { jpg: string; webp480: string; webp736: string; width: number; height: number; position: string }
  /** Hero height below the desktop breakpoint (the photo needs more room than plain teal). */
  heroHeight: string
  highlights?: Highlight[]
}

const LOGISTICS_LOGIN: LoginConfig = {
  workspace: 'logistics',
  label: 'Logistics operations',
  phrases: ['Faster loading.', 'Reliable dispatch.', 'Measurable turnaround.'],
  // White, white, cyan-300: the same colour mapping as the original static headline.
  colors: ['#ffffff', '#ffffff', '#67e8f9'],
  photo: {
    jpg: fleetJpg,
    webp480: fleet480,
    webp736: fleet736,
    width: 736,
    height: 1051,
    position: 'object-[center_34%] sm:object-[center_40%] lg:object-[center_80%]',
  },
  heroHeight: 'h-80 sm:h-[27rem]',
  highlights: [
    { icon: Warehouse, title: 'Loading bays', text: 'Book bays and record every loading step' },
    { icon: Timer, title: 'Turnaround', text: 'Measured from recorded arrival and departure' },
    { icon: ShieldCheck, title: 'Compliance', text: 'Expired documents block dispatch automatically' },
    { icon: BarChart3, title: 'Reports', text: 'Filter, analyse and export CSV, Excel and PDF' },
  ],
}

/** Option C: minimal. Photo to be supplied; until then a plain dark-teal hero, no cards. */
const MAINTENANCE_LOGIN: LoginConfig = {
  workspace: 'maintenance',
  label: 'Maintenance operations',
  phrases: ['Reliable equipment.', 'Preventive maintenance.', 'Measurable uptime.'],
  colors: ['#ffffff', '#ffffff', '#67e8f9'],
  heroHeight: 'h-56 sm:h-72',
}

const YEAR = new Date().getFullYear()
const clock = () => Date.now()

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'
function subscribeReducedMotion(onChange: () => void) {
  if (typeof window.matchMedia !== 'function') return () => {}
  const query = window.matchMedia(REDUCED_MOTION)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}
// Without matchMedia (e.g. jsdom) we can't know the preference, so fall back to the static headline.
const prefersReducedMotion = () => typeof window.matchMedia !== 'function' || window.matchMedia(REDUCED_MOTION).matches

/**
 * Typed headline. Its height is reserved for two lines so the cycling text never moves the
 * layout, and screen readers get all three phrases at once. Reduced-motion users see the
 * full static headline instead.
 */
function Headline({ phrases, colors }: { phrases: string[]; colors: string[] }) {
  const reduced = useSyncExternalStore(subscribeReducedMotion, prefersReducedMotion, () => true)
  const size = 'leading-tight font-bold sm:text-4xl lg:text-[2.75rem] xl:text-5xl'

  if (reduced) {
    // All phrases at once: smaller on phones so the static line doesn't cover the photo.
    return (
      <h1 className={`mt-4 text-xl lg:mt-5 ${size}`}>
        {phrases.map((p, i) => (
          <span key={p}>
            {i > 0 && ' '}
            <span className="lg:block" style={{ color: colors[i] }}>{p}</span>
          </span>
        ))}
      </h1>
    )
  }
  return (
    <h1 className={`mt-4 text-[1.65rem] lg:mt-5 ${size}`}>
      <span className="block min-h-[2.5em]">
        <TextType
          as="span"
          text={phrases}
          textColors={colors}
          typingSpeed={65}
          pauseDuration={2000}
          deletingSpeed={35}
          deleteMode="backspace"
          typeEffect="fade"
          mistakes={0}
          cursorStyle="bar"
          cursorColor="#42E6F2"
          cursorGlide
          showCursor
          loop
        />
      </span>
    </h1>
  )
}

function Brand() {
  return (
    <div className="flex items-center gap-3 px-3.5 sm:px-4 lg:px-5">
      <span className="grid size-11 place-items-center rounded-xl bg-gradient-to-br from-cyan-300 to-accent text-sidebar shadow-lg shadow-cyan-500/20 lg:size-14 lg:rounded-2xl">
        <Truck className="size-6 lg:size-8" strokeWidth={2.2} aria-hidden />
      </span>
      <div>
        <p className="text-xl leading-tight font-bold lg:text-2xl">LogiTrack</p>
        <p className="text-sm text-white/75 lg:text-base">Operations Portal</p>
      </div>
    </div>
  )
}

/** Brand hero: optional photograph under a dark-teal wash, headline above it, optional highlights. */
function Hero({ config }: { config: LoginConfig }) {
  const { photo, highlights } = config
  return (
    <section
      className={`relative isolate flex ${config.heroHeight} flex-col overflow-hidden bg-sidebar-deep pt-3.5 text-white sm:pt-4 lg:h-auto lg:pt-5 lg:pb-10 ${photo ? '' : 'sidebar-gradient'}`}
    >
      {photo && (
        <>
          <picture>
            <source type="image/webp" srcSet={`${photo.webp480} 480w, ${photo.webp736} 736w`} sizes="(min-width: 1024px) 53vw, 100vw" />
            <img
              src={photo.jpg}
              width={photo.width}
              height={photo.height}
              alt=""
              decoding="async"
              fetchPriority="high"
              className={`absolute inset-0 -z-20 size-full object-cover ${photo.position}`}
            />
          </picture>
          {/* Teal tint so the photo sits in the brand palette, then a vertical wash for text contrast. */}
          <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 bg-sidebar/25 mix-blend-multiply" />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-b from-sidebar-deep/90 via-sidebar-deep/30 via-55% to-sidebar-deep/55 lg:from-sidebar-deep/90 lg:via-sidebar-deep/15 lg:via-45% lg:to-sidebar-deep/95"
          />
        </>
      )}

      {/* Brand sits in the corner; the rest keeps the original content inset. */}
      <Brand />

      <div className="flex flex-1 flex-col px-5 sm:px-10 lg:px-12 xl:px-16">
        <div className="mt-2.5 max-w-xl sm:mt-6 lg:mt-11">
          <p className="mt-5 hidden items-center rounded-full border border-white/15 bg-sidebar-deep/40 px-3 py-1 text-xs font-semibold tracking-wide text-cyan-200 uppercase sm:inline-flex">
            {config.label}
          </p>
          <Headline phrases={config.phrases} colors={config.colors} />
        </div>

        <div className="mt-auto hidden lg:block">
          {highlights && (
            <ul className="mb-6 grid grid-cols-2 gap-3">
              {highlights.map(({ icon: Icon, title, text }) => (
                <li key={title} className="rounded-2xl border border-white/10 bg-sidebar-deep/70 px-4 py-3.5 backdrop-blur-sm">
                  <p className="flex items-center gap-2 font-semibold">
                    <Icon className="size-4.5 text-cyan-300" aria-hidden />
                    {title}
                  </p>
                  <p className="mt-1 text-sm text-white/70">{text}</p>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-white/55">© {YEAR} LogiTrack · {WORKSPACE_LABELS[config.workspace]}</p>
        </div>
      </div>
    </section>
  )
}

export function LoginPage() {
  return <WorkspaceLoginPage config={LOGISTICS_LOGIN} />
}

export function MaintenanceLoginPage() {
  return <WorkspaceLoginPage config={MAINTENANCE_LOGIN} />
}

function WorkspaceLoginPage({ config }: { config: LoginConfig }) {
  const { login, status, workspace, sessionExpired } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? WORKSPACE_HOME[config.workspace]
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

  // Already in this workspace: nothing to do. Signed in to the *other* one: show the form, a
  // full sign-in (username and password) is required to enter this workspace.
  if (status === 'authenticated' && workspace === config.workspace) return <Navigate to={from} replace />
  const otherWorkspace = status === 'authenticated' ? workspace : null

  const remaining = lockedUntil ? Math.max(0, Math.ceil((lockedUntil - now) / 1000)) : 0
  const locked = remaining > 0

  const onSubmit = handleSubmit(async ({ username, password }) => {
    setServerError(null)
    try {
      await login(username, password, config.workspace)
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
    <div className="flex min-h-screen flex-col bg-sidebar-deep lg:grid lg:grid-cols-[1.1fr_1fr]">
      <Hero config={config} />

      {/* Sign-in panel */}
      <section className="workspace-gradient relative z-10 -mt-6 flex flex-1 items-start justify-center rounded-t-[28px] px-5 pt-8 pb-8 sm:items-center lg:mt-0 lg:items-center lg:rounded-t-none lg:rounded-l-[32px] lg:py-10">
        <div className="w-full max-w-md">
          <div className="card p-7 sm:p-10">
            <span className="mb-4 grid size-12 place-items-center rounded-2xl bg-sky-100 text-primary">
              <LockKeyhole className="size-6" aria-hidden />
            </span>
            <h2 className="text-2xl font-bold text-ink">Sign in</h2>
            <p className="mt-1 text-sm text-ink-muted">
              {config.workspace === 'maintenance'
                ? 'Sign in to Maintenance Operations with your LogiTrack account.'
                : 'Use the account your administrator created for you.'}
            </p>

            {otherWorkspace && !serverError && (
              <div role="status" className="mt-5 flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
                <LockKeyhole className="mt-0.5 size-5 shrink-0 text-sky-600" aria-hidden />
                <p>
                  You are signed in to {WORKSPACE_LABELS[otherWorkspace]}. Sign in again to open{' '}
                  {WORKSPACE_LABELS[config.workspace]}.
                </p>
              </div>
            )}

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
          <p className="mt-5 text-center">
            <Link to="/welcome" className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline">
              <ArrowLeft className="size-4" aria-hidden /> Choose a different workspace
            </Link>
          </p>
        </div>
      </section>
    </div>
  )
}
