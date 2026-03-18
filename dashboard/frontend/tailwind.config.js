/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ZENOUZ.ai brand palette — see /branding/BRAND.md
        'terminal-bg': '#06060a',       // --bg-primary
        'terminal-surface': '#0c0c14',  // --bg-card
        'terminal-border': 'rgba(255, 255, 255, 0.06)', // --border
        'terminal-text': '#ffffff',     // --text-primary
        'terminal-text-dim': 'rgba(255, 255, 255, 0.5)', // --text-secondary
        'gain': '#00ffa3',              // --positive (emerald)
        'loss': '#ff4466',              // --negative
        'neutral': '#00d4ff',           // --cyan / --accent
        'accent': '#00d4ff',            // --cyan (brand primary)
        'warning': '#f7c948',           // --warning
        // Additional brand tokens
        'cyan': '#00d4ff',
        'emerald': '#00ffa3',
        'violet': '#6332ff',
        'navy': '#0a1628',
        'elevated': '#12121c',          // --bg-elevated
        'text-muted': 'rgba(255, 255, 255, 0.25)',
      },
      fontFamily: {
        'mono': ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
        'sans': ['Outfit', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
