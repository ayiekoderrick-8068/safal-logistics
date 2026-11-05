import { ChevronDown, LogOut, Menu, Search } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { useAuth } from '../../auth/context'
import { initials, ROLE_LABELS } from '../../lib/format'
import { ALL_NAV_ITEMS } from '../../nav'
import { NotificationBell } from './NotificationBell'

export function Topbar({ onToggleNav }: { onToggleNav: () => void }) {
  const { user, logout, hasRole } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !menuRef.current?.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [menuOpen])

  // Module search: jumps to the first page whose name matches. Record search comes later.
  const pages = ALL_NAV_ITEMS.filter((i) => !i.roles || hasRole(...i.roles))
  function onSearch(e: FormEvent) {
    e.preventDefault()
    const q = query.trim().toLowerCase()
    if (!q) return
    const match = pages.find((p) => `${p.label} ${p.title}`.toLowerCase().includes(q))
    if (match) {
      navigate(match.to)
      setQuery('')
    }
  }

  return (
    <header className="topbar-gradient sticky top-0 z-20 flex h-[68px] items-center gap-3 px-4 text-white md:gap-5 md:px-6">
      <button
        type="button"
        onClick={onToggleNav}
        className="rounded-lg p-2 hover:bg-white/10"
        aria-label="Toggle navigation"
        aria-controls="app-sidebar"
      >
        <Menu className="size-6" />
      </button>

      <form role="search" onSubmit={onSearch} className="relative hidden max-w-md flex-1 sm:block">
        <label htmlFor="global-search" className="sr-only">Search modules</label>
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-white/80" aria-hidden />
        <input
          id="global-search"
          list="module-list"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search modules, e.g. dispatch…"
          className="h-10 w-full rounded-full border border-white/25 bg-white/10 pr-4 pl-10 text-sm text-white placeholder:text-white/75 focus:bg-white/15 focus:outline-none"
        />
        <datalist id="module-list">
          {pages.map((p) => (
            <option key={p.to} value={p.label} />
          ))}
        </datalist>
      </form>

      <div className="ml-auto flex items-center gap-3">
        <NotificationBell />

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className="flex items-center gap-2 rounded-full p-0.5 pr-1 hover:bg-white/10"
          >
            <span className="grid size-10 place-items-center rounded-full bg-white text-sm font-bold text-sidebar">
              {user ? initials(user.full_name) : '?'}
            </span>
            <ChevronDown className="size-5" aria-hidden />
            <span className="sr-only">Account menu</span>
          </button>
          {menuOpen && user && (
            <div
              role="menu"
              className="absolute right-0 mt-2 w-64 rounded-2xl border border-line bg-white p-2 text-ink shadow-xl"
            >
              <div className="border-b border-line px-3 pt-2 pb-3">
                <p className="font-semibold">{user.full_name}</p>
                <p className="truncate text-sm text-ink-muted">{user.email}</p>
                <p className="mt-1 text-xs font-semibold text-primary">{ROLE_LABELS[user.role]}</p>
              </div>
              <button
                type="button"
                role="menuitem"
                onClick={async () => {
                  setMenuOpen(false)
                  await logout()
                  navigate('/login', { replace: true })
                }}
                className="mt-1 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-surface-muted"
              >
                <LogOut className="size-4" aria-hidden /> Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
