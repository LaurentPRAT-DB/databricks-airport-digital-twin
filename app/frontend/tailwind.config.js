/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'airport-ground': '#6b7280',
        'airport-climbing': '#22c55e',
        'airport-descending': '#f97316',
        'airport-cruising': '#3b82f6',
      },
    },
  },
  plugins: [],
}
