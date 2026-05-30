/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"DM Sans"', 'system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'sans-serif'],
      },
      colors: {
        'databricks-red': '#FF3621',
        'databricks-dark': '#1B3139',
        'airport-ground': '#6b7280',
        'airport-climbing': '#22c55e',
        'airport-descending': '#f97316',
        'airport-cruising': '#3b82f6',
      },
    },
  },
  plugins: [],
}
