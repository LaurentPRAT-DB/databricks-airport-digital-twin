---
status: complete
area: frontend
related:
  - brand.config.ts
  - deploy.sh
  - .planning/features/38-multi-brand-white-label.md
---

# Multi-Brand Configuration with SITA.AERO Theme

## Context

The app needs white-label support. Current brand config (`brand.config.ts`) is hardcoded for Databricks. Goals:
1. A directory-based brand system — each company gets its own config dir
2. SITA.AERO as first alternative brand (from brandfetch/sita.aero)
3. Databricks remains default
4. `--brand` parameter on `deploy.sh` selects which brand to use at build time

## SITA Brand Tokens (extracted from sita.aero CSS)

- Primary font: "Saans", sans-serif
- Mono font: "ABC Favorit Mono", monospace
- Dark colors: #1e1e1e (primary dark), #2d2d2d (surfaces)
- Accent blue: #4c3de3
- Teal: #0095da
- Light bg: #e8e8e3
- Red: #d0021b
- Logo: SVG from https://www.sita.aero/GlobalAssets/Icons/SITA-logo.svg (dark text, needs white version for dark header)

## Implementation

### 1. Create brand directory structure

```
app/frontend/brands/
├── databricks/
│   ├── brand.config.ts      (current config, moved here)
│   ├── logo.svg             (databricks-logo.svg, moved here)
│   └── index.ts             (re-export)
├── sita.aero/
│   ├── brand.config.ts      (SITA tokens)
│   ├── logo.svg             (SITA logo, white version)
│   └── index.ts             (re-export)
└── index.ts                 (dynamic loader — reads VITE_BRAND env var)
```

### 2. Brand loader (`app/frontend/brands/index.ts`)

```typescript
import { brand as databricks } from './databricks/brand.config';
import { brand as sita } from './sita.aero/brand.config';

const BRANDS = { databricks, 'sita.aero': sita } as const;
type BrandKey = keyof typeof BRANDS;

const key = (import.meta.env.VITE_BRAND || 'databricks') as BrandKey;
export const brand = BRANDS[key] ?? BRANDS.databricks;
```

### 3. Update existing imports

- `src/config/brand.config.ts` → re-exports from `brands/index.ts`
- All existing `import { brand } from '../../config/brand.config'` stay unchanged

### 4. SITA brand config

Same shape as Databricks config but with SITA tokens:
- Primary: #4c3de3 (blue/purple accent)
- Neutrals: #1e1e1e / #2d2d2d scale
- Font: Saans (Google Fonts not available — use system stack fallback)
- Logo: white SITA wordmark SVG (invert fill from #1E1E1E to #ffffff)
- companyLogo: 'sita-wordmark'

### 5. Update `deploy.sh`

Add `--brand` parameter (default: databricks):

```bash
BRAND="${BRAND:-databricks}"
for arg in "$@"; do
  case "$arg" in
    --brand) :;;
    *) [[ "${_prev_arg:-}" == "--brand" ]] && BRAND="$arg" ;;
  esac
done
```

In the build step, pass as env:
```bash
(cd app/frontend && VITE_BRAND="$BRAND" npm run build)
```

### 6. Copy brand logo to `public/` at build time

Each brand dir has a `logo.svg`. The build step copies it:
```bash
cp "app/frontend/brands/$BRAND/logo.svg" app/frontend/public/company-logo.svg
```

`CompanyLogo` component references `/company-logo.svg` always.

## Files to Create/Modify

| File | Action |
|------|--------|
| `app/frontend/brands/databricks/brand.config.ts` | Move current config here |
| `app/frontend/brands/databricks/logo.svg` | Move `public/databricks-logo.svg` |
| `app/frontend/brands/databricks/index.ts` | Re-export |
| `app/frontend/brands/sita.aero/brand.config.ts` | New — SITA tokens |
| `app/frontend/brands/sita.aero/logo.svg` | New — white SITA logo |
| `app/frontend/brands/sita.aero/index.ts` | Re-export |
| `app/frontend/brands/index.ts` | Brand loader |
| `app/frontend/src/config/brand.config.ts` | Re-export from `brands/` |
| `app/frontend/src/components/BrandIcon/CompanyLogo.tsx` | Use `/company-logo.svg` |
| `deploy.sh` | Add `--brand` param, copy logo, pass `VITE_BRAND` |
