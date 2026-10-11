function Badge({ children, variant = 'info', className = '' }) {
  const variants = {
    success: 'badge-success',
    warning: 'badge-warning',
    danger: 'badge-danger',
    info: 'badge-info',
    'role-admin': 'border border-brand-500/40 bg-brand-500/20 text-brand-300',
    'role-manager': 'border border-brand-600/40 bg-brand-600/20 text-brand-200',
    'role-analyst': 'border border-amber-500/40 bg-amber-500/20 text-amber-400',
    'role-executive': 'border border-fire-500/40 bg-fire-500/20 text-fire-400',
    'role-default': 'border border-brand-300/40 bg-brand-400/15 text-brand-200',
    'status-active': 'border border-green-500/30 bg-green-500/15 text-[#4ade80]',
    'status-inactive': 'border border-red-500/30 bg-red-500/15 text-[#f87171]',
    'status-verified': 'border border-brand-300/40 bg-brand-300/20 text-brand-100',
    'status-pending': 'border border-amber-500/40 bg-amber-500/20 text-amber-400',
  }
  
  return (
    <span className={`badge ${variants[variant] || variants.info} ${className}`}>
      {children}
    </span>
  )
}

export default Badge

