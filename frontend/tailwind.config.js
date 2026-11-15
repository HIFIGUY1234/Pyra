/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Navy/charcoal surfaces: base, panel, raised, hover, strong rule.
        ink: { 950: '#080d17', 900: '#0f1726', 800: '#141f33', 700: '#1a2740', 600: '#2c3d5a' },
        line: '#22324b',
        fire: { DEFAULT: '#e8692a', soft: '#f0782d' },
      },
      fontFamily: { sans: ['Inter', 'system-ui', 'Segoe UI', 'sans-serif'], mono: ['JetBrains Mono', 'ui-monospace', 'Consolas', 'monospace'] },
    },
  },
  plugins: [],
}
