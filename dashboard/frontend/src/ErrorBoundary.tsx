import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError && this.state.error) {
      return (
        <div className="min-h-screen bg-[#06060a] text-[#ffffff] p-8 font-sans">
          <h1 className="text-2xl font-bold text-[#ff4466] mb-4">
            Dashboard Error
          </h1>
          <p className="mb-2 text-[rgba(255,255,255,0.5)]">Something went wrong. Check the browser console for details.</p>
          <pre className="bg-[#0c0c14] p-4 rounded text-sm overflow-auto max-h-48">
            {this.state.error.message}
          </pre>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="mt-4 px-4 py-2 bg-[#00d4ff] text-white rounded hover:opacity-90"
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
