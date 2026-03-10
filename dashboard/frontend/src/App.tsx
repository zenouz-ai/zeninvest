import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Universe from './pages/Universe'
import RunHistory from './pages/RunHistory'
import Portfolio from './pages/Portfolio'

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-terminal-bg">
        <nav className="border-b border-terminal-border bg-terminal-surface">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between h-16">
              <div className="flex">
                <Link to="/" className="flex items-center px-2 py-2 text-xl font-bold text-accent">
                  Investment Agent
                </Link>
                <div className="hidden sm:ml-6 sm:flex sm:space-x-8">
                  <Link
                    to="/"
                    className="inline-flex items-center px-1 pt-1 text-sm font-medium text-terminal-text hover:text-accent border-b-2 border-transparent hover:border-accent"
                  >
                    Dashboard
                  </Link>
                  <Link
                    to="/universe"
                    className="inline-flex items-center px-1 pt-1 text-sm font-medium text-terminal-text hover:text-accent border-b-2 border-transparent hover:border-accent"
                  >
                    Universe
                  </Link>
                  <Link
                    to="/runs"
                    className="inline-flex items-center px-1 pt-1 text-sm font-medium text-terminal-text hover:text-accent border-b-2 border-transparent hover:border-accent"
                  >
                    Run History
                  </Link>
                  <Link
                    to="/portfolio"
                    className="inline-flex items-center px-1 pt-1 text-sm font-medium text-terminal-text hover:text-accent border-b-2 border-transparent hover:border-accent"
                  >
                    Portfolio
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </nav>

        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/universe" element={<Universe />} />
            <Route path="/runs" element={<RunHistory />} />
            <Route path="/portfolio" element={<Portfolio />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
