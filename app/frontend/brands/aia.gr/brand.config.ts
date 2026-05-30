/**
 * Athens International Airport (AIA) brand configuration.
 * ICAO: LGAV | IATA: ATH
 * Corporate blue + gold accent.
 */

export const brand = {
  colors: {
    databricks: {
      red: '#004B87',
      redHover: '#003A6B',
      redLight: '#3378A8',
      dark: '#0A1628',
      darkHover: '#152238',
      light: '#F0F4F8',
    },
    primary: {
      50: '#F0F7FF',
      100: '#DCEEFF',
      200: '#B8DCFF',
      300: '#85C3FF',
      400: '#4DA3E8',
      500: '#004B87',
      600: '#003A6B',
      700: '#002D54',
      800: '#001F3D',
      900: '#001529',
    },
    secondary: {
      400: '#D4BA6A',
      500: '#C8A951',
      600: '#B08F3A',
    },
    accent: {
      emerald: '#10b981',
      amber: '#C8A951',
      red: '#D32F2F',
    },
    neutrals: {
      50: '#F8FAFC',
      100: '#F1F5F9',
      200: '#E2E8F0',
      300: '#CBD5E1',
      400: '#94A3B8',
      500: '#64748B',
      600: '#475569',
      700: '#334155',
      800: '#1E293B',
      900: '#0F172A',
      950: '#020617',
    },
    flightPhase: {
      ground: '#6b7280',
      climbing: '#22c55e',
      descending: '#f97316',
      cruising: '#004B87',
    },
  },

  typography: {
    fontFamily: {
      sans: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      mono: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
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
    brandMark: 'aia',
    companyLogo: 'aia-wordmark',
  },

  layout: {
    header: {
      height: '56px',
      bg: 'bg-[#0A1628]',
      zIndex: 1002,
    },
    sidebar: {
      leftWidth: '16rem',
      rightWidth: '20rem',
    },
    playbackBar: {
      zIndex: 1500,
      bg: 'bg-[#0A1628]/95',
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
      primary: 'bg-[#004B87] hover:bg-[#003A6B] text-white',
      secondary: 'bg-slate-700 hover:bg-slate-600 text-white',
      ghost: 'hover:bg-slate-700 text-slate-300',
    },
    card: {
      base: 'rounded-lg border',
      light: 'bg-white border-slate-200',
      dark: 'bg-[#152238] border-[#1E293B]',
    },
    badge: {
      base: 'px-1.5 py-0.5 rounded text-[10px] font-mono',
      success: 'bg-emerald-900/60 text-emerald-400',
      warning: 'bg-[#C8A951]/20 text-[#C8A951]',
      error: 'bg-red-900/60 text-red-400',
    },
    navbar: {
      bg: 'bg-[#0A1628]',
      text: 'text-white',
      activeBorder: 'border-[#004B87]',
    },
    modal: {
      overlay: 'fixed inset-0 z-[2000] bg-black/50',
      panel: 'bg-white dark:bg-[#0A1628] rounded-xl shadow-2xl',
    },
    fab: {
      base: 'fixed z-[1100] rounded-full shadow-lg flex items-center justify-center transition-all hover:scale-105',
      size: 'w-12 h-12',
    },
  },

  defaultAirport: 'LGAV',
} as const;

export type BrandConfig = typeof brand;
