import { useEffect, useRef, useState, type ReactElement } from 'react'
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Universe from './pages/Universe'
import RunHistory from './pages/RunHistory'
import Portfolio from './pages/Portfolio'
import Opportunity from './pages/Opportunity'
import OrderManagement from './pages/OrderManagement'
import Costs from './pages/Costs'
import Roadmap from './pages/Roadmap'
import WorldNews from './pages/WorldNews'
import Commands from './pages/Commands'
import Evolution from './pages/Evolution'
import PublicOverview from './pages/PublicOverview'
import LoginPage from './pages/LoginPage'
import { AlertBanner } from './components/AlertBanner'
import { useDashboardAuthRequired } from './hooks/useDashboardAuthRequired'
import { useSSE } from './hooks/useSSE'
import { authApi, type AuthSession } from './api/client'
import { clearDashboardAuthRequired } from './utils/authErrorBridge'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `inline-flex items-center px-3 py-1.5 text-sm font-medium rounded-full transition-all focus:outline-none focus:ring-2 focus:ring-cyan/40 focus:ring-offset-2 focus:ring-offset-transparent ${
    isActive
      ? 'bg-cyan/10 text-cyan border border-cyan/25 shadow-glow/30'
      : 'text-terminal-text-muted hover:text-terminal-text hover:bg-white/5 border border-transparent'
  }`

const mobileBase = 'block px-3 py-2 text-base font-medium rounded-panel'
const mobileLinkClass = ({ isActive }: { isActive: boolean }) =>
  `${mobileBase} focus:outline-none focus:ring-2 focus:ring-cyan/40 focus:ring-inset ${
    isActive ? 'bg-cyan/10 text-cyan' : 'text-terminal-text-muted hover:bg-white/5 hover:text-terminal-text'
  }`

const dropdownLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block px-4 py-2 text-sm transition-colors rounded-xs ${
    isActive ? 'text-cyan bg-cyan/10' : 'text-terminal-text-muted hover:text-terminal-text hover:bg-white/5'
  }`

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

function ProtectedRoute({
  authenticated,
  resolved,
  children,
}: {
  authenticated: boolean
  resolved: boolean
  children: ReactElement
}) {
  const location = useLocation()
  if (!resolved) {
    return <div className="text-sm text-terminal-text-dim">Loading operator session…</div>
  }
  if (!authenticated) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return children
}

function MoreDropdown({ authenticated }: { authenticated: boolean }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  if (!authenticated) return null

  return (
    <div ref={ref} className="relative inline-flex items-center">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className={`inline-flex items-center px-3 py-1.5 text-sm font-medium rounded-full transition-all focus:outline-none focus:ring-2 focus:ring-cyan/40 focus:ring-offset-2 focus:ring-offset-transparent border ${
          open
            ? 'bg-cyan/10 text-cyan border-cyan/25'
            : 'text-terminal-text-muted hover:text-terminal-text hover:bg-white/5 border-transparent'
        }`}
      >
        More
        <svg className={`ml-1 w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div
          className="absolute top-full left-0 mt-2 w-44 border border-terminal-border-strong rounded-panel py-1 z-50"
          style={{
            background: 'rgba(14, 16, 28, 0.96)',
            boxShadow: 'var(--shadow-panel)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <NavLink to="/opportunity" className={dropdownLinkClass} onClick={() => setOpen(false)}>Opportunity</NavLink>
          <NavLink to="/orders" className={dropdownLinkClass} onClick={() => setOpen(false)}>Order Mgmt</NavLink>
          <NavLink to="/commands" className={dropdownLinkClass} onClick={() => setOpen(false)}>Commands</NavLink>
          <NavLink to="/evolution" className={dropdownLinkClass} onClick={() => setOpen(false)}>Evolution</NavLink>
          <NavLink to="/world-news" className={dropdownLinkClass} onClick={() => setOpen(false)}>World News</NavLink>
          <NavLink to="/costs" className={dropdownLinkClass} onClick={() => setOpen(false)}>Costs</NavLink>
        </div>
      )}
    </div>
  )
}

function DashboardShell() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [authStatus, setAuthStatus] = useState<AuthStatus>('loading')
  const [authSession, setAuthSession] = useState<AuthSession | null>(null)
  const authRequired = useDashboardAuthRequired()

  const refreshAuth = async () => {
    const session = await authApi.me()
    setAuthSession(session)
    setAuthStatus(session.authenticated ? 'authenticated' : 'unauthenticated')
    if (session.authenticated) {
      clearDashboardAuthRequired()
    }
  }

  useEffect(() => {
    void refreshAuth().catch(() => {
      setAuthSession(null)
      setAuthStatus('unauthenticated')
    })
  }, [])

  useEffect(() => {
    if (!authRequired) return
    setAuthSession(null)
    setAuthStatus('unauthenticated')
  }, [authRequired])

  const authenticated = authStatus === 'authenticated'
  const authResolved = authStatus !== 'loading'

  const { events: sseEvents, connectionState: sseConnectionState, sseDisconnectedAlert } = useSSE({
    enabled: authenticated,
  })

  const handleLogout = async () => {
    await authApi.logout()
    setAuthSession(null)
    setAuthStatus('unauthenticated')
    clearDashboardAuthRequired()
  }

  const homePath = authenticated ? '/dashboard' : '/'

  return (
    <div className="relative min-h-screen overflow-hidden bg-terminal-bg">
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute left-[-10rem] top-[-9rem] h-[24rem] w-[24rem] rounded-full bg-violet/14 blur-3xl" />
        <div className="absolute right-[-8rem] top-28 h-[22rem] w-[22rem] rounded-full bg-cyan/10 blur-3xl" />
        <div className="absolute bottom-[-10rem] left-1/3 h-[24rem] w-[24rem] rounded-full bg-emerald/8 blur-3xl" />
        <div
          className="absolute inset-0 opacity-70"
          style={{
            background:
              'radial-gradient(circle at top, rgba(255,255,255,0.06), transparent 26%), linear-gradient(180deg, rgba(6,6,10,0.08), rgba(6,6,10,0.5))',
          }}
        />
      </div>

      <div className="relative z-10">
      <nav
        className="sticky top-0 z-40 border-b border-terminal-border-strong"
        style={{
          background: 'rgba(6, 6, 10, 0.80)',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
        }}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-14">
            <div className="flex items-center gap-6">
              <Link
                to={homePath}
                className="flex items-center gap-2.5 py-2 text-xl font-semibold focus:outline-none focus:ring-2 focus:ring-cyan/40 focus:ring-offset-2 focus:ring-offset-transparent rounded-xs"
              >
                <img src="/logo.svg" alt="ZENOUZ.ai" className="h-6 w-6" />
                <span className="text-white tracking-wide font-heading font-semibold">ZENOUZ</span>
                <span className="brand-gradient-text font-body font-normal">.ai</span>
              </Link>
              <div className="hidden sm:flex sm:items-center sm:gap-1">
                {!authenticated && <NavLink to="/" end className={navLinkClass}>Overview</NavLink>}
                {authenticated && <NavLink to="/dashboard" className={navLinkClass}>Dashboard</NavLink>}
                {authenticated && <NavLink to="/universe" className={navLinkClass}>Universe</NavLink>}
                <NavLink to="/portfolio" className={navLinkClass}>Portfolio</NavLink>
                {authenticated && <NavLink to="/runs" className={navLinkClass}>Runs</NavLink>}
                {!authenticated && <NavLink to="/world-news" className={navLinkClass}>World News</NavLink>}
                <NavLink to="/roadmap" className={navLinkClass}>Roadmap</NavLink>
                <MoreDropdown authenticated={authenticated} />
              </div>
            </div>
            <div className="hidden sm:flex items-center gap-3">
              {authResolved && authenticated ? (
                <>
                  <span className="text-xs text-terminal-text-dim">Signed in as {authSession?.username ?? 'operator'}</span>
                  <button
                    type="button"
                    onClick={() => { void handleLogout() }}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-terminal-text-dim border border-terminal-border rounded-full hover:border-cyan/40 hover:text-cyan transition-all focus:outline-none focus:ring-2 focus:ring-cyan/40"
                  >
                    Sign out
                  </button>
                </>
              ) : (
                <Link
                  to="/login"
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-terminal-text-dim border border-terminal-border rounded-full hover:border-cyan/40 hover:text-cyan transition-all focus:outline-none focus:ring-2 focus:ring-cyan/40"
                >
                  Sign in
                </Link>
              )}
            </div>
            <div className="flex items-center sm:hidden">
              <button
                type="button"
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="inline-flex items-center justify-center p-2 rounded-xs text-terminal-text-muted hover:text-terminal-text hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-cyan/40 focus:ring-inset transition-colors"
                aria-expanded={mobileMenuOpen}
                aria-label="Toggle navigation menu"
              >
                <span className="sr-only">Open main menu</span>
                {mobileMenuOpen ? (
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                ) : (
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        </div>

        {mobileMenuOpen && (
          <div
            className="sm:hidden border-t border-terminal-border"
            style={{ background: 'rgba(6, 6, 10, 0.95)' }}
          >
            <div className="pt-2 pb-3 space-y-0.5 px-3">
              {!authenticated && <NavLink to="/" end className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Overview</NavLink>}
              {authenticated && <NavLink to="/dashboard" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Dashboard</NavLink>}
              {authenticated && <NavLink to="/universe" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Universe</NavLink>}
              <NavLink to="/portfolio" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Portfolio</NavLink>
              {authenticated && <NavLink to="/runs" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Run History</NavLink>}
              {authenticated && <NavLink to="/opportunity" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Opportunity</NavLink>}
              {authenticated && <NavLink to="/orders" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Order Mgmt</NavLink>}
              {authenticated && <NavLink to="/commands" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Commands</NavLink>}
              {authenticated && <NavLink to="/evolution" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Evolution</NavLink>}
              <NavLink to="/world-news" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>World News</NavLink>
              {authenticated && <NavLink to="/costs" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Costs</NavLink>}
              <NavLink to="/roadmap" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Roadmap</NavLink>
              <div className="pt-2 pb-1">
                {authenticated ? (
                  <button
                    type="button"
                    onClick={() => {
                      setMobileMenuOpen(false)
                      void handleLogout()
                    }}
                    className="btn-secondary"
                  >
                    Sign out
                  </button>
                ) : (
                  <Link to="/login" className="btn-secondary" onClick={() => setMobileMenuOpen(false)}>
                    Sign in
                  </Link>
                )}
              </div>
            </div>
          </div>
        )}
      </nav>

      {authenticated && <AlertBanner sseDisconnectedAlert={sseDisconnectedAlert} />}

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Routes>
          <Route path="/" element={<PublicOverview />} />
          <Route
            path="/login"
            element={
              authenticated
                ? <Navigate to="/dashboard" replace />
                : <LoginPage onLoginSuccess={refreshAuth} />
            }
          />
          <Route path="/roadmap" element={<Roadmap />} />
          <Route
            path="/dashboard"
            element={(
              <ProtectedRoute authenticated={authenticated} resolved={authResolved}>
                <Dashboard sseEvents={sseEvents} sseConnectionState={sseConnectionState} />
              </ProtectedRoute>
            )}
          />
          <Route path="/universe" element={<ProtectedRoute authenticated={authenticated} resolved={authResolved}><Universe /></ProtectedRoute>} />
          <Route path="/universe/:ticker" element={<ProtectedRoute authenticated={authenticated} resolved={authResolved}><Universe /></ProtectedRoute>} />
          <Route path="/runs" element={<ProtectedRoute authenticated={authenticated} resolved={authResolved}><RunHistory /></ProtectedRoute>} />
          <Route path="/portfolio" element={<Portfolio publicView={!authenticated} />} />
          <Route path="/opportunity" element={<ProtectedRoute authenticated={authenticated} resolved={authResolved}><Opportunity /></ProtectedRoute>} />
          <Route path="/orders" element={<ProtectedRoute authenticated={authenticated} resolved={authResolved}><OrderManagement /></ProtectedRoute>} />
          <Route path="/costs" element={<ProtectedRoute authenticated={authenticated} resolved={authResolved}><Costs /></ProtectedRoute>} />
          <Route path="/commands" element={<ProtectedRoute authenticated={authenticated} resolved={authResolved}><Commands /></ProtectedRoute>} />
          <Route path="/evolution" element={<ProtectedRoute authenticated={authenticated} resolved={authResolved}><Evolution /></ProtectedRoute>} />
          <Route path="/world-news" element={<WorldNews publicView={!authenticated} />} />
          <Route path="*" element={<Navigate to={homePath} replace />} />
        </Routes>
      </main>
      </div>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <DashboardShell />
    </BrowserRouter>
  )
}

export default App
