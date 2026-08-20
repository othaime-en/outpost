/**
 * Wraps a route element and redirects to /login if there's no authenticated
 * user in AuthContext. The access token still lives only in memory (never
 * localStorage) — but AuthProvider now attempts a silent refresh from an
 * httpOnly cookie on every fresh mount (see hooks/useAuth.tsx), so a hard
 * refresh no longer means an automatic bounce to /login the way it used
 * to. While that silent refresh is in flight (isInitializing), this
 * renders a brief loading state rather than redirecting — redirecting
 * first and then "un-redirecting" a moment later if the refresh succeeds
 * would be a jarring flash for anyone with a valid session.
 */
import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isInitializing } = useAuth()

  if (isInitializing) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white dark:bg-gray-950">
        <p className="text-sm text-gray-500 dark:text-gray-500">Loading…</p>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}