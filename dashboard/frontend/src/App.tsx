import { Suspense, lazy, useEffect, useRef, useState, type ReactElement } from 'react'
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AlertBanner } from './components/AlertBanner'
import { LoadingSpinner } from './components/LoadingSpinner'
import { useDashboardAuthRequired } from './hooks/useDashboardAuthRequired'
import { useSSE } from './hooks/useSSE'
import { authApi, type AuthSession } from './api/client'
import { getMoreNavigationItems, getPrimaryNavigationItems } from './navigation'
import { clearDashboardAuthRequired } from './utils/authErrorBridge'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Universe = lazy(() => import('./pages/Universe'))
const RunHistory = lazy(() => import('./pages/RunHistory'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const PublicUniverse = lazy(() => import('./pages/PublicUniverse'))
const PublicRuns = lazy(() => import('./pages/PublicRuns'))
const PublicPortfolio = lazy(() => import('./pages/PublicPortfolio'))
const PublicOpportunity = lazy(() => import('./pages/PublicOpportunity'))
const PublicOrderManagement = lazy(() => import('./pages/PublicOrderManagement'))
const PublicCosts = lazy(() => import('./pages/PublicCosts'))
const PublicChat = lazy(() => import('./pages/PublicChat'))
const PublicEvolution = lazy(() => import('./pages/PublicEvolution'))
const Opportunity = lazy(() => import('./pages/Opportunity'))
const OrderManagement = lazy(() => import('./pages/OrderManagement'))
const Costs = lazy(() => import('./pages/Costs'))
const Roadmap = lazy(() => import('./pages/Roadmap'))
const WorldNews = lazy(() => import('./pages/WorldNews'))
const Chat = lazy(() => import('./pages/Chat'))
const Evolution = lazy(() => import('./pages/Evolution'))
const PublicOverview = lazy(() => import('./pages/PublicOverview'))
const LoginPage = lazy(() => import('./pages/LoginPage'))

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

function RouteFallback() {
  return <LoadingSpinner className="h-48" />
}

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
  const items = getMoreNavigationItems(authenticated)

  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  if (items.length === 0) return null

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
          {items.map((item) => (
            <NavLink key={item.to} to={item.to} className={dropdownLinkClass} onClick={() => setOpen(false)}>
              {item.label}
            </NavLink>
          ))}
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
  const primaryNavItems = getPrimaryNavigationItems(authenticated)
  const mobileNavItems = [...primaryNavItems, ...getMoreNavigationItems(authenticated)]

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
                {primaryNavItems.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.to === '/'} className={navLinkClass}>
                    {item.label}
                  </NavLink>
                ))}
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
              {mobileNavItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={mobileLinkClass}
                  onClick={() => setMobileMenuOpen(false)}
                >
                  {item.mobileLabel ?? item.label}
                </NavLink>
              ))}
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
        <Suspense fallback={<RouteFallback />}>
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
            <Route path="/universe" element={authenticated ? <Universe /> : <PublicUniverse />} />
            <Route path="/universe/:ticker" element={authenticated ? <Universe /> : <PublicUniverse />} />
            <Route path="/runs" element={authenticated ? <RunHistory /> : <PublicRuns />} />
            <Route path="/portfolio" element={authenticated ? <Portfolio /> : <PublicPortfolio />} />
            <Route path="/opportunity" element={authenticated ? <Opportunity /> : <PublicOpportunity />} />
            <Route path="/orders" element={authenticated ? <OrderManagement /> : <PublicOrderManagement />} />
            <Route path="/costs" element={authenticated ? <Costs /> : <PublicCosts />} />
            <Route path="/commands" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={authenticated ? <Chat /> : <PublicChat />} />
            <Route path="/evolution" element={authenticated ? <Evolution /> : <PublicEvolution />} />
            <Route path="/world-news" element={<WorldNews publicView={!authenticated} />} />
            <Route path="*" element={<Navigate to={homePath} replace />} />
          </Routes>
        </Suspense>
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
