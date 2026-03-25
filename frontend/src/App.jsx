import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { useAuthStore } from './store/auth'

// Layouts
import AuthLayout from './layouts/AuthLayout'
import DashboardLayout from './layouts/DashboardLayout'

// Pages
import Home from './pages/Home'
import Login from './pages/auth/Login'
import Signup from './pages/auth/Signup'
import VerifyEmail from './pages/auth/VerifyEmail'
import ForgotPassword from './pages/auth/ForgotPassword'
import Profile from './pages/profile/Profile'
import WorkspaceSettings from './pages/workspace/WorkspaceSettings'
import MembersList from './pages/workspace/MembersList'
import InviteMember from './pages/workspace/InviteMember'
import AcceptInvite from './pages/workspace/AcceptInvite'
import Dashboard from './pages/dashboard/Dashboard'
import LineageExplorer from './pages/dashboard/LineageExplorer'
import DatabaseManagement from './pages/database/DatabaseManagement'
import VoiceReportManager from './pages/voice-reports/VoiceReportManager'
import SQLEditor from './pages/voice-reports/SQLEditor'
import DashboardViewer from './pages/voice-reports/DashboardViewer'
import AdminDashboard from './pages/admin/AdminDashboard'
import SubscriptionPlansPage from './pages/subscription/SubscriptionPlansPage'

const getDefaultRoute = (user) => {
  if (!user) return '/login'
  if (user.role === 'admin') return '/admin-dashboard'
  return '/dashboard'
}

// Protected Route Component
function PrivateRoute({ children, roles }) {
  const { isAuthenticated, user } = useAuthStore()
  
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  
  if (roles && !roles.includes(user?.role)) {
    return <Navigate to={getDefaultRoute(user)} replace />
  }
  
  return children
}

function App() {
  const location = useLocation()
  
  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        {/* Public Routes */}
        <Route path="/" element={<Home />} />
        
        {/* Auth Routes */}
        <Route element={<AuthLayout />}>
          <Route path="/login" element={<Login />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/accept-invite" element={<AcceptInvite />} />
        </Route>
        
        {/* Protected Dashboard Routes */}
        <Route
          path="/dashboard"
          element={
            <PrivateRoute roles={['manager', 'analyst', 'executive']}>
              <DashboardLayout />
            </PrivateRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="lineage" element={<LineageExplorer />} />
          <Route path="profile" element={<Profile />} />
          
          {/* Database Route (Manager only) */}
          <Route
            path="database"
            element={
              <PrivateRoute roles={['manager']}>
                <DatabaseManagement />
              </PrivateRoute>
            }
          />
          <Route
            path="subscription"
            element={
              <PrivateRoute roles={['manager']}>
                <SubscriptionPlansPage />
              </PrivateRoute>
            }
          />
          
          {/* Voice Reports Routes */}
          <Route
            path="voice-reports"
            element={
              <PrivateRoute roles={['manager']}>
                <VoiceReportManager />
              </PrivateRoute>
            }
          />
          <Route
            path="sql-editor"
            element={
              <PrivateRoute roles={['analyst']}>
                <SQLEditor />
              </PrivateRoute>
            }
          />
          <Route
            path="analytics"
            element={
              <PrivateRoute roles={['executive']}>
                <DashboardViewer />
              </PrivateRoute>
            }
          />
          
          {/* Workspace Routes (Manager only for some) */}
          <Route path="workspace" element={<WorkspaceSettings />} />
          <Route path="members" element={<MembersList />} />
          <Route
            path="invite"
            element={
              <PrivateRoute roles={['manager']}>
                <InviteMember />
              </PrivateRoute>
            }
          />
        </Route>

        <Route
          path="/admin-dashboard"
          element={
            <PrivateRoute roles={['admin']}>
              <AdminDashboard />
            </PrivateRoute>
          }
        />
        
        {/* Catch all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AnimatePresence>
  )
}

export default App

