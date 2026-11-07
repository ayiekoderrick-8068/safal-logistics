import { ArrowRight, Cog, Truck, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router'
import fleetJpg from '../assets/login/fleet-highway.jpg'
import fleet480 from '../assets/login/fleet-highway-480.webp'
import fleet736 from '../assets/login/fleet-highway-736.webp'
import controlRoomJpg from '../assets/login/maintenance-control-room.jpg'
import controlRoom480 from '../assets/login/maintenance-control-room-480.webp'
import controlRoom736 from '../assets/login/maintenance-control-room-736.webp'
import { useAuth, WORKSPACE_HOME, WORKSPACE_LOGIN } from '../auth/context'
import { Logo } from '../components/brand/Logo'
import { WORKSPACE_LABELS } from '../lib/format'
import type { Workspace } from '../lib/types'

const YEAR = new Date().getFullYear()

interface Photo {
  jpg: string
  webp480: string
  webp736: string
  width: number
  height: number
}
const FLEET: Photo = { jpg: fleetJpg, webp480: fleet480, webp736: fleet736, width: 736, height: 1051 }
const CONTROL_ROOM: Photo = { jpg: controlRoomJpg, webp480: controlRoom480, webp736: controlRoom736, width: 736, height: 1307 }

const WORKSPACES: {
  id: Workspace
  icon: LucideIcon
  summary: string
  modules: string[]
  photo: Photo
  /** Crop of the portrait photo inside the wide card banner. */
  bannerPosition: string
}[] = [
  {
    id: 'logistics',
    icon: Truck,
    summary: 'Fleet, loading bays, dispatch, compliance and turnaround analytics.',
    modules: ['Fleet', 'Loading bays', 'Dispatch', 'Reports'],
    photo: FLEET,
    bannerPosition: 'object-[center_58%]',
  },
  {
    id: 'maintenance',
    icon: Cog,
    summary: 'Equipment register, preventive maintenance, work orders and breakdowns.',
    modules: ['Equipment', 'Work orders', 'Spare parts', 'Reports'],
    photo: CONTROL_ROOM,
    bannerPosition: 'object-[center_40%]',
  },
]

function Picture({ photo, sizes, className, eager = false }: { photo: Photo; sizes: string; className: string; eager?: boolean }) {
  return (
    <picture>
      <source type="image/webp" srcSet={`${photo.webp480} 480w, ${photo.webp736} 736w`} sizes={sizes} />
      <img src={photo.jpg} width={photo.width} height={photo.height} alt="" decoding="async"
        loading={eager ? 'eager' : 'lazy'} className={className} />
    </picture>
  )
}

/**
 * Public entry point: pick a workspace, then sign in to it. Each workspace has its own
 * sign-in and its own session; moving between them always asks for the password again.
 */
export function WelcomePage() {
  const { status, workspace } = useAuth()

  return (
    <div className="relative isolate flex min-h-screen flex-col overflow-hidden bg-sidebar-deep text-white">
      {/* Background: the fleet on the left, the plant on the right, meeting in dark teal. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        {/* Left photo is wider than its half and shifted left, so the lead truck sits near the
            edge instead of under the dark centre. */}
        <Picture photo={FLEET} sizes="60vw" eager
          className="absolute inset-y-0 -left-[12%] h-full w-[62%] object-cover object-[center_62%]" />
        <Picture photo={CONTROL_ROOM} sizes="50vw" eager
          className="absolute inset-y-0 right-0 h-full w-1/2 object-cover object-[center_30%]" />
        {/* Teal tint, then darker behind the title and cards (centre) and towards the bottom. */}
        <div className="absolute inset-0 bg-sidebar/45 mix-blend-multiply" />
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(to right, rgb(8 39 54 / 0.2) 0%, rgb(8 39 54 / 0.35) 25%, rgb(8 39 54 / 0.9) 45%, rgb(8 39 54 / 0.9) 55%, rgb(8 39 54 / 0.35) 75%, rgb(8 39 54 / 0.2) 100%)',
          }}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-sidebar-deep/55 via-transparent via-40% to-sidebar-deep/95" />
      </div>

      <header className="flex items-center px-3.5 pt-3.5 sm:px-4 sm:pt-4 lg:px-5 lg:pt-5">
        <Logo variant="full" surface="dark" className="h-12 lg:h-16" />
      </header>

      <main className="flex flex-1 flex-col items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-5xl">
          <h1 className="text-center text-3xl font-bold drop-shadow sm:text-5xl">Choose your workspace</h1>
          <p className="mx-auto mt-3 max-w-xl text-center text-white/85 sm:text-lg">
            Each workspace has its own sign-in. Switching between them always asks for your password.
          </p>

          <ul className="mt-8 grid gap-5 sm:mt-12 md:grid-cols-2 md:gap-7">
            {WORKSPACES.map(({ id, icon: Icon, summary, modules, photo, bannerPosition }) => {
              const here = status === 'authenticated' && workspace === id
              return (
                <li key={id}>
                  <Link
                    to={here ? WORKSPACE_HOME[id] : WORKSPACE_LOGIN[id]}
                    className="group relative flex h-full flex-col overflow-hidden rounded-3xl border border-cyan-300/30 bg-[linear-gradient(155deg,rgb(20_84_102/0.72),rgb(8_39_54/0.88)_60%)] text-white shadow-2xl shadow-black/40 ring-cyan-300/70 backdrop-blur-md transition hover:-translate-y-0.5 hover:border-cyan-300/55 focus-visible:ring-4 focus-visible:outline-none"
                  >
                    {/* Glass sheen across the top-left, behind everything. */}
                    <span aria-hidden className="absolute inset-0 bg-[linear-gradient(115deg,rgb(255_255_255/0.08),transparent_45%)]" />

                    {/* Photo banner, diagonal left edge, fading into the glass at its foot. */}
                    <span aria-hidden className="absolute top-0 right-0 h-32 w-[70%] overflow-hidden rounded-tr-3xl sm:h-36 sm:w-[64%] [clip-path:polygon(24%_0,100%_0,100%_100%,0_100%)]">
                      <Picture photo={photo} sizes="(min-width: 768px) 30vw, 70vw"
                        className={`absolute inset-0 size-full object-cover ${bannerPosition} transition duration-500 group-hover:scale-[1.03]`} />
                      <span className="absolute inset-0 bg-gradient-to-t from-[rgb(12_52_68/0.55)] via-transparent to-transparent" />
                    </span>

                    {/* Soft wave of light in the lower-right corner. */}
                    <svg aria-hidden viewBox="0 0 400 160" preserveAspectRatio="none"
                      className="pointer-events-none absolute right-0 bottom-0 h-28 w-3/4 text-cyan-300 sm:h-32">
                      <defs>
                        <linearGradient id={`wave-${id}`} x1="0" y1="0" x2="1" y2="1">
                          <stop offset="0" stopColor="currentColor" stopOpacity="0" />
                          <stop offset="1" stopColor="currentColor" stopOpacity="0.14" />
                        </linearGradient>
                      </defs>
                      <path d="M0 160 C 120 150, 210 120, 290 70 S 380 10, 400 0 L 400 160 Z" fill={`url(#wave-${id})`} />
                      <path d="M40 160 C 150 145, 230 112, 300 66 S 385 8, 400 2" fill="none" stroke="currentColor" strokeOpacity="0.28" strokeWidth="1.5" />
                    </svg>

                    {/* Same height as the banner, so the title always starts below the photo. */}
                    <span className="relative block h-32 px-6 pt-6 sm:h-36 sm:px-8 sm:pt-8">
                      <span className="grid size-14 place-items-center rounded-2xl border border-cyan-300/45 bg-white/5 text-cyan-300 shadow-[0_0_24px_rgb(34_211_238/0.18)] backdrop-blur sm:size-16">
                        <Icon className="size-7 sm:size-8" aria-hidden />
                      </span>
                    </span>
                    <span className="relative flex flex-1 flex-col px-6 pt-5 pb-6 sm:px-8 sm:pt-6 sm:pb-8">
                      <h2 className="text-xl font-bold sm:text-2xl">{WORKSPACE_LABELS[id]}</h2>
                      <p className="mt-1.5 text-sm text-white/80 sm:text-base">{summary}</p>
                      {/* The separator follows its word, so a wrapped line never starts with "·". */}
                      <ul aria-label="Modules" className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs font-bold tracking-[0.03em] text-cyan-300 uppercase sm:text-[0.8125rem]">
                        {modules.map((m, i) => (
                          <li key={m} className="flex items-center gap-1.5 whitespace-nowrap">
                            {m}
                            {i < modules.length - 1 && <span aria-hidden className="text-cyan-300/60">·</span>}
                          </li>
                        ))}
                      </ul>
                      <span className="mt-auto block pt-6 sm:pt-7">
                        <span className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-cyan-200 to-cyan-400 px-6 py-2.5 text-base font-bold text-sidebar-deep shadow-lg shadow-cyan-500/25 transition group-hover:brightness-110 sm:text-lg">
                          {here ? 'Continue' : 'Sign in'}
                          <ArrowRight className="size-5 transition group-hover:translate-x-1" aria-hidden />
                        </span>
                      </span>
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      </main>

      <footer className="px-5 pb-5 text-center text-xs text-white/70">© {YEAR} LogiTrack · Operations Portal</footer>
    </div>
  )
}
