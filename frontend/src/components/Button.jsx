import { Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'

/**
 * Animated Button Component
 * Features: Loading state, disabled state, multiple variants and sizes
 * Animation: Smooth hover and tap effects
 */
function Button({ 
  children, 
  variant = 'primary', 
  size = 'md', 
  loading = false, 
  disabled = false,
  fullWidth = false,
  className = '',
  ...props 
}) {
  const baseStyles = 'btn inline-flex items-center justify-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200'
  
  const variants = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    danger: 'btn-danger',
    outline:
      'rounded-xl border border-[rgba(108,92,231,0.35)] bg-transparent text-brand-300 hover:bg-[rgba(108,92,231,0.1)] hover:text-white',
    success: 'btn-primary',
  }
  
  const sizes = {
    sm: 'px-4 py-2 text-sm',
    md: 'px-5 py-2.5 text-sm',
    lg: 'px-6 py-3 text-base',
  }
  
  const widthClass = fullWidth ? 'w-full' : ''

  const hoverByVariant = {
    primary: { scale: 1.03, boxShadow: '0 0 30px rgba(69,53,212,0.5)' },
    secondary: { scale: 1.02 },
    danger: { scale: 1.02, boxShadow: '0 0 30px rgba(255,45,120,0.4)' },
    outline: { scale: 1.02 },
    success: { scale: 1.03, boxShadow: '0 0 30px rgba(69,53,212,0.5)' },
  }
  
  return (
    <motion.button
      whileHover={disabled || loading ? {} : hoverByVariant[variant] || hoverByVariant.primary}
      whileTap={disabled || loading ? {} : { scale: 0.97 }}
      transition={{ duration: 0.15, ease: 'easeOut' }}
      className={`${baseStyles} ${variants[variant]} ${sizes[size]} ${widthClass} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
        >
          <Loader2 className="w-4 h-4" />
        </motion.div>
      )}
      {children}
    </motion.button>
  )
}

export default Button

