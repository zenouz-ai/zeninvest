import { useState, useRef, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, NavLink } from 'react-router-dom'
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
import { AlertBanner } from './components/AlertBanner'
import { DashboardAuthBanner } from './components/DashboardAuthBanner'
import { DashboardApiKeyModal } from './components/DashboardApiKeyModal'
import { useDashboardAuthRequired } from './hooks/useDashboardAuthRequired'
import { useSSE } from './hooks/useSSE'

// Pill-style nav link — soft gradient pill active, dim text inactive
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

/** Desktop "More" dropdown for secondary nav items */
function MoreDropdown() {
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
          <NavLink to="/world-news" className={dropdownLinkClass} onClick={() => setOpen(false)}>World News</NavLink>
          <NavLink to="/costs" className={dropdownLinkClass} onClick={() => setOpen(false)}>Costs</NavLink>
          <NavLink to="/roadmap" className={dropdownLinkClass} onClick={() => setOpen(false)}>Roadmap</NavLink>
        </div>
      )}
    </div>
  )
}

function ApiKeyNavButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-terminal-text-dim border border-terminal-border rounded-full hover:border-cyan/40 hover:text-cyan transition-all focus:outline-none focus:ring-2 focus:ring-cyan/40"
      title="Set dashboard API key (localStorage)"
    >
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
      </svg>
      API key
    </button>
  )
}

function App() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [apiKeyModalOpen, setApiKeyModalOpen] = useState(false)
  const [sseReconnectNonce, setSseReconnectNonce] = useState(0)
  const authRequired = useDashboardAuthRequired()
  const { events: sseEvents, connectionState: sseConnectionState, sseDisconnectedAlert } = useSSE({
    enabled: true,
    reconnectNonce: sseReconnectNonce,
  })

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-terminal-bg">
        {/* Sticky blurred nav bar */}
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
                  to="/"
                  className="flex items-center gap-2.5 py-2 text-xl font-semibold focus:outline-none focus:ring-2 focus:ring-cyan/40 focus:ring-offset-2 focus:ring-offset-transparent rounded-xs"
                >
                  <img src="/logo.svg" alt="ZENOUZ.ai" className="h-6 w-6" />
                  <span className="text-white tracking-wide font-heading font-semibold">ZENOUZ</span>
                  <span className="brand-gradient-text font-body font-normal">.ai</span>
                </Link>
                <div className="hidden sm:flex sm:items-center sm:gap-1">
                  <NavLink to="/" end className={navLinkClass}>Dashboard</NavLink>
                  <NavLink to="/universe" className={navLinkClass}>Universe</NavLink>
                  <NavLink to="/portfolio" className={navLinkClass}>Portfolio</NavLink>
                  <NavLink to="/runs" className={navLinkClass}>Runs</NavLink>
                  <MoreDropdown />
                </div>
              </div>
              <div className="hidden sm:flex items-center">
                <ApiKeyNavButton onClick={() => setApiKeyModalOpen(true)} />
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

          {/* Mobile menu */}
          {mobileMenuOpen && (
            <div
              className="sm:hidden border-t border-terminal-border"
              style={{ background: 'rgba(6, 6, 10, 0.95)' }}
            >
              <div className="pt-2 pb-3 space-y-0.5 px-3">
                <NavLink to="/" end className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Dashboard</NavLink>
                <NavLink to="/universe" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Universe</NavLink>
                <NavLink to="/portfolio" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Portfolio</NavLink>
                <NavLink to="/runs" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Run History</NavLink>
                <NavLink to="/opportunity" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Opportunity</NavLink>
                <NavLink to="/orders" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Order Mgmt</NavLink>
                <NavLink to="/commands" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Commands</NavLink>
                <NavLink to="/world-news" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>World News</NavLink>
                <NavLink to="/costs" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Costs</NavLink>
                <NavLink to="/roadmap" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Roadmap</NavLink>
                <div className="pt-2 pb-1">
                  <ApiKeyNavButton onClick={() => { setMobileMenuOpen(false); setApiKeyModalOpen(true) }} />
                </div>
              </div>
            </div>
          )}
        </nav>

        {authRequired && (
          <DashboardAuthBanner
            onRetry={() => setSseReconnectNonce((n) => n + 1)}
            onOpenApiKey={() => setApiKeyModalOpen(true)}
          />
        )}
        <DashboardApiKeyModal open={apiKeyModalOpen} onClose={() => setApiKeyModalOpen(false)} />
        <AlertBanner sseDisconnectedAlert={sseDisconnectedAlert} />

        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<Dashboard sseEvents={sseEvents} sseConnectionState={sseConnectionState} />} />
            <Route path="/universe" element={<Universe />} />
            <Route path="/universe/:ticker" element={<Universe />} />
            <Route path="/runs" element={<RunHistory />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/opportunity" element={<Opportunity />} />
            <Route path="/orders" element={<OrderManagement />} />
            <Route path="/costs" element={<Costs />} />
            <Route path="/commands" element={<Commands />} />
            <Route path="/world-news" element={<WorldNews />} />
            <Route path="/roadmap" element={<Roadmap />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
