function Card({ children, className = '', title, subtitle, actions }) {
  return (
    <div
      className={`card rounded-2xl border border-[var(--c-border)] bg-[var(--c-card-bg)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.4)] backdrop-blur-xl transition-all duration-300 sm:p-8 ${className}`}
    >
      {(title || subtitle || actions) && (
        <div className="mb-6 flex items-start justify-between border-b border-brand-700/20 pb-4">
          <div>
            {title && <h3 className="text-lg font-bold text-white">{title}</h3>}
            {subtitle && <p className="mt-1 text-sm text-brand-200">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center space-x-2">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  )
}

export default Card

