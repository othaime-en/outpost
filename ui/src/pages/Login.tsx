/**
 * Not wrapped in ProtectedRoute (it's the one route an unauthenticated
 * visitor needs to reach), so it handles the bootstrap silent-refresh
 * state itself: shows nothing conclusive while isInitializing, then
 * redirects to "/" if that refresh actually found a valid session
 * (someone hit /login directly while already logged in — e.g. via
 * back/forward navigation) rather than flashing the GitHub button first.
 */
import { Navigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function Login() {
  const { isAuthenticated, isInitializing } = useAuth()
  const apiUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

  if (isInitializing) {
    return <div className="min-h-screen bg-white dark:bg-gray-950" />
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950 flex items-center justify-center">
      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-8 w-96 text-center shadow-sm dark:shadow-none">
        <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.2em] text-cyan-600 dark:text-cyan-500">
          Self-Service Platform
        </p>
        <h1 className="font-display text-3xl font-semibold tracking-tight text-gray-900 dark:text-white mb-2">
          IDP Lite
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mb-8 text-sm">Provision cloud environments on demand</p>
        {/*
          This anchor tag is intentional — it's a full page navigation, not a React Router link.
          We're leaving the browser to go to the FastAPI GitHub OAuth redirect endpoint.
          The API then redirects to GitHub, which then redirects back here via /callback
          (see pages/AuthCallback.tsx) once login succeeds.
        */}
        <a
          href={`${apiUrl}/auth/github`}
          className="flex items-center justify-center gap-3 bg-gray-900 text-white dark:bg-white dark:text-gray-900
                     font-semibold px-6 py-3 rounded-lg hover:bg-gray-700 dark:hover:bg-gray-100 transition-colors"
        >
          {/* GitHub SVG icon */}
          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path
              fillRule="evenodd"
              d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
              clipRule="evenodd"
            />
          </svg>
          Login with GitHub
        </a>
      </div>
    </div>
  )
}