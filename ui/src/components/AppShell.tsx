import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useTheme } from '../hooks/useTheme'

const NAV_LINKS = [
  { to: '/', label: 'Dashboard' },
  { to: '/teams', label: 'Teams' },
  { to: '/new', label: 'New Environment' },
  { to: '/audit', label: 'Audit Log' },
  { to: '/settings', label: 'Settings' },
]

export default function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const location = useLocation()

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950">
      <header className="border-b border-gray-200 bg-white/95 dark:border-gray-800 dark:bg-gray-950/95 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-8">
            <Link to="/" className="font-mono text-sm font-bold text-gray-900 dark:text-white tracking-wide">
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
                        ? 'bg-gray-100 text-cyan-600 dark:bg-gray-900 dark:text-cyan-400'
                        : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100 dark:text-gray-400 dark:hover:text-white dark:hover:bg-gray-900'
                    }`}
                  >
                    {link.label}
                  </Link>
                )
              })}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <ThemeToggle />
            <span className="text-gray-600 dark:text-gray-400">
              <span className="text-gray-800 dark:text-gray-200 font-mono">{user?.username}</span>
              {/*
                MULTI-TEAM CHANGE: this used to show `(${user.role})`, a
                single flat value. That role is now team-scoped and a user
                can hold a different one on each of several teams, so
                there's no single value left to show here — the previous
                display would have been misleading ("(member)" while
                actually being team_admin elsewhere). platform_role is
                still a single global fact, so it's the one thing still
                worth surfacing in a persistent header — and only when it's
                the notable case (super_admin). Team-scoped role belongs on
                that team's own page (see TeamDetail.tsx), not here.
              */}
              {user?.platform_role === 'super_admin' && (
                <span className="ml-1.5 text-gray-400 dark:text-gray-600">(super_admin)</span>
              )}
            </span>
            <button onClick={logout} className="text-gray-500 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300 underline text-xs">
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  )
}

/**
 * Sun/moon icon toggle. Placed in the header. Icons are inline SVG to match the existing
 * pattern in Login.tsx rather than pulling in an icon library for one use.
 */
function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      onClick={toggleTheme}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900
                 dark:text-gray-400 dark:hover:bg-gray-900 dark:hover:text-white transition-colors"
    >
      {isDark ? (
        // Sun — shown when currently dark, signaling "tap to go light"
        <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path
            strokeLinecap="round"
            d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
          />
        </svg>
      ) : (
        // Moon — shown when currently light, signaling "tap to go dark"
        <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
        </svg>
      )}
    </button>
  )
}