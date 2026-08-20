import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'idplite-theme'

interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  // No stored preference yet — default to dark. This matches the app's
  // existing visual identity (every page was designed dark-first), rather
  // than deferring to the OS's prefers-color-scheme, which could silently
  // flip first-time visitors into an unpolished light mode.
  return 'dark'
}

interface ThemeProviderProps {
  children: ReactNode
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [theme, setTheme] = useState<Theme>(readInitialTheme)

  // Keep the `dark` class on <html> in sync with state — this is what
  // Tailwind's `darkMode: 'class'` strategy actually reads.
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    window.localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  function toggleTheme() {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))
  }

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (ctx === undefined) {
    throw new Error('useTheme() must be called inside a <ThemeProvider>. Check that App.tsx wraps everything in <ThemeProvider>.')
  }
  return ctx
}