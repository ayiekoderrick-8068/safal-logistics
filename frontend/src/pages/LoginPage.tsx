import { zodResolver } from '@hookform/resolvers/zod'
import { BarChart3, Eye, EyeOff, LoaderCircle, ShieldCheck, Timer, Truck } from 'lucide-react'
import { useState } from 'react'
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
  { icon: Timer, text: 'Turnaround times calculated from recorded loading timestamps' },
  { icon: Truck, text: 'Fleet, loading bays and dispatch in one workflow' },
  { icon: ShieldCheck, text: 'Role-based access with a full audit trail' },
]

export function LoginPage() {
  const { login, status } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const [serverError, setServerError] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { username: '', password: '' } })

  if (status === 'authenticated') return <Navigate to={from} replace />

  const onSubmit = handleSubmit(async ({ username, password }) => {
    setServerError(null)
    try {
      await login(username, password)
      navigate(from, { replace: true })
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Sign-in failed. Please try again.')
    }
  })

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <section className="sidebar-gradient relative hidden flex-col justify-between overflow-hidden p-12 text-white lg:flex">
        <div className="flex items-center gap-3">
          <span className="grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-cyan-300 to-accent text-sidebar shadow-lg">
            <Truck className="size-8" strokeWidth={2.2} aria-hidden />
          </span>
          <div>
            <p className="text-2xl font-bold">LogiTrack</p>
            <p className="text-white/80">Operations Portal</p>
          </div>
        </div>
        <div className="max-w-lg">
          <h1 className="text-4xl leading-tight font-bold">
            Faster loading. Reliable dispatch. Measurable turnaround.
          </h1>
          <ul className="mt-8 space-y-4">
            {HIGHLIGHTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-white/90">
                <span className="grid size-10 place-items-center rounded-xl bg-white/10 text-cyan-200">
                  <Icon className="size-5" aria-hidden />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="flex items-center gap-2 text-sm text-white/60">
          <BarChart3 className="size-4" aria-hidden /> Logistics Operations
        </p>
        <div className="pointer-events-none absolute -right-32 -bottom-32 size-96 rounded-full bg-accent/20 blur-3xl" />
      </section>

      <section className="workspace-gradient flex items-center justify-center p-6">
        <div className="card w-full max-w-md p-8">
          <div className="mb-6 flex items-center gap-3 lg:hidden">
            <span className="grid size-11 place-items-center rounded-xl bg-accent text-sidebar">
              <Truck className="size-6" aria-hidden />
            </span>
            <p className="text-xl font-bold text-ink">LogiTrack</p>
          </div>
          <h2 className="text-2xl font-bold text-ink">Sign in</h2>
          <p className="mt-1 text-sm text-ink-muted">Use the account your administrator created for you.</p>

          {serverError && (
            <div role="alert" className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {serverError}
            </div>
          )}

          <form onSubmit={onSubmit} noValidate className="mt-6 space-y-5">
            <div>
              <label htmlFor="username" className="mb-1.5 block text-sm font-semibold text-ink">
                Username or email
              </label>
              <input
                id="username"
                autoComplete="username"
                autoFocus
                aria-invalid={!!errors.username}
                aria-describedby={errors.username ? 'username-error' : undefined}
                {...register('username')}
                className="h-11 w-full rounded-xl border border-slate-300 px-3.5 text-ink focus:border-accent focus:ring-2 focus:ring-accent/30 focus:outline-none aria-invalid:border-red-400"
              />
              {errors.username && (
                <p id="username-error" className="mt-1 text-sm text-red-600">{errors.username.message}</p>
              )}
            </div>

            <div>
              <label htmlFor="password" className="mb-1.5 block text-sm font-semibold text-ink">Password</label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  aria-invalid={!!errors.password}
                  aria-describedby={errors.password ? 'password-error' : undefined}
                  {...register('password')}
                  className="h-11 w-full rounded-xl border border-slate-300 pr-11 pl-3.5 text-ink focus:border-accent focus:ring-2 focus:ring-accent/30 focus:outline-none aria-invalid:border-red-400"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  className="absolute inset-y-0 right-0 grid w-11 place-items-center text-ink-muted hover:text-ink"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                >
                  {showPassword ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
                </button>
              </div>
              {errors.password && (
                <p id="password-error" className="mt-1 text-sm text-red-600">{errors.password.message}</p>
              )}
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary font-semibold text-white shadow-md hover:bg-primary-hover disabled:opacity-70"
            >
              {isSubmitting && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
      </section>
    </div>
  )
}
