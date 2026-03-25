import { X } from 'lucide-react'
import { useEffect } from 'react'

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
  
  if (!isOpen) return null
  
  const sizes = {
    sm: 'max-w-md',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
  }
  
  return (
    <div className={`fixed inset-0 z-50 ${overlayScrollable ? 'overflow-y-auto' : 'overflow-hidden'}`}>
      <div className="flex min-h-screen items-center justify-center p-4">
        {/* Backdrop */}
        <div 
          className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
          onClick={onClose}
        />
        
        {/* Modal */}
        <div
          className={`relative flex w-full flex-col rounded-xl bg-white shadow-2xl ${sizes[size]} max-h-[90vh] overflow-hidden ${panelClassName}`}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b">
            <h3 className="text-xl font-semibold text-gray-900">{title}</h3>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
          </div>
          
          {/* Content */}
          <div
            className={`flex-1 min-h-0 p-6 ${scrollContent ? 'overflow-y-auto' : 'overflow-hidden'} ${contentClassName}`}
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}

export default Modal

