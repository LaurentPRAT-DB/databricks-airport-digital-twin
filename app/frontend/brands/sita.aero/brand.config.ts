/**
 * SITA.AERO brand configuration.
 * Light theme with navy/sky-blue palette per sita.aero corporate identity.
 * Navy: #003366 | Blue: #0066CC | Sky: #00A3E0 | Light: #F5F5F5
 */

export const brand = {
  colors: {
    databricks: {
      red: '#003366',
      redHover: '#002244',
      redLight: '#0066CC',
      dark: '#003366',
      darkHover: '#002244',
      light: '#F5F5F5',
    },
    primary: {
      50: '#E6F4FB',
      100: '#CCE9F7',
      200: '#99D3EF',
      300: '#66BDE7',
      400: '#33A7DF',
      500: '#0066CC',
      600: '#005CB8',
      700: '#004D99',
      800: '#003D7A',
      900: '#003366',
    },
    secondary: {
      400: '#33B8E8',
      500: '#00A3E0',
      600: '#0082B3',
    },
    accent: {
      emerald: '#008A5E',
      amber: '#E68A00',
      red: '#CC3333',
    },
    neutrals: {
      50: '#F0F4F8',
      100: '#D9E2EC',
      200: '#BCCCDC',
      300: '#9FB3C8',
      400: '#829AB1',
      500: '#627D98',
      600: '#486581',
      700: '#1E3A5F',
      800: '#102A43',
      900: '#0A1929',
      950: '#061220',
    },
    flightPhase: {
      ground: '#666666',
      climbing: '#008A5E',
      descending: '#CC3333',
      cruising: '#00A3E0',
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
    md: '0 4px 6px -1px rgba(0, 0, 0, 0.08)',
    lg: '0 10px 15px -3px rgba(0, 0, 0, 0.08)',
    xl: '0 4px 20px rgba(0, 0, 0, 0.12)',
  },
  backdrop: {
    blur: 'backdrop-blur',
    overlay: 'rgba(0, 0, 0, 0.4)',
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
      bg: 'bg-[#003366]',
      zIndex: 1002,
    },
    sidebar: {
      leftWidth: '16rem',
      rightWidth: '20rem',
    },
    playbackBar: {
      zIndex: 1500,
      bg: 'bg-[#003366]/95',
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
      primary: 'bg-[#0066CC] hover:bg-[#005CB8] text-white',
      secondary: 'bg-[#003366] hover:bg-[#002244] text-white',
      ghost: 'hover:bg-[#E6F4FB] text-[#003366]',
    },
    card: {
      base: 'rounded-lg border',
      light: 'bg-white border-[#E8E8E8]',
      dark: 'bg-[#003366] border-[#004D99]',
    },
    badge: {
      base: 'px-1.5 py-0.5 rounded text-[10px] font-mono',
      success: 'bg-[#008A5E]/10 text-[#008A5E]',
      warning: 'bg-[#E68A00]/10 text-[#E68A00]',
      error: 'bg-[#CC3333]/10 text-[#CC3333]',
    },
    navbar: {
      bg: 'bg-[#003366]',
      text: 'text-white',
      activeBorder: 'border-[#00A3E0]',
    },
    modal: {
      overlay: 'fixed inset-0 z-[2000] bg-black/40',
      panel: 'bg-white dark:bg-[#003366] rounded-xl shadow-2xl',
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
