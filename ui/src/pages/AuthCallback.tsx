/**
 * Landing page for the OAuth redirect.
 *
 * The API redirects here as `${FRONTEND_URL}/callback#token=<jwt>` once
 * GitHub login succeeds (see api/app/routers/auth.py::github_callback).
 * The token lives in the URL *fragment*, which browsers never send back to
 * any server — we read it client-side, hand it to AuthContext, and
 * immediately scrub it out of the visible URL/history.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../hooks/useAuth'

export default function AuthCallback() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const hash = window.location.hash // "#token=eyJ..."
    const params = new URLSearchParams(hash.replace(/^#/, ''))
    const token = params.get('token')

    if (!token) {
      setError('No token found in the callback URL. Please try logging in again.')
      return
    }

    // Strip the token out of the visible URL right away so it doesn't
    // linger in browser history.
    window.history.replaceState(null, '', window.location.pathname)

    api.setToken(token)
    api
      .getMe()
      .then((user) => {
        login(token, user)
        navigate('/', { replace: true })
      })
      .catch(() => {
        api.setToken(null)
        setError('Could not validate your session. Please try logging in again.')
      })
  }, [login, navigate])

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950 flex items-center justify-center">
      <div className="text-center">
        {error ? (
          <>
            <p className="text-red-600 dark:text-red-400 mb-4">{error}</p>
            <a href="/login" className="text-cyan-600 dark:text-cyan-400 hover:underline text-sm">
              Back to login
            </a>
          </>
        ) : (
          <p className="text-gray-600 dark:text-gray-400">Signing you in…</p>
        )}
      </div>
    </div>
  )
}