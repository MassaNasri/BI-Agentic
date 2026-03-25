import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuthStore } from '../store/auth'
import { 
  Home, Users, Settings, User, LogOut, 
  UserPlus, LayoutDashboard, Menu, X, Database,
  Mic, Code, BarChart3, CreditCard
} from 'lucide-react'
import { useState, useEffect } from 'react'
import { slideInLeft, sidebarItemVariants } from '../animations/variants'

function DashboardLayout() {
  const { user, logout, loadUser } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  
  // Load user profile on mount only
  useEffect(() => {
    loadUser()
  }, []) // Removed location.pathname dependency to prevent unnecessary reloads
  
  // Periodic profile refresh (every 60 seconds) to catch role changes
  // Increased interval to reduce API calls
  useEffect(() => {
    const interval = setInterval(() => {
      loadUser()
    }, 60000) // 60 seconds (reduced from 30)
    
    return () => clearInterval(interval)
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
      name: 'Analytics', 
      path: '/dashboard/analytics', 
      icon: BarChart3, 
      roles: ['executive'],
      description: 'View Insights'
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

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Mobile sidebar backdrop */}
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 bg-gray-600 bg-opacity-75 z-20 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <motion.aside 
        initial={{ x: -300 }}
        animate={{ x: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className={`
          fixed inset-y-0 left-0 z-30 w-64 bg-white shadow-lg transform transition-transform duration-300 ease-in-out
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
          lg:translate-x-0
        `}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center justify-between h-16 px-6 border-b bg-gradient-to-r from-blue-50 to-indigo-50">
            <div className="flex items-center space-x-2">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-indigo-600 rounded-lg flex items-center justify-center shadow-md">
                <Mic className="w-6 h-6 text-white" />
              </div>
              <div>
                <span className="text-xl font-bold text-gray-800 block leading-tight">BI Voice</span>
                <span className="text-xs text-gray-600">AI-Powered Analytics</span>
              </div>
            </div>
            <button
              className="lg:hidden"
              onClick={() => setSidebarOpen(false)}
            >
              <X className="w-6 h-6" />
            </button>
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
                    className="block"
                    onClick={() => setSidebarOpen(false)}
                  >
                    <motion.div
                      variants={sidebarItemVariants}
                      whileHover="hover"
                      whileTap="tap"
                      className={`
                        flex items-center space-x-3 px-4 py-3 rounded-lg transition-all duration-200
                        ${active 
                          ? 'bg-primary-50 text-primary-600 shadow-md font-semibold' 
                          : 'text-gray-700 hover:bg-gray-100 hover:shadow-sm'
                        }
                      `}
                    >
                      <Icon className="w-5 h-5" />
                      <span className="font-medium">{item.name}</span>
                      {active && (
                        <motion.span 
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          className="ml-auto w-1.5 h-1.5 rounded-full bg-primary-600"
                        />
                      )}
                    </motion.div>
                  </Link>
                </motion.div>
              )
            })}
          </nav>

          {/* User section */}
          <div className="p-4 border-t">
            <div className="flex items-center space-x-3 px-4 py-3">
              <div className="flex-shrink-0 w-10 h-10 bg-primary-100 rounded-full flex items-center justify-center">
                <User className="w-5 h-5 text-primary-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">
                  {user?.name}
                </p>
                <p className="text-xs text-gray-500 truncate">
                  {user?.role}
                </p>
              </div>
            </div>
            <motion.button
              onClick={handleLogout}
              whileHover={{ scale: 1.02, backgroundColor: 'rgba(254, 226, 226, 1)' }}
              whileTap={{ scale: 0.98 }}
              transition={{ duration: 0.2 }}
              className="w-full flex items-center space-x-3 px-4 py-3 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
            >
              <LogOut className="w-5 h-5" />
              <span className="font-medium">Logout</span>
            </motion.button>
          </div>
        </div>
      </motion.aside>

      {/* Main content */}
      <div className="lg:pl-64">
        {/* Top bar */}
        <header className="sticky top-0 z-10 flex items-center justify-between h-16 px-6 bg-white border-b">
          <button
            className="lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="w-6 h-6" />
          </button>
          
          <div className="flex items-center space-x-4">
            <span className="text-sm text-gray-600 hidden sm:block">
              Welcome, <span className="font-semibold">{user?.name}</span>
            </span>
            <span className={`
              px-3 py-1 text-xs font-medium rounded-full
              ${user?.role === 'manager' ? 'bg-blue-100 text-blue-800' : ''}
              ${user?.role === 'analyst' ? 'bg-purple-100 text-purple-800' : ''}
              ${user?.role === 'executive' ? 'bg-green-100 text-green-800' : ''}
            `}>
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

