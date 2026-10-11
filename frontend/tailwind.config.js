/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          950: '#03010a',
          900: '#080520',
          800: '#0f0a35',
          700: '#1a1060',
          600: '#2d1fa3',
          500: '#4535d4',
          400: '#6c5ce7',
          300: '#a29bfe',
          200: '#d6d0ff',
          100: '#f0eeff',
        },
        fire: {
          600: '#e84393',
          500: '#ff2d78',
          400: '#ff6eb4',
        },
        amber: {
          500: '#ffb347',
          400: '#ffd580',
        },
        surface: {
          dark: '#07041a',
          card: 'rgba(15,10,53,0.7)',
          glass: 'rgba(255,255,255,0.04)',
        },
        ui: {
          bg: 'rgb(var(--theme-bg-rgb) / <alpha-value>)',
          surface: 'rgb(var(--theme-surface-rgb) / <alpha-value>)',
          report: 'rgb(var(--theme-report-rgb) / <alpha-value>)',
          border: 'rgb(var(--theme-border-rgb) / <alpha-value>)',
          text: 'rgb(var(--theme-text-rgb) / <alpha-value>)',
          muted: 'rgb(var(--theme-text-muted-rgb) / <alpha-value>)',
        },
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
      },
    },
  },
  plugins: [],
  darkMode: 'class',
}

