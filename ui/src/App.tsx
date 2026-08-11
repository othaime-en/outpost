import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './hooks/useAuth'
import ProtectedRoute from './components/ProtectedRoute'
import AppShell from './components/AppShell'
import AuthCallback from './pages/AuthCallback'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import Dashboard from './pages/Dashboard'
import NewEnvironment from './pages/NewEnvironment'
import EnvironmentDetail from './pages/EnvironmentDetail'
import AuditLog from './pages/AuditLog'
import Settings from './pages/Settings'
import Teams from './pages/Teams'
import TeamDetail from './pages/TeamDetail'

/** Shorthand for "protected route, rendered inside the app shell's nav/header". */
function Protected({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  )
}

export default function App() {
  return (
    /*
     * AuthProvider wraps everything so any component can call useAuth() to get
     * the current user without needing to pass it down through props.
     */
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              <Protected>
                <Dashboard />
              </Protected>
            }
          />
          <Route
            path="/new"
            element={
              <Protected>
                <NewEnvironment />
              </Protected>
            }
          />
          <Route
            path="/environments/:id"
            element={
              <Protected>
                <EnvironmentDetail />
              </Protected>
            }
          />
          <Route
            path="/teams"
            element={
              <Protected>
                <Teams />
              </Protected>
            }
          />
          <Route
            path="/teams/:id"
            element={
              <Protected>
                <TeamDetail />
              </Protected>
            }
          />
          <Route
            path="/audit"
            element={
              <Protected>
                <AuditLog />
              </Protected>
            }
          />
          <Route
            path="/settings"
            element={
              <Protected>
                <Settings />
              </Protected>
            }
          />
          <Route path="/login" element={<Login />} />
          <Route path="/callback" element={<AuthCallback />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}