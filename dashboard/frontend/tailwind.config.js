/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Financial terminal: dark charcoal, electric green, warm red, cool blue, muted gold
        'terminal-bg': '#0d1117',
        'terminal-surface': '#161b22',
        'terminal-border': '#30363d',
        'terminal-text': '#e6edf3',
        'terminal-text-dim': '#8b949e',
        'gain': '#00ff88',
        'loss': '#ff4444',
        'neutral': '#58a6ff',
        'accent': '#d4a017',
        'warning': '#ffaa00',
      },
      fontFamily: {
        'mono': ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
        'sans': ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
