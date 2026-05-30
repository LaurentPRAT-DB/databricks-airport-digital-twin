/**
 * SITA.AERO brand configuration.
 * Colors and fonts extracted from sita.aero website CSS.
 */

export const brand = {
  colors: {
    databricks: {
      red: '#4c3de3',
      redHover: '#3a2ec4',
      redLight: '#7b6ef0',
      dark: '#1e1e1e',
      darkHover: '#2d2d2d',
      light: '#e8e8e3',
    },
    primary: {
      50: '#f5f3ff',
      100: '#ede9fe',
      200: '#ddd6fe',
      300: '#c4b5fd',
      400: '#a78bfa',
      500: '#4c3de3',
      600: '#3a2ec4',
      700: '#2e25a0',
      800: '#231c7c',
      900: '#1a1560',
    },
    secondary: {
      400: '#33b5e5',
      500: '#0095da',
      600: '#0077b0',
    },
    accent: {
      emerald: '#2b3e2b',
      amber: '#fef387',
      red: '#d0021b',
    },
    neutrals: {
      50: '#f5f5f5',
      100: '#e8e8e3',
      200: '#d9d9d4',
      300: '#b8b8b3',
      400: '#787878',
      500: '#5a5a5a',
      600: '#3d3d3d',
      700: '#2d2d2d',
      800: '#1e1e1e',
      900: '#0a0a0b',
      950: '#050505',
    },
    flightPhase: {
      ground: '#787878',
      climbing: '#2b3e2b',
      descending: '#d0021b',
      cruising: '#0095da',
    },
  },

  typography: {
    fontFamily: {
      sans: '"Saans", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      mono: '"ABC Favorit Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    },
    fontImport: '',
    fontSize: {
      xs: '0.625rem',
      sm: '0.75rem',
      base: '0.875rem',
      lg: '1rem',
      xl: '1.25rem',
      '2xl': '1.5rem',
    },
    fontWeight: {
      normal: '400',
      medium: '500',
      semibold: '600',
      bold: '700',
    },
    lineHeight: {
      tight: '1.25',
      normal: '1.5',
      relaxed: '1.7',
    },
  },

  spacing: {
    px: '1px',
    0.5: '0.125rem',
    1: '0.25rem',
    1.5: '0.375rem',
    2: '0.5rem',
    3: '0.75rem',
    4: '1rem',
    5: '1.25rem',
    6: '1.5rem',
    8: '2rem',
  },

  borderRadius: {
    sm: '0.25rem',
    md: '0.375rem',
    lg: '0.5rem',
    xl: '0.75rem',
    full: '9999px',
  },
  shadows: {
    sm: '0 1px 2px rgba(0, 0, 0, 0.05)',
    md: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
    lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
    xl: '0 4px 20px rgba(0, 0, 0, 0.4)',
  },
  backdrop: {
    blur: 'backdrop-blur',
    overlay: 'rgba(0, 0, 0, 0.5)',
  },

  logo: {
    svg: '/airport.svg',
    favicon: '/airport.svg',
    appleTouchIcon: '/apple-touch-icon.png',
    icon192: '/icons/icon-192.png',
    brandMark: 'sita',
    companyLogo: 'sita-wordmark',
  },

  layout: {
    header: {
      height: '56px',
      bg: 'bg-[#1e1e1e]',
      zIndex: 1002,
    },
    sidebar: {
      leftWidth: '16rem',
      rightWidth: '20rem',
    },
    playbackBar: {
      zIndex: 1500,
      bg: 'bg-[#1e1e1e]/95',
    },
    genieChat: {
      zIndex: 1100,
      fabSize: '3rem',
    },
    brandIcon: {
      zIndex: 1100,
      position: 'bottom-right',
      size: '2.5rem',
      offset: '1rem',
    },
  },

  components: {
    button: {
      base: 'px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
      primary: 'bg-[#4c3de3] hover:bg-[#3a2ec4] text-white',
      secondary: 'bg-[#2d2d2d] hover:bg-[#3d3d3d] text-white',
      ghost: 'hover:bg-[#2d2d2d] text-[#b8b8b3]',
    },
    card: {
      base: 'rounded-lg border',
      light: 'bg-white border-[#e8e8e3]',
      dark: 'bg-[#2d2d2d] border-[#3d3d3d]',
    },
    badge: {
      base: 'px-1.5 py-0.5 rounded text-[10px] font-mono',
      success: 'bg-[#2b3e2b]/60 text-[#bbe8ee]',
      warning: 'bg-[#fef387]/20 text-[#fef387]',
      error: 'bg-[#d0021b]/20 text-[#d0021b]',
    },
    navbar: {
      bg: 'bg-[#1e1e1e]',
      text: 'text-white',
      activeBorder: 'border-[#4c3de3]',
    },
    modal: {
      overlay: 'fixed inset-0 z-[2000] bg-black/50',
      panel: 'bg-white dark:bg-[#1e1e1e] rounded-xl shadow-2xl',
    },
    fab: {
      base: 'fixed z-[1100] rounded-full shadow-lg flex items-center justify-center transition-all hover:scale-105',
      size: 'w-12 h-12',
    },
  },

  // ── Default Airport ──────────────────────────────────────────────────────
  defaultAirport: 'LSGG',
} as const;

export type BrandConfig = typeof brand;
