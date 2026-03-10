/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Financial terminal color palette
        'terminal-bg': '#0a0a0a',
        'terminal-surface': '#141414',
        'terminal-border': '#2a2a2a',
        'terminal-text': '#e0e0e0',
        'terminal-text-dim': '#888888',
        'gain': '#00ff88',
        'loss': '#ff4444',
        'neutral': '#4a9eff',
        'accent': '#ffd700',
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
