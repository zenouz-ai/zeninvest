import { type FormEvent, useState } from 'react'

interface ChatInputProps {
  onSubmit: (message: string, mode?: string) => void
  disabled?: boolean
  placeholder?: string
}

const MODES = [
  { key: 'research', label: 'Research' },
  { key: 'trade', label: 'Trade' },
  { key: 'committee', label: 'Committee' },
  { key: 'quick', label: 'Quick' },
] as const

export function ChatInput({ onSubmit, disabled = false, placeholder }: ChatInputProps) {
  const [message, setMessage] = useState('')
  const [mode, setMode] = useState<string>('research')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = message.trim()
    if (!trimmed) return
    onSubmit(trimmed, mode)
    setMessage('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="border-t border-terminal-border bg-terminal-surface/60 p-4">
      <div className="mb-2 flex gap-1">
        {MODES.map((m) => (
          <button
            key={m.key}
            type="button"
            onClick={() => setMode(m.key)}
            className={`rounded-full px-3 py-1 text-[11px] uppercase tracking-wide transition-colors ${
              mode === m.key
                ? 'bg-cyan/20 text-cyan border border-cyan/40'
                : 'text-terminal-text-dim hover:text-terminal-text border border-transparent'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={placeholder || 'Type a message... (Enter to send, Shift+Enter for newline)'}
          rows={2}
          className="flex-1 resize-none rounded-lg border border-terminal-border bg-terminal-bg px-3 py-2 text-sm text-terminal-text placeholder:text-terminal-text-dim focus:border-cyan focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={disabled || !message.trim()}
          className="self-end rounded-lg bg-cyan/20 px-4 py-2 text-sm font-medium text-cyan transition-colors hover:bg-cyan/30 disabled:opacity-30"
        >
          Send
        </button>
      </div>
    </form>
  )
}
