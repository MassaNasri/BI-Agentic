import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  UserPlus,
  Mail,
  Lock,
  User as UserIcon,
  Users,
  Sparkles,
  Activity,
  BarChart3,
  LineChart,
} from 'lucide-react'
import { useAuthStore } from '../../store/auth'
import { Button, Input, Select, ErrorAlert } from '../../components'
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

const PASSWORD_STRENGTH_COLORS = ['#ef4444', '#ffb347', '#fbbf24', '#22c55e']
const PASSWORD_STRENGTH_LABELS = ['Weak', 'Fair', 'Good', 'Strong']

function getPasswordStrength(password) {
  if (!password) return 0

  let score = 0
  if (password.length >= 8) score += 1
  if (/[A-Z]/.test(password) && /\d/.test(password)) score += 1
  if (/[^A-Za-z0-9]/.test(password) || password.length >= 12) score += 1

  return Math.min(score, 3)
}

function Signup() {
  const navigate = useNavigate()
  const { signup, isLoading } = useAuthStore()
  const [searchParams] = useSearchParams()

  const invitationEmail = searchParams.get('email')
  const invitationRole = searchParams.get('role')
  const invitationToken = searchParams.get('token')
  const workspaceName = searchParams.get('workspace')
  const inviterName = searchParams.get('inviter')
  const isInvited = !!(invitationEmail && invitationRole && invitationToken)

  const [formData, setFormData] = useState({
    name: '',
    email: invitationEmail || '',
    password: '',
    role: invitationRole || 'analyst',
    invitation_token: invitationToken || '',
  })

  const [errors, setErrors] = useState({})
  const [apiError, setApiError] = useState('')
  const [showError, setShowError] = useState(false)

  useEffect(() => {
    if (isInvited) {
      setFormData((prev) => ({
        ...prev,
        email: invitationEmail,
        role: invitationRole,
        invitation_token: invitationToken,
      }))
    }
  }, [invitationEmail, invitationRole, invitationToken, isInvited])

  useEffect(() => {
    if (apiError) {
      setShowError(true)
    }
  }, [apiError])

  const roleOptions = [
    { value: 'manager', label: 'Manager - Create and manage workspace' },
    { value: 'analyst', label: 'Analyst - Analyze data and create reports' },
    { value: 'executive', label: 'Executive - View reports and dashboards' },
  ]

  const validateForm = () => {
    const newErrors = {}

    if (!formData.name.trim()) {
      newErrors.name = 'Name is required'
    }

    if (!formData.email.trim()) {
      newErrors.email = 'Email is required'
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = 'Email is invalid'
    }

    if (!formData.password) {
      newErrors.password = 'Password is required'
    } else if (formData.password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    })
    if (errors[e.target.name]) {
      setErrors({
        ...errors,
        [e.target.name]: null,
      })
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!validateForm()) {
      return
    }

    setApiError('')
    setShowError(false)
    const result = await signup(formData)

    if (result.success) {
      if (isInvited) {
        navigate('/verify-email?sent=true&invited=true')
      } else {
        navigate('/verify-email?sent=true')
      }
    } else {
      setApiError(result.error || 'Registration failed. Please try again.')
      setShowError(true)
    }
  }

  const passwordStrength = getPasswordStrength(formData.password)

  return (
    <motion.div variants={pageWrapperVariants} initial="hidden" animate="visible" className="relative min-h-screen overflow-hidden">
      <ParticleBackground />

      <div className="relative z-10 flex min-h-screen items-center justify-center px-6 py-10">
        <div className="grid w-full max-w-7xl items-center gap-10 lg:grid-cols-2">
          <motion.aside
            variants={titleVariants}
            className="relative hidden min-h-[620px] overflow-hidden rounded-3xl border border-brand-500/30 bg-brand-900/35 p-10 backdrop-blur-xl lg:flex lg:flex-col lg:justify-between"
          >
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(69,53,212,0.35),transparent_42%),radial-gradient(circle_at_75%_35%,rgba(255,45,120,0.28),transparent_45%),radial-gradient(circle_at_55%_85%,rgba(255,179,71,0.22),transparent_35%)]" />
            <div className="absolute -left-8 top-24 h-44 w-44 rounded-full bg-brand-500/30 blur-3xl" />
            <div className="absolute bottom-4 right-10 h-52 w-52 rounded-full bg-fire-500/30 blur-3xl" />

            <div className="relative z-10">
              <p className="mb-4 text-sm uppercase tracking-[0.22em] text-brand-300">Analytics Onboarding</p>
              <h1 className="text-5xl font-extrabold leading-tight text-white">
                Start your
                <span className="mt-2 block bg-gradient-to-r from-brand-300 via-fire-400 to-amber-400 bg-clip-text text-transparent">
                  analytics journey
                </span>
              </h1>
              <p className="mt-6 max-w-md text-lg font-light text-brand-200">
                Launch your workspace, invite your team, and transform live data into business
                momentum.
              </p>
            </div>

            <div className="relative z-10 grid grid-cols-3 gap-4">
              {[
                { icon: BarChart3, value: '12.4k', label: 'Live Queries' },
                { icon: Activity, value: '99.9%', label: 'Uptime' },
                { icon: LineChart, value: '4.8x', label: 'Faster Insights' },
              ].map((stat, index) => {
                const Icon = stat.icon
                return (
                  <motion.div
                    key={stat.label}
                    className="rounded-2xl border border-brand-400/25 bg-[var(--c-card-bg)]/5 p-4 text-center"
                    animate={{ y: [0, -9, 0] }}
                    transition={{ duration: 4.5 + index, repeat: Infinity, ease: 'easeInOut' }}
                  >
                    <Icon className="mx-auto mb-2 h-5 w-5 text-brand-200" />
                    <p className="text-lg font-semibold text-white">{stat.value}</p>
                    <p className="text-xs text-brand-300">{stat.label}</p>
                  </motion.div>
                )
              })}
            </div>
          </motion.aside>

          <motion.div
            variants={formContainerVariants}
            animate={showError ? errorShakeVariants.shake : 'visible'}
            className="auth-form-shell w-full max-w-xl justify-self-center rounded-3xl border border-brand-400/25 bg-[var(--c-card-bg)] p-8 shadow-[0_25px_80px_rgba(0,0,0,0.5)] backdrop-blur-2xl sm:p-10"
          >
            <div className="mb-6 flex items-center justify-center gap-3">
              {[0, 1, 2].map((step) => (
                <span
                  key={step}
                  className={`h-2.5 w-9 rounded-full ${
                    step === 0 ? 'bg-brand-500 shadow-[0_0_14px_rgba(69,53,212,0.6)]' : 'bg-brand-300/30'
                  }`}
                />
              ))}
            </div>

            <div className="mb-8 text-center">
              <motion.div variants={iconContainerVariants} className="relative mb-5 inline-flex">
                <motion.div
                  className="absolute inset-0 rounded-full bg-fire-500/35 blur-xl"
                  animate={{ scale: [1, 1.15, 1], opacity: [0.35, 0.7, 0.35] }}
                  transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
                />
                <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-brand-700 to-brand-600">
                  <UserPlus className="h-8 w-8 text-white" />
                </div>
              </motion.div>
              <motion.h2 variants={titleVariants} className="text-4xl font-bold text-white">
                Create Your Account
              </motion.h2>
              <motion.p variants={titleVariants} className="mt-2 text-base text-brand-200">
                Join thousands of analysts worldwide
              </motion.p>
            </div>

            <AnimatePresence>
              {isInvited && workspaceName && (
                <motion.div
                  variants={alertVariants}
                  initial="hidden"
                  animate="visible"
                  exit="exit"
                  className="mb-6 rounded-xl border border-brand-500/50 bg-gradient-to-r from-brand-800 to-brand-700 p-4"
                >
                  <div className="flex items-start space-x-3">
                    <Users className="mt-0.5 h-5 w-5 flex-shrink-0 text-brand-100" />
                    <div className="text-sm text-brand-100">
                      <p className="mb-1 font-semibold">
                        You&apos;ve been invited to join {workspaceName} {'\u{1F389}'}
                      </p>
                      <p>
                        {inviterName ? `${inviterName} invited you` : 'An admin invited you'} as{' '}
                        <strong>{invitationRole?.charAt(0).toUpperCase() + invitationRole?.slice(1)}</strong>.
                      </p>
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
                    label="Full Name"
                    icon={UserIcon}
                    name="name"
                    type="text"
                    required
                    value={formData.name}
                    onChange={handleChange}
                    error={errors.name}
                    placeholder="John Doe"
                    className="rounded-xl border-brand-300/30 bg-[var(--c-card-bg)]/5 py-3 placeholder:text-brand-200/50"
                  />
                </motion.div>

                <motion.div variants={formFieldVariants}>
                  <Input
                    label="Email Address"
                    icon={Mail}
                    name="email"
                    type="email"
                    required
                    value={formData.email}
                    onChange={handleChange}
                    error={errors.email}
                    placeholder="you@example.com"
                    disabled={isInvited}
                    className={`rounded-xl border-brand-300/30 bg-[var(--c-card-bg)]/5 py-3 placeholder:text-brand-200/50 ${
                      isInvited ? 'cursor-not-allowed opacity-75' : ''
                    }`}
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
                    error={errors.password}
                    placeholder={'\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022'}
                    className="rounded-xl border-brand-300/30 bg-[var(--c-card-bg)]/5 py-3 placeholder:text-brand-200/50"
                  />

                  <div className="mt-3">
                    <div className="mb-2 flex items-center justify-between text-xs">
                      <span className="text-brand-300">Password strength</span>
                      <span className="text-brand-200">{PASSWORD_STRENGTH_LABELS[passwordStrength]}</span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-brand-900/80">
                      <motion.div
                        className="h-full rounded-full"
                        style={{ backgroundColor: PASSWORD_STRENGTH_COLORS[passwordStrength] }}
                        animate={{
                          width: formData.password ? `${((passwordStrength + 1) / 4) * 100}%` : '0%',
                        }}
                        transition={{ duration: 0.35, ease: 'easeOut' }}
                      />
                    </div>
                  </div>
                </motion.div>

                {!isInvited && (
                  <motion.div variants={formFieldVariants}>
                    <Select
                      label="Role"
                      name="role"
                      value={formData.role}
                      onChange={handleChange}
                      options={roleOptions}
                      className="rounded-xl border-brand-300/30 bg-[var(--c-card-bg)]/5 py-3 text-brand-100"
                    />
                  </motion.div>
                )}

                <motion.div variants={submitButtonVariants} whileHover="hover" whileTap="tap" className="mt-8">
                  <Button
                    type="submit"
                    loading={isLoading}
                    fullWidth
                    className="rounded-xl py-3.5 text-base font-semibold shadow-[0_0_30px_rgba(255,45,120,0.35)] hover:shadow-[0_0_45px_rgba(255,45,120,0.5)]"
                  >
                    {isLoading ? (
                      'Creating account...'
                    ) : (
                      <>
                        <Sparkles className="h-5 w-5" />
                        <span>Create Account</span>
                      </>
                    )}
                  </Button>
                </motion.div>
              </motion.div>
            </form>

            <motion.div variants={linksVariants} className="mt-6 text-center">
              <p className="text-sm text-brand-200">
                Already have an account?{' '}
                <Link to="/login" className="font-semibold text-fire-400 transition-colors hover:text-fire-400">
                  Sign In
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

export default Signup
