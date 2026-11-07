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
  modules: string
  photo: Photo
  /** Crop of the portrait photo inside the wide card banner. */
  bannerPosition: string
}[] = [
  {
    id: 'logistics',
    icon: Truck,
    summary: 'Fleet, loading bays, dispatch, compliance and turnaround analytics.',
    modules: 'Fleet · Loading bays · Dispatch · Reports',
    photo: FLEET,
    bannerPosition: 'object-[center_58%]',
  },
  {
    id: 'maintenance',
    icon: Cog,
    summary: 'Equipment register, preventive maintenance, work orders and breakdowns.',
    modules: 'Equipment · Work orders · Spare parts · Reports',
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
                    className="group relative flex h-full flex-col overflow-hidden rounded-3xl bg-white text-ink shadow-2xl shadow-black/30 ring-accent/60 transition hover:-translate-y-0.5 focus-visible:ring-4 focus-visible:outline-none"
                  >
                    {/* Photo banner with a diagonal edge and a pale cyan stripe along it. */}
                    <span aria-hidden className="absolute top-0 right-0 h-32 w-[70%] sm:h-36 sm:w-[64%]">
                      <span className="absolute inset-0 bg-sky-100 [clip-path:polygon(18%_0,30%_0,12%_100%,0_100%)]" />
                      <Picture photo={photo} sizes="(min-width: 768px) 30vw, 70vw"
                        className={`absolute inset-0 size-full object-cover ${bannerPosition} [clip-path:polygon(30%_0,100%_0,100%_100%,12%_100%)] transition duration-500 group-hover:scale-[1.03]`} />
                    </span>

                    {/* Same height as the banner, so the title always starts below the photo. */}
                    <span className="relative block h-32 px-6 pt-6 sm:h-36 sm:px-8 sm:pt-8">
                      <span className="grid size-14 place-items-center rounded-2xl bg-sky-100 text-primary shadow-sm sm:size-16">
                        <Icon className="size-7 sm:size-8" aria-hidden />
                      </span>
                    </span>
                    <span className="relative flex flex-1 flex-col px-6 pt-5 pb-6 sm:px-8 sm:pt-6 sm:pb-8">
                      <h2 className="text-xl font-bold sm:text-2xl">{WORKSPACE_LABELS[id]}</h2>
                      <p className="mt-1.5 text-sm text-ink-muted sm:text-base">{summary}</p>
                      <p className="mt-3 text-xs font-bold tracking-wide text-primary uppercase sm:text-sm">{modules}</p>
                      <span className="mt-5 inline-flex items-center gap-2 text-lg font-bold text-primary sm:mt-auto sm:pt-5">
                        {here ? 'Continue' : 'Sign in'}
                        <ArrowRight className="size-5 transition group-hover:translate-x-1" aria-hidden />
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
