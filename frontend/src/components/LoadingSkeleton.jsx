import { motion } from 'framer-motion'

function LoadingSkeleton({ type = 'text', count = 1, className = '' }) {
  const shimmer = {
    initial: { backgroundPosition: '-200% 0' },
    animate: {
      backgroundPosition: '200% 0',
      transition: {
        repeat: Infinity,
        duration: 1.5,
        ease: 'linear',
      },
    },
  }

  const renderSkeleton = () => {
    switch (type) {
      case 'text':
        return (
          <motion.div
            variants={shimmer}
            initial="initial"
            animate="animate"
            className={`h-4 rounded bg-gradient-to-r from-brand-700/30 via-brand-600/40 to-brand-700/30 ${className}`}
            style={{ backgroundSize: '200% 100%' }}
          />
        )
      case 'title':
        return (
          <motion.div
            variants={shimmer}
            initial="initial"
            animate="animate"
            className={`h-8 rounded bg-gradient-to-r from-brand-700/30 via-brand-600/40 to-brand-700/30 ${className}`}
            style={{ backgroundSize: '200% 100%' }}
          />
        )
      case 'circle':
        return (
          <motion.div
            variants={shimmer}
            initial="initial"
            animate="animate"
            className={`h-12 w-12 rounded-full bg-gradient-to-r from-brand-700/30 via-brand-600/40 to-brand-700/30 ${className}`}
            style={{ backgroundSize: '200% 100%' }}
          />
        )
      case 'card':
        return (
          <motion.div
            variants={shimmer}
            initial="initial"
            animate="animate"
            className={`h-32 rounded-lg bg-gradient-to-r from-brand-700/30 via-brand-600/40 to-brand-700/30 ${className}`}
            style={{ backgroundSize: '200% 100%' }}
          />
        )
      case 'input':
        return (
          <motion.div
            variants={shimmer}
            initial="initial"
            animate="animate"
            className={`h-10 rounded-lg bg-gradient-to-r from-brand-700/30 via-brand-600/40 to-brand-700/30 ${className}`}
            style={{ backgroundSize: '200% 100%' }}
          />
        )
      default:
        return null
    }
  }

  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index}>{renderSkeleton()}</div>
      ))}
    </div>
  )
}

export default LoadingSkeleton

