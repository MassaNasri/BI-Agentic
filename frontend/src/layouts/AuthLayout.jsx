import { Outlet, Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/auth'

function AuthLayout() {
  const { isAuthenticated } = useAuthStore()
  const location = useLocation()

  // Redirect to dashboard if already authenticated
  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />
  }

  const fullBleedAuthRoutes = new Set(['/login', '/signup', '/forgot-password'])
  if (fullBleedAuthRoutes.has(location.pathname)) {
    return <Outlet />
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-brand-900/30 to-brand-700/30 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <Outlet />
      </div>
    </div>
  )
}

export default AuthLayout

