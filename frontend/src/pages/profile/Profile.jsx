import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  EyeOff,
  Info,
  KeyRound,
  Loader2,
  Lock,
  MapPin,
  PowerOff,
  RotateCcw,
  Save,
  ShieldCheck,
  User,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { userAPI } from '../../api/endpoints'
import { useAuthStore } from '../../store/auth'
import { AnimatedPage } from '../../components'
import ParticleBackground from '../../components/ParticleBackground'
import { avatarVariants, infoItemVariants, sectionCardVariants } from '../../animations/uiVariants'

function Profile() {
  const navigate = useNavigate()
  const { user, updateUser, logout } = useAuthStore()

  const [profile, setProfile] = useState({
    first_name: '',
    last_name: '',
    date_of_birth: '',
    home_address: '',
    email: '',
  })
  const [originalProfile, setOriginalProfile] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isChangingPassword, setIsChangingPassword] = useState(false)
  const [isDeactivating, setIsDeactivating] = useState(false)
  const [showDeactivateModal, setShowDeactivateModal] = useState(false)
  const [showChangePasswordModal, setShowChangePasswordModal] = useState(false)
  const [errors, setErrors] = useState({})
  const [passwordErrors, setPasswordErrors] = useState({})
  const [passwordForm, setPasswordForm] = useState({
    current_password: '',
    new_password: '',
    confirm_new_password: '',
  })
  const [passwordVisibility, setPasswordVisibility] = useState({
    current_password: false,
    new_password: false,
    confirm_new_password: false,
  })

  const loadProfile = useCallback(async () => {
    try {
      const response = await userAPI.getProfile()
      const userData = response.data?.user || {}
      const nextProfile = {
        first_name: userData.first_name || '',
        last_name: userData.last_name || '',
        date_of_birth: userData.date_of_birth || '',
        home_address: userData.home_address || '',
        email: userData.email || '',
      }
      setProfile(nextProfile)
      setOriginalProfile(nextProfile)
      updateUser(userData)
    } catch (error) {
      toast.error('Failed to load profile')
    }
  }, [updateUser])

  useEffect(() => {
    loadProfile()
  }, [loadProfile])

  const validateProfile = () => {
    const nextErrors = {}
    if (!profile.first_name.trim()) {
      nextErrors.first_name = 'First name is required'
    }
    if (!profile.last_name.trim()) {
      nextErrors.last_name = 'Last name is required'
    }
    setErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  const handleProfileChange = (event) => {
    const { name, value } = event.target
    setProfile((previous) => ({
      ...previous,
      [name]: value,
    }))
    if (errors[name]) {
      setErrors((previous) => ({
        ...previous,
        [name]: null,
      }))
    }
  }

  const handleProfileSubmit = async (event) => {
    event.preventDefault()
    if (!validateProfile()) {
      return
    }
    if (!originalProfile) {
      return
    }

    const payload = {}
    ;['first_name', 'last_name', 'date_of_birth', 'home_address'].forEach((field) => {
      const currentValue = profile[field] ?? ''
      const originalValue = originalProfile[field] ?? ''
      if (currentValue !== originalValue) {
        payload[field] = currentValue
      }
    })

    if (Object.keys(payload).length === 0) {
      toast.info('No changes to save')
      return
    }

    try {
      setIsLoading(true)
      const response = await userAPI.updateProfile(payload)
      const updatedUser = response.data?.user || {}
      const refreshedProfile = {
        first_name: updatedUser.first_name || '',
        last_name: updatedUser.last_name || '',
        date_of_birth: updatedUser.date_of_birth || '',
        home_address: updatedUser.home_address || '',
        email: updatedUser.email || profile.email,
      }
      setProfile(refreshedProfile)
      setOriginalProfile(refreshedProfile)
      updateUser(updatedUser)
      toast.success('Profile updated successfully!')
    } catch (error) {
      const message = error.response?.data?.message || 'Failed to update profile'
      toast.error(message)
    } finally {
      setIsLoading(false)
    }
  }

  const handlePasswordInputChange = (event) => {
    const { name, value } = event.target
    setPasswordForm((previous) => ({
      ...previous,
      [name]: value,
    }))
    if (passwordErrors[name]) {
      setPasswordErrors((previous) => ({
        ...previous,
        [name]: null,
      }))
    }
  }

  const validatePasswordForm = () => {
    const nextErrors = {}
    if (!passwordForm.current_password) {
      nextErrors.current_password = 'Current password is required'
    }
    if (!passwordForm.new_password) {
      nextErrors.new_password = 'New password is required'
    }
    if (passwordForm.new_password !== passwordForm.confirm_new_password) {
      nextErrors.confirm_new_password = 'New password and confirmation do not match'
    }
    setPasswordErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  const handleChangePassword = async (event) => {
    event.preventDefault()
    if (!validatePasswordForm()) {
      return
    }

    try {
      setIsChangingPassword(true)
      await userAPI.changePassword(passwordForm)
      toast.success('Password changed successfully!')
      setPasswordForm({
        current_password: '',
        new_password: '',
        confirm_new_password: '',
      })
      setShowChangePasswordModal(false)
    } catch (error) {
      const backendErrors = error.response?.data?.errors || {}
      const message = error.response?.data?.message

      if (backendErrors.current_password?.[0]) {
        setPasswordErrors({ current_password: backendErrors.current_password[0] })
      } else if (backendErrors.confirm_new_password?.[0]) {
        setPasswordErrors({ confirm_new_password: backendErrors.confirm_new_password[0] })
      } else if (backendErrors.new_password?.[0]) {
        setPasswordErrors({ new_password: backendErrors.new_password[0] })
      } else {
        toast.error(message || 'Failed to change password')
      }
    } finally {
      setIsChangingPassword(false)
    }
  }

  const handleDeactivate = async () => {
    try {
      setIsDeactivating(true)
      const refreshToken = localStorage.getItem('refresh_token')
      await userAPI.deactivateAccount(refreshToken)
      toast.success('Account deactivated successfully')
      setShowDeactivateModal(false)
      await logout()
      navigate('/login')
    } catch (error) {
      const message = error.response?.data?.message || 'Failed to deactivate account'
      toast.error(message)
    } finally {
      setIsDeactivating(false)
    }
  }

  const roleLabel = useMemo(() => {
    const role = user?.role || 'member'
    return role.charAt(0).toUpperCase() + role.slice(1)
  }, [user?.role])

  const roleBadgeVariant = useMemo(() => {
    const role = user?.role
    if (role === 'admin') return 'role-admin'
    if (role === 'manager') return 'role-manager'
    if (role === 'analyst') return 'role-analyst'
    if (role === 'executive') return 'role-executive'
    return 'role-default'
  }, [user?.role])

  const memberSince = useMemo(() => {
    const rawDate = user?.date_joined || user?.created_at || user?.member_since
    if (!rawDate) return 'N/A'

    const parsedDate = new Date(rawDate)
    if (Number.isNaN(parsedDate.getTime())) return 'N/A'

    return parsedDate.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }, [user])

  const passwordLastChanged = useMemo(() => {
    const rawDate = user?.password_changed_at
    if (!rawDate) return 'Never'

    const parsedDate = new Date(rawDate)
    if (Number.isNaN(parsedDate.getTime())) return 'Never'

    return parsedDate.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }, [user?.password_changed_at])

  const profileInitials = useMemo(() => {
    const firstInitial = profile.first_name?.trim()?.[0] || ''
    const lastInitial = profile.last_name?.trim()?.[0] || ''
    const initials = `${firstInitial}${lastInitial}`.toUpperCase()
    return initials || 'U'
  }, [profile.first_name, profile.last_name])

  const displayName = useMemo(() => {
    const first = profile.first_name?.trim() || ''
    const last = profile.last_name?.trim() || ''
    const fullName = `${first} ${last}`.trim()
    return fullName || 'Your Name'
  }, [profile.first_name, profile.last_name])

  const togglePasswordVisibility = (field) => {
    setPasswordVisibility((previous) => ({
      ...previous,
      [field]: !previous[field],
    }))
  }

  const sharedInputClass =
    'w-full rounded-xl border border-[rgba(108,92,231,0.3)] bg-[rgba(255,255,255,0.04)] px-4 py-3 text-sm text-white placeholder:text-brand-200/50 transition-all duration-200 focus:border-brand-400 focus:outline-none focus:ring-[3px] focus:ring-[rgba(69,53,212,0.2)]'

  const roleBadgeClass = useMemo(() => {
    if (roleBadgeVariant === 'role-admin') return 'border border-brand-500/40 bg-brand-500/20 text-brand-300'
    if (roleBadgeVariant === 'role-manager') return 'border border-brand-600/40 bg-brand-600/20 text-brand-200'
    if (roleBadgeVariant === 'role-analyst') return 'border border-amber-500/40 bg-amber-500/20 text-amber-400'
    if (roleBadgeVariant === 'role-executive') return 'border border-fire-500/40 bg-fire-500/20 text-fire-400'
    return 'border border-brand-300/30 bg-brand-300/15 text-brand-200'
  }, [roleBadgeVariant])

  return (
    <AnimatedPage className="relative min-h-[calc(100vh-8rem)] overflow-hidden">
      <ParticleBackground />

      <div className="relative z-10 mx-auto w-full max-w-4xl">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="mb-6"
        >
          <div className="flex items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">My Profile</h1>
              <p className="mt-2 text-sm text-[var(--c-muted)]">
                Manage your personal information and account settings
              </p>
            </div>
          </div>
          <div className="mt-4 border-b border-brand-700/30" />
        </motion.div>

        <motion.div
          custom={0}
          variants={sectionCardVariants}
          initial="hidden"
          animate="visible"
          className="mb-6 rounded-2xl border border-[var(--c-border)] bg-[var(--c-card-bg)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.4)] backdrop-blur-[20px] sm:p-8"
        >
          <div className="mb-6">
            <div className="flex items-center gap-2">
              <User className="h-5 w-5 text-brand-400" />
              <h3 className="text-lg font-bold text-white">Profile Information</h3>
            </div>
            <div className="mt-2 border-b border-brand-700/20" />
          </div>

          <motion.div variants={avatarVariants} initial="hidden" animate="visible" className="text-center">
            <div className="inline-flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-brand-700 to-brand-500 font-['Syne'] text-2xl font-bold text-white animate-ring-pulse">
              {profileInitials}
            </div>
            <p className="mt-4 text-base font-medium text-white">{displayName}</p>
            <span
              className={`mt-2 inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${roleBadgeClass}`}
            >
              {roleLabel}
            </span>
          </motion.div>

          <form onSubmit={handleProfileSubmit} className="mt-6 space-y-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium text-brand-300">First Name</label>
                <input
                  name="first_name"
                  type="text"
                  required
                  value={profile.first_name}
                  onChange={handleProfileChange}
                  placeholder="First name"
                  className={sharedInputClass}
                />
                {errors.first_name && <p className="mt-1 text-sm text-red-400">{errors.first_name}</p>}
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-brand-300">Last Name</label>
                <input
                  name="last_name"
                  type="text"
                  required
                  value={profile.last_name}
                  onChange={handleProfileChange}
                  placeholder="Last name"
                  className={sharedInputClass}
                />
                {errors.last_name && <p className="mt-1 text-sm text-red-400">{errors.last_name}</p>}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium text-brand-300">Date of Birth</label>
                <input
                  name="date_of_birth"
                  type="date"
                  value={profile.date_of_birth || ''}
                  onChange={handleProfileChange}
                  className={sharedInputClass}
                />
                {errors.date_of_birth && <p className="mt-1 text-sm text-red-400">{errors.date_of_birth}</p>}
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-brand-300">Email Address</label>
                <div className="relative">
                  <input
                    name="email"
                    type="email"
                    value={profile.email}
                    disabled
                    className="w-full cursor-not-allowed rounded-xl border border-dashed border-[rgba(108,92,231,0.2)] bg-[rgba(255,255,255,0.02)] px-4 py-3 pr-10 text-sm text-[var(--c-muted)]"
                  />
                  <Lock className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-brand-300/70" />
                </div>
                <p className="mt-2 text-xs text-[var(--c-muted)]">Email address cannot be changed</p>
              </div>
            </div>

            <div>
              <label htmlFor="home_address" className="mb-2 block text-sm font-medium text-brand-300">
                Home Address
              </label>
              <div className="relative">
                <MapPin className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-brand-300/70" />
                <textarea
                  id="home_address"
                  name="home_address"
                  rows={3}
                  value={profile.home_address}
                  onChange={handleProfileChange}
                  className={`${sharedInputClass} resize-none pl-9`}
                  placeholder="Enter your home address"
                />
              </div>
            </div>

            <div className="mt-6 flex flex-wrap justify-end gap-3 border-t border-brand-700/20 pt-4">
              <motion.button
                type="button"
                onClick={loadProfile}
                whileTap={{ scale: 0.97 }}
                className="inline-flex items-center gap-2 rounded-xl border border-[rgba(108,92,231,0.25)] bg-[rgba(255,255,255,0.04)] px-5 py-2.5 text-sm text-[var(--c-muted)] transition-all duration-200 hover:border-brand-400/50 hover:bg-[rgba(255,255,255,0.07)] hover:text-white"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                <span>Reset Changes</span>
              </motion.button>

              <motion.button
                type="submit"
                whileHover={{ scale: 1.03, boxShadow: 'var(--glow-purple)' }}
                whileTap={{ scale: 0.97 }}
                disabled={isLoading}
                className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#4535d4,#ff2d78)] px-6 py-2.5 text-sm font-medium text-white transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Saving...</span>
                  </>
                ) : (
                  <>
                    <Save className="h-3.5 w-3.5" />
                    <span>Save Changes</span>
                  </>
                )}
              </motion.button>
            </div>
          </form>
        </motion.div>

        <motion.div
          custom={1}
          variants={sectionCardVariants}
          initial="hidden"
          animate="visible"
          className="mb-6 rounded-2xl border border-[var(--c-border)] bg-[var(--c-card-bg)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.4)] backdrop-blur-[20px] sm:p-8"
        >
          <div className="mb-6">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-brand-400" />
              <h3 className="text-lg font-bold text-white">Security</h3>
            </div>
            <div className="mt-2 border-b border-brand-700/20" />
          </div>

          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium text-white">Password</p>
              <p className="mt-1 text-xs text-[var(--c-muted)]">Last updated: {passwordLastChanged}</p>
            </div>

            <motion.button
              onClick={() => setShowChangePasswordModal(true)}
              whileTap={{ scale: 0.97 }}
              className="inline-flex items-center gap-2 rounded-xl border border-[rgba(255,45,120,0.35)] bg-[rgba(255,45,120,0.08)] px-5 py-2.5 text-sm text-fire-400 transition-all duration-200 hover:border-fire-400 hover:bg-[rgba(255,45,120,0.15)] hover:text-white hover:shadow-[var(--glow-pink)]"
            >
              <KeyRound className="h-3.5 w-3.5 text-fire-400" />
              <span>Change Password</span>
            </motion.button>
          </div>
        </motion.div>

        <motion.div
          custom={2}
          variants={sectionCardVariants}
          initial="hidden"
          animate="visible"
          className="mb-6 rounded-2xl border border-[var(--c-border)] bg-[var(--c-card-bg)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.4)] backdrop-blur-[20px] sm:p-8"
        >
          <div className="mb-6">
            <div className="flex items-center gap-2">
              <Info className="h-5 w-5 text-brand-400" />
              <h3 className="text-lg font-bold text-white">Account Information</h3>
            </div>
            <div className="mt-2 border-b border-brand-700/20" />
          </div>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <motion.div
              custom={0}
              variants={infoItemVariants}
              initial="hidden"
              animate="visible"
              className="rounded-xl border border-[rgba(108,92,231,0.15)] bg-[rgba(255,255,255,0.02)] p-4"
            >
              <p className="mb-1 text-xs uppercase tracking-wide text-[var(--c-muted)]">Role</p>
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${roleBadgeClass}`}
              >
                {roleLabel}
              </span>
            </motion.div>

            <motion.div
              custom={1}
              variants={infoItemVariants}
              initial="hidden"
              animate="visible"
              className="rounded-xl border border-[rgba(108,92,231,0.15)] bg-[rgba(255,255,255,0.02)] p-4"
            >
              <p className="mb-1 text-xs uppercase tracking-wide text-[var(--c-muted)]">Account Status</p>
              <span
                className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium ${
                  user?.is_active
                    ? 'border-[rgba(34,197,94,0.3)] bg-[rgba(34,197,94,0.15)] text-[#4ade80]'
                    : 'border-rose-500/30 bg-rose-500/15 text-rose-300'
                }`}
              >
                {user?.is_active && <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />}
                {user?.is_active ? 'Active' : 'Suspended'}
              </span>
            </motion.div>

            <motion.div
              custom={2}
              variants={infoItemVariants}
              initial="hidden"
              animate="visible"
              className="rounded-xl border border-[rgba(108,92,231,0.15)] bg-[rgba(255,255,255,0.02)] p-4"
            >
              <p className="mb-1 text-xs uppercase tracking-wide text-[var(--c-muted)]">Email Verified</p>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
                  user?.is_verified
                    ? 'border-brand-300/30 bg-brand-300/15 text-brand-200'
                    : 'border-amber-500/30 bg-amber-500/15 text-amber-400'
                }`}
              >
                {user?.is_verified && <CheckCircle2 className="h-3 w-3" />}
                {user?.is_verified ? 'Verified' : 'Pending'}
              </span>
            </motion.div>

            <motion.div
              custom={3}
              variants={infoItemVariants}
              initial="hidden"
              animate="visible"
              className="rounded-xl border border-[rgba(108,92,231,0.15)] bg-[rgba(255,255,255,0.02)] p-4"
            >
              <p className="mb-1 text-xs uppercase tracking-wide text-[var(--c-muted)]">Member Since</p>
              <p className="text-sm font-medium text-white">{memberSince}</p>
            </motion.div>
          </div>
        </motion.div>

        <motion.div
          custom={3}
          variants={sectionCardVariants}
          initial="hidden"
          animate="visible"
          className="mb-6 rounded-2xl border border-[rgba(255,45,120,0.25)] bg-[rgba(30,5,15,0.65)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.4)] backdrop-blur-[20px] sm:p-8"
        >
          <div className="mb-6">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-fire-500" />
              <h3 className="text-lg font-bold text-fire-400">Danger Zone</h3>
            </div>
            <div className="mt-2 border-b border-brand-700/20" />
          </div>

          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="max-w-sm">
              <p className="text-sm font-medium text-white">Deactivate Account</p>
              <p className="mt-1 text-xs text-[var(--c-muted)]">
                This action is permanent and cannot be undone. All your data will be lost.
              </p>
            </div>

            <motion.button
              onClick={() => setShowDeactivateModal(true)}
              whileTap={{ scale: 0.97 }}
              className="inline-flex items-center gap-2 rounded-xl border border-[rgba(255,45,120,0.4)] bg-[rgba(255,45,120,0.08)] px-5 py-2.5 text-sm text-fire-400 transition-all duration-200 hover:border-fire-500 hover:bg-[rgba(255,45,120,0.18)] hover:text-white hover:shadow-[var(--glow-pink)]"
            >
              <PowerOff className="h-3.5 w-3.5" />
              <span>Deactivate Account</span>
            </motion.button>
          </div>
        </motion.div>
      </div>

      <AnimatePresence>
        {showChangePasswordModal && (
          <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="absolute inset-0 bg-black/70 backdrop-blur-sm"
              onClick={() => setShowChangePasswordModal(false)}
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 30 }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              className="relative z-10 w-full max-w-md rounded-2xl border border-[var(--c-border)] bg-[var(--c-card-bg)] p-8 shadow-[0_25px_80px_rgba(0,0,0,0.6)] backdrop-blur-2xl"
            >
              <button
                onClick={() => setShowChangePasswordModal(false)}
                className="absolute right-4 top-4 text-brand-300/70 transition-colors hover:text-white"
                aria-label="Close change password modal"
              >
                <X className="h-5 w-5" />
              </button>

              <div className="text-center">
                <motion.div
                  initial={{ opacity: 0, scale: 0.7, y: 10 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                  className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-brand-700 to-brand-500"
                >
                  <KeyRound className="h-6 w-6 text-white" />
                </motion.div>
                <h3 className="mt-4 text-xl font-bold text-white">Change Password</h3>
              </div>

              <form onSubmit={handleChangePassword} className="mt-6 space-y-4">
                <motion.div
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0, duration: 0.35 }}
                >
                  <label className="mb-2 block text-sm font-medium text-brand-300">Current Password</label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-brand-300/70" />
                    <input
                      name="current_password"
                      type={passwordVisibility.current_password ? 'text' : 'password'}
                      value={passwordForm.current_password}
                      onChange={handlePasswordInputChange}
                      required
                      className={`${sharedInputClass} pl-9 pr-10`}
                    />
                    <button
                      type="button"
                      onClick={() => togglePasswordVisibility('current_password')}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-brand-300/70 transition-colors hover:text-white"
                      aria-label="Toggle current password visibility"
                    >
                      {passwordVisibility.current_password ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                  {passwordErrors.current_password && (
                    <p className="mt-1 text-sm text-red-400">{passwordErrors.current_password}</p>
                  )}
                </motion.div>

                <motion.div
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.07, duration: 0.35 }}
                >
                  <label className="mb-2 block text-sm font-medium text-brand-300">New Password</label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-brand-300/70" />
                    <input
                      name="new_password"
                      type={passwordVisibility.new_password ? 'text' : 'password'}
                      value={passwordForm.new_password}
                      onChange={handlePasswordInputChange}
                      required
                      className={`${sharedInputClass} pl-9 pr-10`}
                    />
                    <button
                      type="button"
                      onClick={() => togglePasswordVisibility('new_password')}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-brand-300/70 transition-colors hover:text-white"
                      aria-label="Toggle new password visibility"
                    >
                      {passwordVisibility.new_password ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  {passwordErrors.new_password && <p className="mt-1 text-sm text-red-400">{passwordErrors.new_password}</p>}
                </motion.div>

                <motion.div
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.14, duration: 0.35 }}
                >
                  <label className="mb-2 block text-sm font-medium text-brand-300">Confirm New Password</label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-brand-300/70" />
                    <input
                      name="confirm_new_password"
                      type={passwordVisibility.confirm_new_password ? 'text' : 'password'}
                      value={passwordForm.confirm_new_password}
                      onChange={handlePasswordInputChange}
                      required
                      className={`${sharedInputClass} pl-9 pr-10`}
                    />
                    <button
                      type="button"
                      onClick={() => togglePasswordVisibility('confirm_new_password')}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-brand-300/70 transition-colors hover:text-white"
                      aria-label="Toggle confirm password visibility"
                    >
                      {passwordVisibility.confirm_new_password ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                  {passwordErrors.confirm_new_password && (
                    <p className="mt-1 text-sm text-red-400">{passwordErrors.confirm_new_password}</p>
                  )}
                </motion.div>

                <motion.button
                  type="submit"
                  whileHover={{ scale: 1.03, boxShadow: 'var(--glow-purple)' }}
                  whileTap={{ scale: 0.97 }}
                  disabled={isChangingPassword}
                  className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[linear-gradient(135deg,#4535d4,#ff2d78)] px-6 py-3 text-sm font-medium text-white transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {isChangingPassword ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Updating...</span>
                    </>
                  ) : (
                    <span>Update Password</span>
                  )}
                </motion.button>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showDeactivateModal && (
          <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="absolute inset-0 bg-black/70 backdrop-blur-sm"
              onClick={() => setShowDeactivateModal(false)}
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 30 }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              className="relative z-10 w-full max-w-md rounded-2xl border border-[var(--c-border)] bg-[var(--c-card-bg)] p-8 shadow-[0_25px_80px_rgba(0,0,0,0.6)] backdrop-blur-2xl"
            >
              <button
                onClick={() => setShowDeactivateModal(false)}
                className="absolute right-4 top-4 text-brand-300/70 transition-colors hover:text-white"
                aria-label="Close deactivate modal"
              >
                <X className="h-5 w-5" />
              </button>

              <div className="text-center">
                <motion.div
                  initial={{ opacity: 0, scale: 0.7, y: 10 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                  className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-fire-600 to-fire-500"
                >
                  <AlertTriangle className="h-6 w-6 text-white" />
                </motion.div>
                <h3 className="mt-4 text-xl font-bold text-fire-400">Confirm Deactivation</h3>
                <p className="mx-auto mt-2 max-w-xs text-center text-sm text-[var(--c-muted)]">
                  This action is permanent and cannot be undone. All your data will be lost.
                </p>
              </div>

              <div className="mt-6 flex flex-wrap justify-center gap-3">
                <motion.button
                  onClick={() => setShowDeactivateModal(false)}
                  whileTap={{ scale: 0.97 }}
                  disabled={isDeactivating}
                  className="inline-flex items-center justify-center rounded-xl border border-[rgba(108,92,231,0.25)] bg-[rgba(255,255,255,0.04)] px-6 py-2.5 text-sm text-[var(--c-muted)] transition-all duration-200 hover:border-brand-400/50 hover:bg-[rgba(255,255,255,0.07)] hover:text-white disabled:cursor-not-allowed disabled:opacity-70"
                >
                  Cancel
                </motion.button>

                <motion.button
                  onClick={handleDeactivate}
                  whileHover={{ scale: 1.02, boxShadow: 'var(--glow-pink)' }}
                  whileTap={{ scale: 0.97 }}
                  disabled={isDeactivating}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-[linear-gradient(135deg,#e84393,#ff2d78)] px-6 py-2.5 text-sm font-medium text-white transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {isDeactivating ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Deactivating...</span>
                    </>
                  ) : (
                    <span>Deactivate</span>
                  )}
                </motion.button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </AnimatedPage>
  )
}

export default Profile
