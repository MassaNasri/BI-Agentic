import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuthStore } from '../../store/auth'
import { LogIn, Mail, Lock, CheckCircle } from 'lucide-react'
import { Button, Input, ErrorAlert } from '../../components'
import {
  pageWrapperVariants,
  formContainerVariants,
  titleVariants,
  iconContainerVariants,
  formFieldsContainerVariants,
  formFieldVariants,
  submitButtonVariants,
  linksVariants,
  alertVariants,
  errorShakeVariants,
  floatingBlobVariants,
  floatingBlobVariants2,
} from '../../animations/formVariants'

function Login() {
  const navigate = useNavigate()
  const { login, isLoading } = useAuthStore()
  const [searchParams] = useSearchParams()
  
  const [formData, setFormData] = useState({
    email: '',
    password: '',
  })
  const [apiError, setApiError] = useState('')
  const [showWorkspaceJoinedMessage, setShowWorkspaceJoinedMessage] = useState(false)
  const [showError, setShowError] = useState(false)
  
  // Check if user just accepted a workspace invitation
  useEffect(() => {
    if (searchParams.get('workspace_joined') === 'true' || searchParams.get('joined') === 'true') {
      setShowWorkspaceJoinedMessage(true)
    }
  }, [searchParams])
  
  // Show error animation
  useEffect(() => {
    if (apiError) {
      setShowError(true)
    }
  }, [apiError])

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    setApiError('')
    setShowError(false)
    const result = await login(formData.email, formData.password)
    
    if (result.success) {
      if (result.user?.role === 'admin') {
        navigate('/admin-dashboard')
      } else {
        navigate('/dashboard')
      }
    } else {
      setApiError(result.error || 'Login failed. Please try again.')
      setShowError(true)
    }
  }

  return (
    <motion.div
      variants={pageWrapperVariants}
      initial="hidden"
      animate="visible"
      className="min-h-screen bg-gradient-to-br from-primary-50 via-blue-50 to-indigo-50 flex items-center justify-center px-6 py-12 relative overflow-hidden"
    >
      {/* Animated Background Elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <motion.div
          variants={floatingBlobVariants}
          animate="animate"
          className="absolute top-20 left-10 w-72 h-72 bg-primary-300 rounded-full mix-blend-multiply filter blur-3xl opacity-20"
        />
        <motion.div
          variants={floatingBlobVariants2}
          animate="animate"
          className="absolute bottom-20 right-20 w-96 h-96 bg-blue-300 rounded-full mix-blend-multiply filter blur-3xl opacity-20"
        />
      </div>

      {/* Form Container */}
      <motion.div
        variants={formContainerVariants}
        animate={showError ? errorShakeVariants.shake : {}}
        className="card max-w-md w-full relative z-10 bg-white/90 backdrop-blur-sm shadow-2xl"
      >
        {/* Header */}
        <div className="text-center mb-8">
          <motion.div
            variants={iconContainerVariants}
            className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-primary-100 to-blue-100 rounded-full mb-4 shadow-lg"
          >
            <LogIn className="w-8 h-8 text-primary-600" />
          </motion.div>
          <motion.h2 variants={titleVariants} className="text-3xl font-bold text-gray-900">
            Welcome Back
          </motion.h2>
          <motion.p variants={titleVariants} className="mt-2 text-gray-600">
            Sign in to your account
          </motion.p>
        </div>

        {/* Success Message */}
        <AnimatePresence>
          {showWorkspaceJoinedMessage && (
            <motion.div
              variants={alertVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="mb-6 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-lg p-4"
            >
              <div className="flex items-start space-x-3">
                <CheckCircle className="w-5 h-5 text-green-600 mt-0.5 flex-shrink-0" />
                <div className="text-sm text-green-800">
                  <p className="font-semibold mb-1">Invitation Accepted! 🎉</p>
                  <p>You have successfully joined the workspace. Please log in to access it.</p>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Error Message */}
        <AnimatePresence>
          {apiError && (
            <motion.div
              variants={alertVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="mb-6"
            >
              <ErrorAlert
                message={apiError}
                type="error"
                onClose={() => {
                  setApiError('')
                  setShowError(false)
                }}
              />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-6">
          <motion.div variants={formFieldsContainerVariants}>
            {/* Email Field */}
            <motion.div variants={formFieldVariants}>
              <Input
                label="Email Address"
                icon={Mail}
                name="email"
                type="email"
                required
                value={formData.email}
                onChange={handleChange}
                placeholder="you@example.com"
              />
            </motion.div>

            {/* Password Field */}
            <motion.div variants={formFieldVariants}>
              <Input
                label="Password"
                icon={Lock}
                name="password"
                type="password"
                required
                value={formData.password}
                onChange={handleChange}
                placeholder="••••••••"
              />
            </motion.div>

            {/* Submit Button */}
            <motion.div variants={submitButtonVariants} whileHover="hover" whileTap="tap" className="mt-8">
              <Button type="submit" loading={isLoading} fullWidth className="py-3 shadow-lg">
                {isLoading ? (
                  'Signing in...'
                ) : (
                  <>
                    <LogIn className="w-5 h-5" />
                    <span>Sign In</span>
                  </>
                )}
              </Button>
            </motion.div>
          </motion.div>
        </form>

        {/* Links */}
        <motion.div variants={linksVariants} className="mt-2 text-center">
          <Link
            to="/forgot-password"
            className="text-sm text-primary-600 hover:text-primary-700 font-semibold transition-colors"
          >
            Forgot Password?
          </Link>
        </motion.div>

        <motion.div variants={linksVariants} className="mt-6 text-center">
          <p className="text-sm text-gray-600">
            Don't have an account?{' '}
            <Link
              to="/signup"
              className="text-primary-600 hover:text-primary-700 font-semibold transition-colors"
            >
              Create Account
            </Link>
          </p>
        </motion.div>

        <motion.div variants={linksVariants} className="mt-4 text-center">
          <Link to="/" className="text-sm text-gray-500 hover:text-gray-700 transition-colors">
            ← Back to Home
          </Link>
        </motion.div>
      </motion.div>
    </motion.div>
  )
}

export default Login
