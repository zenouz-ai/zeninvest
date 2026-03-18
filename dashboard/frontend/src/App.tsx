import { useState } from 'react'
import { BrowserRouter, Routes, Route, Link, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Universe from './pages/Universe'
import RunHistory from './pages/RunHistory'
import Portfolio from './pages/Portfolio'
import Opportunity from './pages/Opportunity'
import OrderManagement from './pages/OrderManagement'
import Costs from './pages/Costs'
import Roadmap from './pages/Roadmap'
import { AlertBanner } from './components/AlertBanner'
import { useSSE } from './hooks/useSSE'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `inline-flex items-center px-1 pt-1 text-sm font-medium border-b-2 transition-colors rounded focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-surface ${
    isActive ? 'border-accent text-accent' : 'border-transparent text-terminal-text hover:text-accent hover:border-accent'
  }`

function NavLinks({ mobile = false, onNavigate }: { mobile?: boolean; onNavigate?: () => void }) {
  const base = 'block px-3 py-2 text-base font-medium'
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `${base} rounded-md focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-inset ${isActive ? 'bg-terminal-bg text-accent' : 'text-terminal-text hover:bg-terminal-bg hover:text-accent'}`

  return (
    <>
      <NavLink to="/" className={mobile ? linkClass : navLinkClass} onClick={onNavigate}>
        Dashboard
      </NavLink>
      <NavLink to="/universe" className={mobile ? linkClass : navLinkClass} onClick={onNavigate}>
        Universe
      </NavLink>
      <NavLink to="/runs" className={mobile ? linkClass : navLinkClass} onClick={onNavigate}>
        Run History
      </NavLink>
      <NavLink to="/portfolio" className={mobile ? linkClass : navLinkClass} onClick={onNavigate}>
        Portfolio
      </NavLink>
      <NavLink to="/opportunity" className={mobile ? linkClass : navLinkClass} onClick={onNavigate}>
        Opportunity
      </NavLink>
      <NavLink to="/orders" className={mobile ? linkClass : navLinkClass} onClick={onNavigate}>
        Order Mgmt
      </NavLink>
      <NavLink to="/costs" className={mobile ? linkClass : navLinkClass} onClick={onNavigate}>
        Costs
      </NavLink>
      <NavLink to="/roadmap" className={mobile ? linkClass : navLinkClass} onClick={onNavigate}>
        Roadmap
      </NavLink>
    </>
  )
}

function App() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const { events: sseEvents, isConnected: sseConnected } = useSSE({ enabled: true })

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-terminal-bg">
        <nav className="border-b border-terminal-border bg-terminal-surface">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between h-16">
              <div className="flex">
                <Link to="/" className="flex items-center gap-2.5 px-2 py-2 text-xl font-semibold focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-surface rounded">
                  <img src="/logo.svg" alt="ZENOUZ.ai" className="h-7 w-7" />
                  <span className="text-white tracking-wide">ZENOUZ</span>
                  <span className="brand-gradient-text font-normal">.ai</span>
                </Link>
                <div className="hidden sm:ml-6 sm:flex sm:space-x-8">
                  <NavLinks />
                </div>
              </div>
              <div className="flex items-center sm:hidden">
                <button
                  type="button"
                  onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                  className="inline-flex items-center justify-center p-2 rounded-md text-terminal-text hover:text-accent hover:bg-terminal-bg focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-inset"
                  aria-expanded={mobileMenuOpen}
                  aria-label="Toggle navigation menu"
                >
                  <span className="sr-only">Open main menu</span>
                  {mobileMenuOpen ? (
                    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  ) : (
                    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          </div>
          {mobileMenuOpen && (
            <div className="sm:hidden border-t border-terminal-border">
              <div className="pt-2 pb-3 space-y-1">
                <NavLinks mobile onNavigate={() => setMobileMenuOpen(false)} />
              </div>
            </div>
          )}
        </nav>
        <AlertBanner sseConnected={sseConnected} />

        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<Dashboard sseEvents={sseEvents} sseConnected={sseConnected} />} />
            <Route path="/universe" element={<Universe />} />
            <Route path="/runs" element={<RunHistory />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/opportunity" element={<Opportunity />} />
            <Route path="/orders" element={<OrderManagement />} />
            <Route path="/costs" element={<Costs />} />
            <Route path="/roadmap" element={<Roadmap />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
