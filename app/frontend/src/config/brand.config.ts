/**
 * Brand configuration — single source of truth for visual identity.
 *
 * Official Databricks branding applied:
 * - Primary color: #FF3621 (Databricks red/orange)
 * - Font: DM Sans (Databricks product font)
 * - Dark surfaces: #1B3139 (Databricks dark teal)
 */

export const brand = {
  // ── Colors ──────────────────────────────────────────────────────────────
  colors: {
    // Databricks official brand color
    databricks: {
      red: '#FF3621',         // primary brand mark
      redHover: '#E52E1A',    // darker on hover
      redLight: '#FF6B57',    // lighter variant
      dark: '#1B3139',        // official dark (nav, buttons)
      darkHover: '#24424D',   // dark hover state
      light: '#F5F6F6',       // official light background
    },
    primary: {
      50: '#FFF5F4',
      100: '#FFE8E5',
      200: '#FFCEC8',
      300: '#FFA89E',
      400: '#FF6B57',
      500: '#FF3621',         // === Databricks red
      600: '#E52E1A',
      700: '#BF2515',
      800: '#991E11',
      900: '#73160D',
    },
    secondary: {
      400: '#60a5fa',
      500: '#3b82f6',         // blue accent (links, interactive)
      600: '#2563eb',
    },
    accent: {
      emerald: '#10b981',     // success, active indicators, radar glow
      amber: '#f59e0b',       // warnings, recorded mode
      red: '#ef4444',         // errors, alerts (distinct from brand red)
    },
    neutrals: {
      // Slate scale (dark theme backbone)
      50: '#f8fafc',
      100: '#f1f5f9',
      200: '#e2e8f0',
      300: '#cbd5e1',
      400: '#94a3b8',
      500: '#64748b',
      600: '#475569',
      700: '#334155',
      800: '#1e293b',         // header, panels
      900: '#0f172a',         // app background
      950: '#020617',
    },
    // Flight phase colors (used in map markers + legend)
    flightPhase: {
      ground: '#6b7280',
      climbing: '#22c55e',
      descending: '#f97316',
      cruising: '#3b82f6',
    },
  },

  // ── Typography ──────────────────────────────────────────────────────────
  typography: {
    fontFamily: {
      // DM Sans — official Databricks product font
      sans: '"DM Sans", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      mono: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
    },
    // Google Fonts import URL (add to index.html or CSS)
    fontImport: 'https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&display=swap',
    fontSize: {
      xs: '0.625rem',       // 10px — labels, badges
      sm: '0.75rem',        // 12px — secondary text
      base: '0.875rem',     // 14px — body text
      lg: '1rem',           // 16px — section headers
      xl: '1.25rem',        // 20px — page title (Header h1)
      '2xl': '1.5rem',      // 24px — modal titles
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
      relaxed: '1.7',       // markdown reports
    },
  },

  // ── Spacing ─────────────────────────────────────────────────────────────
  spacing: {
    px: '1px',
    0.5: '0.125rem',      // 2px
    1: '0.25rem',         // 4px
    1.5: '0.375rem',      // 6px
    2: '0.5rem',          // 8px
    3: '0.75rem',         // 12px
    4: '1rem',            // 16px — standard padding
    5: '1.25rem',         // 20px
    6: '1.5rem',          // 24px
    8: '2rem',            // 32px
  },

  // ── Borders & Elevation ─────────────────────────────────────────────────
  borderRadius: {
    sm: '0.25rem',        // 4px — badges, tags
    md: '0.375rem',       // 6px — inputs
    lg: '0.5rem',         // 8px — cards, panels
    xl: '0.75rem',        // 12px — modals, toasts
    full: '9999px',       // pills, avatars, FABs
  },
  shadows: {
    sm: '0 1px 2px rgba(0, 0, 0, 0.05)',
    md: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
    lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
    xl: '0 4px 20px rgba(0, 0, 0, 0.4)',       // toasts, floating panels
  },
  backdrop: {
    blur: 'backdrop-blur',                       // playback bar, overlays
    overlay: 'rgba(0, 0, 0, 0.5)',              // modals bg-black/50
  },

  // ── Logo & Icons ────────────────────────────────────────────────────────
  logo: {
    svg: '/airport.svg',
    favicon: '/airport.svg',
    appleTouchIcon: '/apple-touch-icon.png',
    icon192: '/icons/icon-192.png',
    // Bottom-left branding — uses inline DatabricksLogo component
    brandMark: 'databricks',
    // Top-right company logo — 'databricks-wordmark' for inline SVG, or a path for custom image
    companyLogo: 'databricks-wordmark',
  },

  // ── Layout ──────────────────────────────────────────────────────────────
  layout: {
    header: {
      height: '56px',             // py-3 + content ≈ 56px
      bg: 'bg-slate-800',
      zIndex: 1002,
    },
    sidebar: {
      leftWidth: '16rem',         // w-64
      rightWidth: '20rem',        // w-80
    },
    playbackBar: {
      zIndex: 1500,
      bg: 'bg-slate-900/95',
    },
    genieChat: {
      zIndex: 1100,
      fabSize: '3rem',            // w-12 h-12
    },
    brandIcon: {
      zIndex: 1100,
      position: 'bottom-left',
      size: '2.5rem',             // 40px
      offset: '1rem',             // 16px from edges
    },
  },

  // ── Component Overrides ─────────────────────────────────────────────────
  components: {
    button: {
      base: 'px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
      primary: 'bg-[#FF3621] hover:bg-[#E52E1A] text-white',
      secondary: 'bg-slate-700 hover:bg-slate-600 text-white',
      ghost: 'hover:bg-slate-700 text-slate-300',
    },
    card: {
      base: 'rounded-lg border',
      light: 'bg-white border-slate-200',
      dark: 'bg-slate-800 border-slate-700',
    },
    badge: {
      base: 'px-1.5 py-0.5 rounded text-[10px] font-mono',
      success: 'bg-emerald-900/60 text-emerald-400',
      warning: 'bg-amber-900/60 text-amber-400',
      error: 'bg-red-900/60 text-red-400',
    },
    navbar: {
      bg: 'bg-slate-800',
      text: 'text-white',
      activeBorder: 'border-[#FF3621]',
    },
    modal: {
      overlay: 'fixed inset-0 z-[2000] bg-black/50',
      panel: 'bg-white dark:bg-slate-900 rounded-xl shadow-2xl',
    },
    fab: {
      base: 'fixed z-[1100] rounded-full shadow-lg flex items-center justify-center transition-all hover:scale-105',
      size: 'w-12 h-12',
    },
  },
} as const;

export type BrandConfig = typeof brand;
