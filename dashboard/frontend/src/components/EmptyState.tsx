export function EmptyState({
  message,
  hint,
  className = '',
}: {
  message: string
  hint?: string
  className?: string
}) {
  return (
    <div
      className={`text-center py-8 text-terminal-text-dim ${className}`}
      role="status"
    >
      <p className="text-sm">{message}</p>
      {hint && <p className="text-xs mt-1 opacity-80">{hint}</p>}
    </div>
  )
}
