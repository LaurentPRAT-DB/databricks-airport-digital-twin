import type { Config } from 'tailwindcss';
import { brand } from './brands';

const config: Config = {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [brand.typography.fontFamily.sans],
      },
      colors: {
        slate: brand.colors.neutrals,
        'databricks-red': brand.colors.databricks.red,
        'databricks-dark': brand.colors.databricks.dark,
        'airport-ground': brand.colors.flightPhase.ground,
        'airport-climbing': brand.colors.flightPhase.climbing,
        'airport-descending': brand.colors.flightPhase.descending,
        'airport-cruising': brand.colors.flightPhase.cruising,
      },
    },
  },
  plugins: [],
};

export default config;
