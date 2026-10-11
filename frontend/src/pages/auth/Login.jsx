import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ShieldCheck, Mail, Lock, CheckCircle, Activity, BarChart3, PieChart } from 'lucide-react'
import { useAuthStore } from '../../store/auth'
import { Button, Input, ErrorAlert } from '../../components'
import ParticleBackground from '../../components/ParticleBackground'
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

  useEffect(() => {
    if (searchParams.get('workspace_joined') === 'true' || searchParams.get('joined') === 'true') {
      setShowWorkspaceJoinedMessage(true)
    }
  }, [searchParams])

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
    <motion.div variants={pageWrapperVariants} initial="hidden" animate="visible" className="relative min-h-screen overflow-hidden">
      <ParticleBackground />

      <div className="relative z-10 flex min-h-screen items-center justify-center px-6 py-10">
        <div className="grid w-full max-w-6xl items-center gap-10 lg:grid-cols-2">
          <motion.aside
            variants={titleVariants}
            className="relative hidden min-h-[560px] overflow-hidden rounded-3xl border border-brand-500/30 bg-brand-900/35 p-10 backdrop-blur-xl lg:flex lg:flex-col lg:justify-between"
          >
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(255,45,120,0.28),transparent_38%),radial-gradient(circle_at_80%_40%,rgba(69,53,212,0.32),transparent_45%),radial-gradient(circle_at_50%_90%,rgba(255,179,71,0.22),transparent_35%)]" />
            <div className="absolute -right-10 top-16 h-40 w-40 rounded-full bg-fire-500/35 blur-3xl" />
            <div className="absolute bottom-0 left-8 h-56 w-56 rounded-full bg-brand-500/30 blur-3xl" />

            <div className="relative z-10">
              <p className="mb-4 text-sm uppercase tracking-[0.2em] text-brand-300">Secure Access Layer</p>
              <h1 className="text-5xl font-extrabold leading-tight text-white">
                Welcome to
                <span className="mt-2 block bg-gradient-to-r from-brand-300 via-fire-400 to-amber-400 bg-clip-text text-transparent">
                  Intelligence Ops
                </span>
              </h1>
              <p className="mt-6 max-w-md text-lg font-light text-brand-200">
                Sign in to your analytics workspace and launch voice-powered decisions across your
                entire organization.
              </p>
            </div>

            <div className="relative z-10 grid grid-cols-3 gap-4">
              {[BarChart3, Activity, PieChart].map((Icon, index) => (
                <motion.div
                  key={index}
                  className="flex h-16 items-center justify-center rounded-2xl border border-brand-400/25 bg-[var(--c-card-bg)]/5"
                  animate={{ y: [0, -8, 0] }}
                  transition={{ duration: 4 + index, repeat: Infinity, ease: 'easeInOut' }}
                >
                  <Icon className="h-7 w-7 text-brand-200" />
                </motion.div>
              ))}
            </div>
          </motion.aside>

          <motion.div
            variants={formContainerVariants}
            animate={showError ? errorShakeVariants.shake : 'visible'}
            className="auth-form-shell w-full max-w-md justify-self-center rounded-3xl border border-brand-400/25 bg-[var(--c-card-bg)] p-8 shadow-[0_25px_80px_rgba(0,0,0,0.5)] backdrop-blur-2xl sm:p-10"
          >
            <div className="mb-8 text-center">
              <motion.div variants={iconContainerVariants} className="relative mb-5 inline-flex">
                <motion.div
                  className="absolute inset-0 rounded-full bg-brand-400/40 blur-xl"
                  animate={{ scale: [1, 1.15, 1], opacity: [0.35, 0.7, 0.35] }}
                  transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
                />
                <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-brand-700 to-brand-600">
                  <ShieldCheck className="h-8 w-8 text-white" />
                </div>
              </motion.div>
              <motion.h2 variants={titleVariants} className="text-4xl font-bold text-white">
                Welcome Back
              </motion.h2>
              <motion.p variants={titleVariants} className="mt-2 text-base text-brand-200">
                Sign in to your analytics workspace
              </motion.p>
            </div>

            <AnimatePresence>
              {showWorkspaceJoinedMessage && (
                <motion.div
                  variants={alertVariants}
                  initial="hidden"
                  animate="visible"
                  exit="exit"
                  className="mb-6 rounded-xl border border-green-400/35 bg-gradient-to-r from-green-500/15 to-brand-400/10 p-4"
                >
                  <div className="flex items-start space-x-3">
                    <CheckCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-green-300" />
                    <div className="text-sm text-green-100">
                      <p className="mb-1 font-semibold">
                        Invitation Accepted! {'\u{1F389}'}
                      </p>
                      <p>You have successfully joined the workspace. Please log in to access it.</p>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {apiError && (
                <motion.div variants={alertVariants} initial="hidden" animate="visible" exit="exit" className="mb-6">
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

            <form onSubmit={handleSubmit} className="space-y-6">
              <motion.div variants={formFieldsContainerVariants}>
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
                    className="rounded-xl border-brand-300/30 bg-[var(--c-card-bg)]/5 py-3 placeholder:text-brand-200/50"
                  />
                </motion.div>

                <motion.div variants={formFieldVariants}>
                  <Input
                    label="Password"
                    icon={Lock}
                    name="password"
                    type="password"
                    required
                    value={formData.password}
                    onChange={handleChange}
                    placeholder={'\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022'}
                    className="rounded-xl border-brand-300/30 bg-[var(--c-card-bg)]/5 py-3 placeholder:text-brand-200/50"
                  />
                </motion.div>

                <motion.div variants={submitButtonVariants} whileHover="hover" whileTap="tap" className="mt-8">
                  <Button
                    type="submit"
                    loading={isLoading}
                    fullWidth
                    className="rounded-xl py-3.5 text-base font-semibold shadow-[0_0_30px_rgba(255,45,120,0.35)] hover:shadow-[0_0_45px_rgba(255,45,120,0.5)]"
                  >
                    {isLoading ? (
                      'Signing in...'
                    ) : (
                      <>
                        <ShieldCheck className="h-5 w-5" />
                        <span>Sign In</span>
                      </>
                    )}
                  </Button>
                </motion.div>
              </motion.div>
            </form>

            <motion.div variants={linksVariants} className="mt-3 text-center">
              <Link
                to="/forgot-password"
                className="text-sm font-semibold text-brand-300 transition-colors hover:text-white"
              >
                Forgot Password?
              </Link>
            </motion.div>

            <motion.div variants={linksVariants} className="mt-6 text-center">
              <p className="text-sm text-brand-200">
                Don&apos;t have an account?{' '}
                <Link to="/signup" className="font-semibold text-fire-400 transition-colors hover:text-fire-400">
                  Create Account
                </Link>
              </p>
            </motion.div>

            <motion.div variants={linksVariants} className="mt-4 text-center">
              <Link to="/" className="text-sm text-brand-300 transition-colors hover:text-brand-100">
                {'\u2190'} Back to Home
              </Link>
            </motion.div>
          </motion.div>
        </div>
      </div>
    </motion.div>
  )
}

export default Login
