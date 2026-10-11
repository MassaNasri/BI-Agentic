import { X } from 'lucide-react'
import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

function Modal({
  isOpen,
  onClose,
  title,
  children,
  size = 'md',
  panelClassName = '',
  contentClassName = '',
  scrollContent = true,
  overlayScrollable = true,
}) {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = 'unset'
    }
    
    return () => {
      document.body.style.overflow = 'unset'
    }
  }, [isOpen])

  const sizes = {
    sm: 'max-w-md',
    md: 'max-w-md',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <div className={`fixed inset-0 z-50 ${overlayScrollable ? 'overflow-y-auto' : 'overflow-hidden'}`}>
          <div className="flex min-h-screen items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 bg-black/70 backdrop-blur-sm"
              onClick={onClose}
            />

            <motion.div
              initial={{ opacity: 0, y: 24, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 20, scale: 0.95 }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              className={`relative flex max-h-[90vh] w-full flex-col overflow-hidden rounded-2xl border border-[var(--c-border)] bg-[var(--c-card-bg)] shadow-[0_20px_70px_rgba(0,0,0,0.5)] backdrop-blur-2xl ${sizes[size]} ${panelClassName}`}
            >
              <div className="flex items-center justify-between border-b border-brand-700/20 p-6">
                <h3 className="text-xl font-bold text-white">{title}</h3>
                <button
                  onClick={onClose}
                  className="text-brand-300/70 transition-colors hover:text-white"
                  aria-label="Close modal"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <div
                className={`flex-1 min-h-0 p-6 ${scrollContent ? 'overflow-y-auto' : 'overflow-hidden'} ${contentClassName}`}
              >
                {children}
              </div>
            </motion.div>
          </div>
        </div>
      )}
    </AnimatePresence>
  )
}

export default Modal

