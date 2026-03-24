import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '../api/client'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { StatusPill } from '../components/StatusPill'

interface LoginPageProps {
  onLoginSuccess: () => Promise<void> | void
}

export default function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  const next = params.get('next') || '/dashboard'

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await authApi.login(username.trim(), password)
      await onLoginSuccess()
      navigate(next, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="OPERATOR"
        title="Sign In"
        description="Operator controls require a server-issued session. Login is blocked on plain HTTP except localhost development mode."
        titleMeta={<StatusPill label="Private Access" variant="warning" />}
      />

      <Panel className="max-w-md space-y-5">
        <div className="space-y-2">
          <div className="label-mono">Authenticated Session</div>
          <p className="text-sm leading-6 text-terminal-text-muted">
            This gateway issues an operator session before exposing live portfolio, execution, and control routes.
          </p>
        </div>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="dashboard-username" className="block text-sm text-terminal-text-dim mb-1">
              Username
            </label>
            <input
              id="dashboard-username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-panel border border-terminal-border bg-terminal-bg/70 px-3 py-2.5 text-sm text-terminal-text focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="Operator username"
              required
            />
          </div>

          <div>
            <label htmlFor="dashboard-password" className="block text-sm text-terminal-text-dim mb-1">
              Password
            </label>
            <input
              id="dashboard-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-panel border border-terminal-border bg-terminal-bg/70 px-3 py-2.5 text-sm text-terminal-text focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="Operator password"
              required
            />
          </div>

          {error && (
            <p className="text-sm text-loss">{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="btn-secondary disabled:opacity-60"
          >
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </Panel>
    </div>
  )
}
