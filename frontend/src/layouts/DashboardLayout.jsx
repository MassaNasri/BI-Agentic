import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuthStore } from '../store/auth'
import { 
  Home, Users, Settings, User, LogOut, 
  UserPlus, Database, Mic, Code, CreditCard,
  ChevronLeft
} from 'lucide-react'
import { useState, useEffect, useMemo } from 'react'
import { slideInLeft, sidebarItemVariants } from '../animations/variants'

function DashboardLayout() {
  const { user, logout, loadUser } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const desktopQuery = '(min-width: 1024px)'
  const getInitialDesktopState = () => {
    if (typeof window === 'undefined') return true
    return window.matchMedia(desktopQuery).matches
  }
  const [isDesktop, setIsDesktop] = useState(getInitialDesktopState)
  const [sidebarOpen, setSidebarOpen] = useState(getInitialDesktopState)
  
  // Load user profile on mount only
  useEffect(() => {
    loadUser()
  }, [loadUser]) // Removed location.pathname dependency to prevent unnecessary reloads
  
  // Periodic profile refresh (every 60 seconds) to catch role changes
  // Increased interval to reduce API calls
  useEffect(() => {
    const interval = setInterval(() => {
      loadUser()
    }, 60000) // 60 seconds (reduced from 30)
    
    return () => clearInterval(interval)
  }, [loadUser])

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const mediaQuery = window.matchMedia(desktopQuery)

    const handleViewportChange = (event) => {
      setIsDesktop(event.matches)
      setSidebarOpen(event.matches)
    }

    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handleViewportChange)
    } else {
      mediaQuery.addListener(handleViewportChange)
    }

    return () => {
      if (mediaQuery.removeEventListener) {
        mediaQuery.removeEventListener('change', handleViewportChange)
      } else {
        mediaQuery.removeListener(handleViewportChange)
      }
    }
  }, [])

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const isActive = (path) => {
    return location.pathname === path || location.pathname.startsWith(path)
  }

  const navigation = [
    { 
      name: 'Dashboard', 
      path: '/dashboard', 
      icon: Home, 
      roles: ['manager', 'analyst', 'executive'],
      description: 'Overview'
    },
    { 
      name: 'Voice Reports', 
      path: '/dashboard/voice-reports', 
      icon: Mic, 
      roles: ['manager'],
      description: 'Create Reports'
    },
    { 
      name: 'SQL Editor', 
      path: '/dashboard/sql-editor', 
      icon: Code, 
      roles: ['analyst'],
      description: 'Edit Queries'
    },
    { 
      name: 'Database', 
      path: '/dashboard/database', 
      icon: Database, 
      roles: ['manager'],
      description: 'Manage Data'
    },
    {
      name: 'Subscription',
      path: '/dashboard/subscription',
      icon: CreditCard,
      roles: ['manager'],
      description: 'Billing Plans',
    },
    { 
      name: 'Members', 
      path: '/dashboard/members', 
      icon: Users, 
      roles: ['manager', 'analyst', 'executive'],
      description: 'Team'
    },
    { 
      name: 'Invite Member', 
      path: '/dashboard/invite', 
      icon: UserPlus, 
      roles: ['manager'],
      description: 'Add Users'
    },
    { 
      name: 'Workspace', 
      path: '/dashboard/workspace', 
      icon: Settings, 
      roles: ['manager'],
      description: 'Settings'
    },
    { 
      name: 'Profile', 
      path: '/dashboard/profile', 
      icon: User, 
      roles: ['manager', 'analyst', 'executive'],
      description: 'Account'
    },
  ]

  const filteredNavigation = navigation.filter(item => 
    item.roles.includes(user?.role)
  )

  const toggleSidebar = () => setSidebarOpen((current) => !current)

  const userInitials = useMemo(() => {
    const source = user?.name || user?.email || 'U'
    const parts = source.trim().split(/\s+/)
    if (parts.length === 1) return parts[0][0]?.toUpperCase() || 'U'
    return `${parts[0][0] || ''}${parts[1][0] || ''}`.toUpperCase() || 'U'
  }, [user?.name, user?.email])

  const roleBadgeClass = useMemo(() => {
    if (user?.role === 'admin') return 'border border-brand-500/40 bg-brand-500/20 text-brand-300'
    if (user?.role === 'manager') return 'border border-brand-600/40 bg-brand-600/20 text-brand-200'
    if (user?.role === 'analyst') return 'border border-amber-500/40 bg-amber-500/20 text-amber-400'
    if (user?.role === 'executive') return 'border border-fire-500/40 bg-fire-500/20 text-fire-400'
    return 'border border-brand-300/40 bg-brand-300/15 text-brand-200'
  }, [user?.role])

  return (
    <div className="min-h-screen bg-[var(--c-bg)] text-[var(--c-text)]">
      {/* Mobile sidebar backdrop */}
      <AnimatePresence>
        {!isDesktop && sidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="fixed inset-0 z-20 bg-brand-950/75 backdrop-blur-sm lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Shared Sidebar Toggle */}
      <button
        type="button"
        aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
        onClick={toggleSidebar}
        className={`
          fixed top-5 z-40 flex h-10 w-10 items-center justify-center rounded-full
          border border-[rgba(108,92,231,0.3)] bg-brand-900/95 text-brand-300
          hover:bg-[rgba(255,255,255,0.07)] hover:text-white
          transition-[left,transform,background-color] duration-300 ease-in-out
        `}
        style={{ left: sidebarOpen ? '15rem' : '0.75rem' }}
      >
        <ChevronLeft
          className={`
            w-5 h-5 transition-transform duration-300 ease-in-out
            ${sidebarOpen ? 'rotate-0' : 'rotate-180'}
          `}
        />
      </button>

      {/* Sidebar */}
      <aside 
        className={`
          fixed inset-y-0 left-0 z-30 overflow-hidden border-r border-[rgba(108,92,231,0.2)] bg-brand-900 shadow-[0_18px_60px_rgba(0,0,0,0.45)]
          transition-[width,transform,opacity] duration-300 ease-in-out
          ${isDesktop
            ? `${sidebarOpen ? 'w-64' : 'w-0'} translate-x-0`
            : `w-64 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`
          }
        `}
      >
        <div className="flex flex-col h-full">
          <div
            className={`
              flex flex-col h-full transition-opacity duration-300 ease-in-out
              ${sidebarOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}
            `}
          >
            {/* Logo */}
            <div className="flex h-16 items-center justify-between border-b border-[rgba(108,92,231,0.2)] bg-[rgba(69,53,212,0.15)] px-6">
              <div className="flex items-center space-x-2">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-600 to-brand-500 shadow-[0_8px_24px_rgba(69,53,212,0.4)]">
                  <Mic className="w-6 h-6 text-white" />
                </div>
                <div>
                  <span className="block font-['Syne'] text-xl font-bold leading-tight text-white">BI Voice</span>
                  <span className="text-xs text-brand-300">AI-Powered Analytics</span>
                </div>
              </div>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-4 py-6 space-y-2 overflow-y-auto">
              {filteredNavigation.map((item, index) => {
                const Icon = item.icon
                const active = isActive(item.path)
                
                return (
                  <motion.div
                    key={item.path}
                    variants={slideInLeft}
                    initial="hidden"
                    animate="visible"
                    transition={{ delay: index * 0.05 }}
                  >
                    <Link
                      to={item.path}
                      className="group block"
                      onClick={() => {
                        if (!isDesktop) setSidebarOpen(false)
                      }}
                    >
                      <motion.div
                        variants={sidebarItemVariants}
                        whileHover="hover"
                        whileTap="tap"
                        className={`
                          relative flex items-center space-x-3 rounded-xl px-3 py-2.5 transition-all duration-200
                          ${active
                            ? 'border border-[rgba(108,92,231,0.3)] bg-[rgba(69,53,212,0.2)] text-white shadow-[0_10px_30px_rgba(69,53,212,0.28)]'
                            : 'text-[var(--c-muted)] hover:bg-[rgba(255,255,255,0.05)] hover:text-[var(--c-text)]'
                          }
                        `}
                      >
                        {active && (
                          <span className="absolute left-0 top-1/2 h-8 w-[3px] -translate-y-1/2 rounded-r bg-gradient-to-b from-brand-500 to-fire-500" />
                        )}
                        <Icon
                          className={`w-5 h-5 ${
                            active ? 'text-brand-300' : 'text-[var(--c-muted)] group-hover:text-brand-300'
                          }`}
                        />
                        <span className="font-medium">{item.name}</span>
                        <span className="ml-auto text-xs text-brand-300/80">{item.description}</span>
                      </motion.div>
                    </Link>
                  </motion.div>
                )
              })}
            </nav>

            {/* User section */}
            <div className="border-t border-[rgba(108,92,231,0.2)] p-4">
              <div className="flex items-center space-x-3 px-4 py-3">
                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-700 to-brand-500 font-['Syne'] text-sm font-bold text-white">
                  {userInitials}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="truncate text-sm font-medium text-white">
                    {user?.name}
                  </p>
                  <p className="truncate text-xs text-brand-300">
                    {user?.role}
                  </p>
                </div>
              </div>
              <motion.button
                onClick={handleLogout}
                whileHover={{ scale: 1.02, backgroundColor: 'rgba(255,45,120,0.08)' }}
                whileTap={{ scale: 0.97 }}
                transition={{ duration: 0.2 }}
                className="flex w-full items-center space-x-3 rounded-xl px-4 py-3 text-fire-400 transition-colors hover:text-white"
              >
                <LogOut className="w-5 h-5 text-fire-400" />
                <span className="font-medium">Logout</span>
              </motion.button>
            </div>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div
        className={`
          transition-[padding-left] duration-300 ease-in-out
          ${sidebarOpen ? 'lg:pl-64' : 'lg:pl-0'}
        `}
      >
        {/* Top bar */}
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-[rgba(108,92,231,0.2)] bg-[rgba(8,5,32,0.85)] px-6 backdrop-blur-xl">
          <div className="w-8" aria-hidden="true" />
          
          <div className="flex items-center space-x-4">
            <span className="hidden text-sm text-[var(--c-muted)] sm:block">
              Welcome, <span className="font-semibold text-white">{user?.name}</span>
            </span>
            <span className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${roleBadgeClass}`}>
              {user?.role?.toUpperCase()}
            </span>
          </div>
        </header>

        {/* Page content */}
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default DashboardLayout

