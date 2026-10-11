function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="text-center py-12">
      {Icon && (
        <div className="inline-flex items-center justify-center w-16 h-16 bg-[rgba(255,255,255,0.07)] rounded-full mb-4">
          <Icon className="w-8 h-8 text-brand-300/60" />
        </div>
      )}
      <h3 className="text-lg font-medium text-white mb-2">{title}</h3>
      {description && (
        <p className="text-[var(--c-muted)] mb-6 max-w-md mx-auto">{description}</p>
      )}
      {action}
    </div>
  )
}

export default EmptyState

