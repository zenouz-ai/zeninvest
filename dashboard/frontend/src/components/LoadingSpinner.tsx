export function LoadingSpinner({ className = '' }: { className?: string }) {
  return (
    <div className={`flex items-center justify-center h-64 ${className}`}>
      <div
        className="h-8 w-8 rounded-full border-2 border-terminal-border border-t-neutral animate-spin"
        role="status"
        aria-label="Loading"
      />
    </div>
  )
}
