import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { KeyRound, Mail, Lock, ShieldCheck } from 'lucide-react'
import { authAPI } from '../../api/endpoints'
import { Button, ErrorAlert, Input } from '../../components'

const STEP_REQUEST = 'request'
const STEP_VERIFY = 'verify'
const STEP_RESET = 'reset'
const STEP_DONE = 'done'

function ForgotPassword() {
  const navigate = useNavigate()
  const [step, setStep] = useState(STEP_REQUEST)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [formData, setFormData] = useState({
    email: '',
    code: '',
    newPassword: '',
    confirmPassword: '',
  })
  const [resetToken, setResetToken] = useState('')

  const stepTitle = useMemo(() => {
    if (step === STEP_REQUEST) return 'Forgot Password'
    if (step === STEP_VERIFY) return 'Verify Code'
    if (step === STEP_RESET) return 'Set New Password'
    return 'Password Updated'
  }, [step])

  const stepDescription = useMemo(() => {
    if (step === STEP_REQUEST) return 'Enter your email to receive a reset code.'
    if (step === STEP_VERIFY) return 'Enter the verification code sent to your email.'
    if (step === STEP_RESET) return 'Choose a new password for your account.'
    return 'Your password has been reset successfully.'
  }, [step])

  const handleChange = (event) => {
    const { name, value } = event.target
    setFormData((previous) => ({ ...previous, [name]: value }))
    if (errorMessage) {
      setErrorMessage('')
    }
  }

  const handleRequestCode = async (event) => {
    event.preventDefault()
    if (!formData.email.trim()) {
      setErrorMessage('Email is required.')
      return
    }

    try {
      setIsLoading(true)
      await authAPI.requestPasswordResetCode(formData.email.trim())
      setStep(STEP_VERIFY)
    } catch (error) {
      setErrorMessage(error.response?.data?.message || 'Failed to request verification code.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleVerifyCode = async (event) => {
    event.preventDefault()
    if (!formData.code.trim()) {
      setErrorMessage('Verification code is required.')
      return
    }

    try {
      setIsLoading(true)
      const response = await authAPI.verifyPasswordResetCode(formData.email.trim(), formData.code.trim())
      const token = response?.data?.reset_token
      if (!token) {
        setErrorMessage('Verification succeeded, but no reset token was returned.')
        return
      }
      setResetToken(token)
      setStep(STEP_RESET)
    } catch (error) {
      const message =
        error.response?.data?.errors?.code?.[0] ||
        error.response?.data?.message ||
        'Verification failed.'
      setErrorMessage(message)
    } finally {
      setIsLoading(false)
    }
  }

  const handleResetPassword = async (event) => {
    event.preventDefault()
    if (!formData.newPassword) {
      setErrorMessage('New password is required.')
      return
    }
    if (formData.newPassword !== formData.confirmPassword) {
      setErrorMessage('New password and confirmation do not match.')
      return
    }

    try {
      setIsLoading(true)
      await authAPI.resetPassword(resetToken, formData.newPassword, formData.confirmPassword)
      setStep(STEP_DONE)
      setTimeout(() => {
        navigate('/login')
      }, 1500)
    } catch (error) {
      const message =
        error.response?.data?.errors?.new_password?.[0] ||
        error.response?.data?.errors?.reset_token?.[0] ||
        error.response?.data?.message ||
        'Failed to reset password.'
      setErrorMessage(message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 via-blue-50 to-indigo-50 flex items-center justify-center px-6 py-12">
      <div className="card max-w-md w-full bg-white/90 backdrop-blur-sm shadow-2xl">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-primary-100 to-blue-100 rounded-full mb-4 shadow-lg">
            <KeyRound className="w-8 h-8 text-primary-600" />
          </div>
          <h2 className="text-3xl font-bold text-gray-900">{stepTitle}</h2>
          <p className="mt-2 text-gray-600">{stepDescription}</p>
        </div>

        {errorMessage && (
          <div className="mb-6">
            <ErrorAlert message={errorMessage} type="error" onClose={() => setErrorMessage('')} />
          </div>
        )}

        {step === STEP_REQUEST && (
          <form onSubmit={handleRequestCode} className="space-y-6">
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
            <Button type="submit" loading={isLoading} fullWidth>
              {isLoading ? 'Sending code...' : 'Send Verification Code'}
            </Button>
          </form>
        )}

        {step === STEP_VERIFY && (
          <form onSubmit={handleVerifyCode} className="space-y-6">
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
            <Input
              label="Verification Code"
              icon={ShieldCheck}
              name="code"
              type="text"
              required
              value={formData.code}
              onChange={handleChange}
              placeholder="Enter 6-digit code"
            />
            <Button type="submit" loading={isLoading} fullWidth>
              {isLoading ? 'Verifying...' : 'Verify Code'}
            </Button>
          </form>
        )}

        {step === STEP_RESET && (
          <form onSubmit={handleResetPassword} className="space-y-6">
            <Input
              label="New Password"
              icon={Lock}
              name="newPassword"
              type="password"
              required
              value={formData.newPassword}
              onChange={handleChange}
              placeholder="Enter new password"
            />
            <Input
              label="Confirm New Password"
              icon={Lock}
              name="confirmPassword"
              type="password"
              required
              value={formData.confirmPassword}
              onChange={handleChange}
              placeholder="Confirm new password"
            />
            <Button type="submit" loading={isLoading} fullWidth>
              {isLoading ? 'Resetting...' : 'Reset Password'}
            </Button>
          </form>
        )}

        {step === STEP_DONE && (
          <div className="text-center text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg p-4">
            Password reset successful. Redirecting to login...
          </div>
        )}

        <div className="mt-6 text-center">
          <Link to="/login" className="text-primary-600 hover:text-primary-700 font-semibold transition-colors">
            Back to Sign In
          </Link>
        </div>
      </div>
    </div>
  )
}

export default ForgotPassword
