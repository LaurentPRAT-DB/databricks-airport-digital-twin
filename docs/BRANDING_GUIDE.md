# Multi-Brand Configuration Guide

How to add a new company brand to the Airport Digital Twin.

---

## Architecture Overview

```
app/frontend/brands/
├── databricks/              ← default brand
│   ├── brand.config.ts      (colors, fonts, components)
│   ├── logo.svg             (company logo for header)
│   └── index.ts             (re-export)
├── sita.aero/               ← example alternative brand
│   ├── brand.config.ts
│   ├── logo.svg
│   └── index.ts
└── index.ts                 (brand loader — reads VITE_BRAND env var)
```

Brand selection happens at **build time** via `VITE_BRAND` environment variable. The brand loader (`brands/index.ts`) imports all brand configs statically and exports the selected one.

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

The config has these sections — all are required:

| Section | What to customize |
|---------|-------------------|
| `colors.databricks` | Primary brand color + dark/light variants (keep the key name `databricks` — it's structural) |
| `colors.primary` | Full color scale (50–900) built from your primary color |
| `colors.secondary` | Accent/link color scale |
| `colors.accent` | Semantic colors: success (emerald), warning (amber), error (red) |
| `colors.neutrals` | Gray scale for backgrounds, text, borders |
| `colors.flightPhase` | Map marker colors for flight states |
| `typography` | Font family, import URL, sizes, weights |
| `spacing` | Usually keep as-is unless brand has strict grid |
| `borderRadius` | Corner rounding (usually keep defaults) |
| `shadows` | Elevation system (usually keep defaults) |
| `backdrop` | Blur and overlay settings |
| `logo` | Logo references and brand mark identifier |
| `layout` | Header bg color, sidebar widths, z-indexes |
| `components` | Tailwind class overrides for buttons, cards, badges, navbar, modals |

### 4. Key fields to change

**Colors** — minimum changes:

```typescript
colors: {
  databricks: {
    red: '#YOUR_PRIMARY',         // main brand color
    redHover: '#YOUR_PRIMARY_DARK',
    redLight: '#YOUR_PRIMARY_LIGHT',
    dark: '#YOUR_DARK_SURFACE',
    darkHover: '#YOUR_DARK_HOVER',
    light: '#YOUR_LIGHT_BG',
  },
  primary: { /* generate a 50-900 scale from your primary */ },
  // ...
}
```

**Typography:**

```typescript
typography: {
  fontFamily: {
    sans: '"Your Font", system-ui, sans-serif',
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

**Components** — update Tailwind classes with your colors:

```typescript
components: {
  button: {
    primary: 'bg-[#YOUR_PRIMARY] hover:bg-[#YOUR_PRIMARY_DARK] text-white',
    // ...
  },
  navbar: {
    bg: 'bg-[#YOUR_DARK]',
    activeBorder: 'border-[#YOUR_PRIMARY]',
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
./deploy.sh --brand <company-name>
```

This:
1. Copies `brands/<company-name>/logo.svg` → `public/company-logo.svg`
2. Builds frontend with `VITE_BRAND=<company-name>`
3. Deploys via DABs as usual

### Local development

```bash
cd app/frontend
VITE_BRAND=<company-name> npm run dev
```

Note: You also need to manually copy the logo for local dev:
```bash
cp brands/<company-name>/logo.svg public/company-logo.svg
```

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
- [ ] Added white/light logo SVG
- [ ] Created `index.ts` re-export
- [ ] Registered brand in `brands/index.ts` loader
- [ ] Tested locally: `VITE_BRAND=<name> npm run dev`
- [ ] Verified header renders correctly (logo + colors)
- [ ] Verified buttons, cards, badges use new colors
- [ ] Deployed: `./deploy.sh --brand <name>`
