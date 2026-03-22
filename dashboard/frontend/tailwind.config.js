/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ZENOUZ.ai brand palette — see /branding/BRAND.md and dashboard-style-guide.md
        'terminal-bg': '#06060a',
        'terminal-surface': 'rgba(13, 14, 24, 0.88)',
        'terminal-surface-strong': 'rgba(17, 19, 31, 0.94)',
        'terminal-surface-soft': 'rgba(255, 255, 255, 0.04)',
        'terminal-border': 'rgba(255, 255, 255, 0.08)',
        'terminal-border-strong': 'rgba(255, 255, 255, 0.16)',
        'terminal-text': '#f1f3fb',
        'terminal-text-muted': '#adb3cb',
        'terminal-text-dim': '#7c8299',
        'gain': '#00ffa3',
        'loss': '#ff4466',
        'neutral': '#00d4ff',
        'accent': '#00d4ff',
        'warning': '#f7c948',
        // Named brand tokens
        'cyan': '#00d4ff',
        'emerald': '#00ffa3',
        'violet': '#6332ff',
        'navy': '#0a1628',
        'elevated': 'rgba(17, 19, 31, 0.94)',
        // Soft fills
        'cyan-soft': 'rgba(0, 212, 255, 0.16)',
        'emerald-soft': 'rgba(0, 255, 163, 0.16)',
        'violet-soft': 'rgba(99, 50, 255, 0.16)',
      },
      fontFamily: {
        'heading': ['Syne', 'system-ui', 'sans-serif'],
        'sans': ['Outfit', 'system-ui', 'sans-serif'],
        'mono': ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
      borderRadius: {
        'xs': '0.75rem',
        'panel': '1.5rem',
        'hero': '2rem',
      },
      boxShadow: {
        'panel': '0 30px 80px rgba(0, 0, 0, 0.28)',
        'glow': '0 16px 48px rgba(0, 212, 255, 0.18)',
        'glow-strong': '0 8px 32px rgba(0, 212, 255, 0.28), 0 0 64px rgba(99, 50, 255, 0.12)',
        'card-hover': '0 24px 64px rgba(0, 0, 0, 0.32), 0 8px 24px rgba(0, 212, 255, 0.08)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-up': 'fadeUp 0.4s cubic-bezier(0.4, 0, 0.2, 1) both',
      },
      keyframes: {
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
