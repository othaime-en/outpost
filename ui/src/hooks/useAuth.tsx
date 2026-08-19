import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, type User } from '../api/client'

// Re-exported for convenience so other files can `import { User } from
// '../hooks/useAuth'` without also reaching into api/client. The type
// itself now lives in api/client.ts (Phase 1 change) so the API client and
// AuthContext never disagree about the User shape.
export type { User }

interface AuthContextValue {
    user: User | null
    token: string | null
    isAuthenticated: boolean
    // True only during the very first render, while AuthProvider is
    // attempting a silent refresh from the httpOnly cookie. Consumers
    // (ProtectedRoute) must wait for this to go false before deciding
    // whether to redirect to /login — otherwise a returning visitor with
    // a perfectly good refresh cookie would flash through the login page
    // on every hard refresh, since isAuthenticated starts out false.
    isInitializing: boolean
    login: (token: string, user: User) => void
    logout: () => Promise<void>
}

// Create the context with undefined as the initial value.
// This is intentional — if a component calls useAuth() outside of AuthProvider,
// they'll get an error rather than silently getting null/undefined values.
const AuthContext = createContext<AuthContextValue | undefined>(undefined)

interface AuthProviderProps {
    children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
    // Both pieces of auth state are stored together.
    // When we have a token, we have a user; when we don't, we have neither.
    const [user, setUser] = useState<User | null>(null)
    const [token, setToken] = useState<string | null>(null)
    const [isInitializing, setIsInitializing] = useState(true)

    function login(newToken: string, newUser: User) {
        api.setToken(newToken)
        setToken(newToken)
        setUser(newUser)
    }

    // Clears LOCAL state only — does not talk to the server. Used both by
    // logout() below (after the server call) and by the API client's
    // onUnauthorized callback, which fires when a background
    // refresh-and-retry ultimately fails (session genuinely over) and
    // there's no point attempting a server round-trip for a session the
    // server has already discarded.
    function clearLocalSession() {
        api.setToken(null)
        setToken(null)
        setUser(null)
    }

    async function logout() {
        try {
            await api.logout()
        } catch {
            // Best-effort — the local session must still end even if this
            // fails (e.g. offline). Worst case, the httpOnly cookie simply
            // expires naturally after refresh_token_ttl_days, or gets
            // rejected on its next actual use if this call reached the
            // server despite the client-side error.
        }
        clearLocalSession()
    }

    useEffect(() => {
        // AuthCallback.tsx (the GitHub OAuth redirect target) already
        // establishes the session from the URL fragment token immediately
        // after login — the refresh cookie it just received is brand new,
        // so there's nothing for a silent refresh to add here, and racing
        // the two would just rotate that fresh cookie a second time for
        // no benefit (see api/app/services/refresh_tokens.py — rotation
        // isn't harmful, just pointless in this specific case).
        if (window.location.pathname === '/callback') {
            setIsInitializing(false)
            return
        }

        api.setUnauthorizedHandler(clearLocalSession)

        api
            .refresh()
            .then(() => api.getMe())
            .then((freshUser) => {
                setToken(api.getToken())
                setUser(freshUser)
            })
            .catch(() => {
                // No valid refresh cookie — never logged in, or the
                // session expired/was revoked. Not an error; it just
                // means the login page is what renders next.
            })
            .finally(() => setIsInitializing(false))

        return () => api.setUnauthorizedHandler(null)
    }, [])

    const value: AuthContextValue = {
        user,
        token,
        isAuthenticated: user !== null,
        isInitializing,
        login,
        logout,
    }

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
    const ctx = useContext(AuthContext)
    if (ctx === undefined) {
        throw new Error('useAuth() must be called inside an <AuthProvider>. Check that App.tsx wraps everything in <AuthProvider>.')
    }
    return ctx
}