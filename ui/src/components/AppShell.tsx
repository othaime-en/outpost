import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

const NAV_LINKS = [
  { to: '/', label: 'Dashboard' },
  { to: '/new', label: 'New Environment' },
  { to: '/audit', label: 'Audit Log' },
  { to: '/settings', label: 'Settings' },
]

/**
 * Not called out as its own component in Section 6 of the plan, but Phase 6
 * introduces five routed pages (Dashboard, New Environment, Detail, Audit
 * Log, Settings) with no shared chrome between them — without this, every
 * page would need to reinvent navigation. Flagging as an addition rather
 * than silently introducing it.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const location = useLocation()

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="border-b border-gray-800 bg-gray-950/95 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-8">
            <Link to="/" className="font-mono text-sm font-bold text-white tracking-wide">
              IDP&nbsp;Lite
            </Link>
            <nav className="flex items-center gap-1">
              {NAV_LINKS.map((link) => {
                const active =
                  link.to === '/' ? location.pathname === '/' : location.pathname.startsWith(link.to)
                return (
                  <Link
                    key={link.to}
                    to={link.to}
                    className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                      active
                        ? 'bg-gray-900 text-cyan-400'
                        : 'text-gray-400 hover:text-white hover:bg-gray-900'
                    }`}
                  >
                    {link.label}
                  </Link>
                )
              })}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-gray-400">
              <span className="text-gray-200 font-mono">{user?.username}</span>{' '}
              <span className="text-gray-600">({user?.role})</span>
            </span>
            <button onClick={logout} className="text-gray-500 hover:text-gray-300 underline text-xs">
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  )
}