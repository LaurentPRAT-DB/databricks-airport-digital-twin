# Multi-Brand Configuration Guide

White-label the Airport Digital Twin for any customer. One config file controls all visual identity — colors, typography, dark surface tones, logo, default airport, and component styling.

---

## Architecture Overview

```
app/frontend/brands/
├── databricks/              ← default brand
│   ├── brand.config.ts      (single source of truth for all visual identity)
│   ├── logo.svg             (company logo — displayed in header)
│   └── index.ts             (re-export)
├── sita.aero/               ← SITA brand (navy/sky-blue)
│   ├── brand.config.ts
│   ├── logo.svg
│   └── index.ts
├── aia.gr/                   ← Athens International Airport
│   ├── brand.config.ts
│   ├── logo.svg
│   └── index.ts
├── index.ts                 (brand loader — reads VITE_BRAND env var)
app/frontend/tailwind.config.ts  (imports brand → drives Tailwind color system)
```

Brand selection happens at **build time** via `VITE_BRAND` environment variable. The brand config is the **single source of truth** — Tailwind's color system, font family, and flight-phase markers are all derived from it at build time via `tailwind.config.ts`.

---

## Step-by-Step: Adding a New Brand

### 1. Create the brand directory

```bash
mkdir -p app/frontend/brands/<company-name>
```

Use a lowercase identifier. Dots are allowed (e.g., `sita.aero`).

### 2. Create `brand.config.ts`

Copy the Databricks config as a template and replace values:

```bash
cp app/frontend/brands/databricks/brand.config.ts app/frontend/brands/<company-name>/brand.config.ts
```

### 3. Fill in brand tokens

The config has these sections — all are required unless marked optional:

| Section | What to customize | Tailwind impact |
|---------|-------------------|-----------------|
| `colors.databricks` | Primary brand color + dark/light variants (keep the key name `databricks` — it's structural) | `databricks-red`, `databricks-dark` utilities |
| `colors.primary` | Full color scale (50–900) built from your primary color | — |
| `colors.secondary` | Accent/link color scale | — |
| `colors.accent` | Semantic colors: success (emerald), warning (amber), error (red) | — |
| `colors.neutrals` | **Surface scale (50–950)** — controls ALL dark backgrounds, panels, sidebars | **Overrides `slate-*` in Tailwind** |
| `colors.flightPhase` | Map marker colors for flight states | `airport-ground`, `airport-climbing`, etc. |
| `typography` | Font family, import URL, sizes, weights | Tailwind `font-sans` override |
| `spacing` | Usually keep as-is unless brand has strict grid | — |
| `borderRadius` | Corner rounding (usually keep defaults) | — |
| `shadows` | Elevation system (usually keep defaults) | — |
| `backdrop` | Blur and overlay settings | — |
| `logo` | Logo references and brand mark identifier | — |
| `layout` | Header bg color, sidebar widths, z-indexes | — |
| `components` | Tailwind class overrides for buttons, cards, badges, navbar, modals | — |
| `defaultAirport` | (optional) ICAO code to load on startup (e.g. `'LSGG'`) | — |
| `companyName` | (optional) Text displayed next to logo — only use when logo doesn't clearly show company name | — |

### 4. Key fields to change

**Colors — Neutrals (most impactful)**

The `neutrals` scale controls the entire app surface. It maps directly to Tailwind's `slate-*` utilities via `tailwind.config.ts`. This is how you control whether the app feels "neutral gray", "navy-tinted", or "warm":

```typescript
neutrals: {
  50: '#F0F4F8',     // lightest background (light mode panels)
  100: '#D9E2EC',    // light borders, subtle backgrounds
  200: '#BCCCDC',    // medium borders
  300: '#9FB3C8',    // disabled text
  400: '#829AB1',    // placeholder text
  500: '#627D98',    // secondary text
  600: '#486581',    // body text (light mode)
  700: '#1E3A5F',    // dark panels, cards
  800: '#102A43',    // app background (dark mode)
  900: '#0A1929',    // deepest background
  950: '#061220',    // extreme dark
},
```

To create a navy-tinted dark theme (like SITA), shift all values toward blue. For a neutral theme, use standard gray values. For a warm theme, shift toward amber/brown.

**Colors — Primary brand:**

```typescript
colors: {
  databricks: {
    red: '#YOUR_PRIMARY',         // main brand color (buttons, active states)
    redHover: '#YOUR_PRIMARY_DARK',
    redLight: '#YOUR_PRIMARY_LIGHT',
    dark: '#YOUR_DARK_SURFACE',   // header/navbar background
    darkHover: '#YOUR_DARK_HOVER',
    light: '#YOUR_LIGHT_BG',      // light mode background
  },
  primary: { /* generate a 50-900 scale from your primary */ },
  // ...
}
```

**Typography:**

```typescript
typography: {
  fontFamily: {
    sans: '"Your Font", system-ui, sans-serif',   // drives Tailwind font-sans
    mono: '"Your Mono Font", ui-monospace, monospace',
  },
  fontImport: 'https://fonts.googleapis.com/css2?family=Your+Font&display=swap',
  // ... keep fontSize/fontWeight/lineHeight unless brand guidelines differ
}
```

**Logo section:**

```typescript
logo: {
  svg: '/airport.svg',           // app icon (airport specific, usually keep)
  favicon: '/airport.svg',
  appleTouchIcon: '/apple-touch-icon.png',
  icon192: '/icons/icon-192.png',
  brandMark: 'your-brand',       // identifier for bottom-left brand mark
  companyLogo: 'your-wordmark',  // identifier (currently unused — logo.svg handles it)
}
```

**Layout header:**

```typescript
layout: {
  header: {
    height: '56px',
    bg: 'bg-[#YOUR_DARK_COLOR]',  // Tailwind arbitrary value
    zIndex: 1002,
  },
  // ...
}
```

**Default Airport** (optional):

```typescript
defaultAirport: 'LSGG',  // ICAO code — app opens at this airport on startup
```

When set, the frontend falls back to this airport if the backend doesn't specify one. The backend is also configured per-brand at deploy time (see Deployment section).

**Company Name** (optional):

```typescript
companyName: 'International Airport',  // text shown next to logo in header
```

Only set this when the logo image doesn't clearly convey the company name. Most brands (SITA, Databricks) omit this field — their logos are self-explanatory.

**Components** — update Tailwind classes with your colors:

```typescript
components: {
  button: {
    primary: 'bg-[#YOUR_PRIMARY] hover:bg-[#YOUR_PRIMARY_DARK] text-white',
    // ...
  },
  navbar: {
    bg: 'bg-[#YOUR_DARK]',
    activeBorder: 'border-[#YOUR_ACCENT]',
    // ...
  },
}
```

### 5. Add company logo SVG

Place your logo at `app/frontend/brands/<company-name>/logo.svg`.

Requirements:
- SVG format
- White or light-colored (displays on dark header background)
- Reasonable aspect ratio (renders at `h-5` / 20px height)
- If your logo is dark, create a white/inverted version

### 6. Create `index.ts`

```typescript
export { brand, type BrandConfig } from './brand.config';
```

### 7. Register in the brand loader

Edit `app/frontend/brands/index.ts`:

```typescript
import { brand as databricks } from './databricks/brand.config';
import { brand as sita } from './sita.aero/brand.config';
import { brand as yourcompany } from './<company-name>/brand.config';  // ADD

const BRANDS: Record<string, BrandShape> = {
  databricks,
  'sita.aero': sita,
  '<company-name>': yourcompany,  // ADD
};
```

---

## Deploying with a Brand

### Using deploy.sh

```bash
./deploy.sh --brand <company-name> --target <target>
```

This does:
1. Copies `brands/<company-name>/logo.svg` → `public/company-logo.svg`
2. Builds frontend with `VITE_BRAND=<company-name>` — Tailwind reads the brand config at build time
3. Deploys via DABs (`databricks bundle deploy`)
4. Patches `app.yaml` on workspace with target-specific env vars including `DEMO_DEFAULT_AIRPORT`
5. Stops and starts the app to apply changes

**Current deployment targets:**

| Target | Brand | Default Airport | Workspace |
|--------|-------|-----------------|-----------|
| `dev` | sita.aero | LSGG (Geneva) | FEVM_SERVERLESS_STABLE |
| `prod` | databricks | KSFO (San Francisco) | FEVM_SERVERLESS_STABLE |
| `free` | aia.gr | LGAV (Athens) | LPT_FREE_EDITION |

### Default airport handling

The default airport is resolved from two layers:
1. **Backend env var** `DEMO_DEFAULT_AIRPORT` — set automatically by `deploy.sh` based on the `--brand` flag
2. **Frontend fallback** `brand.defaultAirport` — used only if backend `/api/config` is unreachable

The brand → airport mapping is defined in `deploy.sh`:

```bash
_brand_default_airport() {
  case "$BRAND" in
    sita.aero) echo "LSGG" ;;
    aia.gr)    echo "LGAV" ;;
    *)         echo "KSFO" ;;
  esac
}
```

When adding a new brand, add its mapping here.

### Local development

```bash
cd app/frontend
VITE_BRAND=<company-name> npm run dev
```

Note: You also need to manually copy the logo for local dev:
```bash
cp brands/<company-name>/logo.svg public/company-logo.svg
```

### How brand config drives the build

`tailwind.config.ts` imports the active brand and maps its values to Tailwind utilities:

```typescript
import { brand } from './brands';

// brand.colors.neutrals → slate-50 through slate-950
// brand.typography.fontFamily.sans → font-sans
// brand.colors.flightPhase.* → airport-ground, airport-climbing, etc.
```

This means every `bg-slate-800`, `text-slate-300`, `font-sans` in the codebase automatically adapts to the brand's color palette — no per-component overrides needed.

---

## Design Token Reference

### Generating a color scale from a primary color

Given a primary hex (e.g., `#4c3de3`), generate a 50–900 scale:

| Step | Approach |
|------|----------|
| 50 | Near-white tint (97% lightness) |
| 100–200 | Light tints |
| 300–400 | Medium tints |
| 500 | Your primary color |
| 600 | 15% darker |
| 700 | 30% darker |
| 800 | 45% darker |
| 900 | 60% darker |

Tools: [UIColors.app](https://uicolors.app), [Tailwind color generator](https://www.tints.dev/).

### Font considerations

- If using a proprietary font (not on Google Fonts), leave `fontImport` empty and self-host the font files
- Always include system fallbacks in `fontFamily`
- The app uses sizes from `xs` (10px) to `2xl` (24px) — ensure your font is legible at small sizes

---

## Checklist

- [ ] Created `app/frontend/brands/<name>/` directory
- [ ] Created `brand.config.ts` with all required sections
- [ ] Set `colors.neutrals` scale with brand-appropriate tint (navy, gray, warm)
- [ ] Set `defaultAirport` to customer's primary hub ICAO code
- [ ] Added `_brand_default_airport()` mapping in `deploy.sh`
- [ ] Added white/light logo SVG (renders on dark header)
- [ ] Set `companyName` only if logo doesn't clearly show company name
- [ ] Created `index.ts` re-export
- [ ] Registered brand in `brands/index.ts` loader
- [ ] Tested locally: `VITE_BRAND=<name> npm run dev`
- [ ] Verified header renders correctly (logo + navy/brand background)
- [ ] Verified dark mode uses brand-tinted neutrals (not generic gray)
- [ ] Verified correct airport loads on startup
- [ ] Verified buttons, cards, badges, navbar use brand colors
- [ ] Built production: `VITE_BRAND=<name> npm run build` (no errors)
- [ ] Deployed: `./deploy.sh --brand <name> --target <target>`
- [ ] Verified deployed app loads correct default airport
