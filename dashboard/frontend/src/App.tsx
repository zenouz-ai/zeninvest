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
import { AlertBanner } from './components/AlertBanner'
import { useSSE } from './hooks/useSSE'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `inline-flex items-center px-1 pt-1 text-sm font-medium border-b-2 transition-colors rounded focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-surface ${
    isActive ? 'border-accent text-accent' : 'border-transparent text-terminal-text hover:text-accent hover:border-accent'
  }`

const mobileBase = 'block px-3 py-2 text-base font-medium'
const mobileLinkClass = ({ isActive }: { isActive: boolean }) =>
  `${mobileBase} rounded-md focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-inset ${isActive ? 'bg-terminal-bg text-accent' : 'text-terminal-text hover:bg-terminal-bg hover:text-accent'}`

const dropdownLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block px-4 py-2 text-sm transition-colors ${isActive ? 'text-accent bg-terminal-bg' : 'text-terminal-text hover:text-accent hover:bg-terminal-bg'}`

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
        className={`inline-flex items-center px-1 pt-1 text-sm font-medium border-b-2 transition-colors rounded focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-surface ${
          open ? 'border-accent text-accent' : 'border-transparent text-terminal-text hover:text-accent hover:border-accent'
        }`}
      >
        More
        <svg className={`ml-1 w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 w-44 bg-terminal-surface border border-terminal-border rounded-md shadow-lg py-1 z-50">
          <NavLink to="/opportunity" className={dropdownLinkClass} onClick={() => setOpen(false)}>Opportunity</NavLink>
          <NavLink to="/orders" className={dropdownLinkClass} onClick={() => setOpen(false)}>Order Mgmt</NavLink>
          <NavLink to="/costs" className={dropdownLinkClass} onClick={() => setOpen(false)}>Costs</NavLink>
          <NavLink to="/roadmap" className={dropdownLinkClass} onClick={() => setOpen(false)}>Roadmap</NavLink>
        </div>
      )}
    </div>
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
                <div className="hidden sm:ml-6 sm:flex sm:space-x-6 sm:items-center">
                  {/* Primary nav — always visible */}
                  <NavLink to="/" className={navLinkClass}>Dashboard</NavLink>
                  <NavLink to="/universe" className={navLinkClass}>Universe</NavLink>
                  <NavLink to="/portfolio" className={navLinkClass}>Portfolio</NavLink>
                  <NavLink to="/runs" className={navLinkClass}>Runs</NavLink>
                  {/* Secondary nav — collapsed into dropdown */}
                  <MoreDropdown />
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
          {/* Mobile menu — all items flat */}
          {mobileMenuOpen && (
            <div className="sm:hidden border-t border-terminal-border">
              <div className="pt-2 pb-3 space-y-1">
                <NavLink to="/" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Dashboard</NavLink>
                <NavLink to="/universe" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Universe</NavLink>
                <NavLink to="/portfolio" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Portfolio</NavLink>
                <NavLink to="/runs" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Run History</NavLink>
                <NavLink to="/opportunity" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Opportunity</NavLink>
                <NavLink to="/orders" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Order Mgmt</NavLink>
                <NavLink to="/costs" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Costs</NavLink>
                <NavLink to="/roadmap" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>Roadmap</NavLink>
              </div>
            </div>
          )}
        </nav>
        <AlertBanner sseConnected={sseConnected} />

        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<Dashboard sseEvents={sseEvents} sseConnected={sseConnected} />} />
            <Route path="/universe" element={<Universe />} />
            <Route path="/universe/:ticker" element={<Universe />} />
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
