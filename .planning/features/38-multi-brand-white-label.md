---
status: complete
area: ui
related: [brand.config.ts, deploy.sh]
---

# Feature 38: Multi-Brand White-Label System

## Summary

Directory-based brand configuration enabling white-label deployments. Each company gets its own brand directory with design tokens, logo, and font config. Selected at build time via `VITE_BRAND` env var and `deploy.sh --brand <name>`.

## Architecture

```
app/frontend/brands/
├── databricks/          (default)
│   ├── brand.config.ts  — colors, typography, spacing, components
│   ├── logo.svg         — official Databricks wordmark (white text)
│   └── index.ts
├── sita.aero/
│   ├── brand.config.ts  — SITA tokens (#4c3de3, Saans font)
│   ├── logo.svg         — official SITA logo (white fill)
│   └── index.ts
└── index.ts             — loader (reads VITE_BRAND, defaults to databricks)
```

## Brand Tokens

Each `brand.config.ts` exports a config object with:
- `colors` — primary scale, neutrals, flight phase, accents
- `typography` — font family, sizes, weights, Google Fonts import URL
- `spacing`, `borderRadius`, `shadows`, `backdrop`
- `logo` — SVG paths, brand mark type, company logo type
- `layout` — header, sidebar, playbar, FAB dimensions
- `components` — button, card, badge, navbar, modal, FAB class overrides

## Deployment

```bash
./deploy.sh --brand sita.aero --target free   # SITA on free workspace
./deploy.sh --target dev                       # Databricks (default)
BRAND=sita.aero ./deploy.sh --target prod      # env var also works
```

Deploy.sh:
1. Copies `brands/$BRAND/logo.svg` → `public/company-logo.svg`
2. Passes `VITE_BRAND=$BRAND` to `npm run build`
3. Vite bundles only the selected brand's config

## Local Dev

```bash
BRAND=sita.aero ./dev.sh          # local with SITA brand
./dev.sh                           # default: databricks
```

`dev.sh` copies the brand logo to `public/company-logo.svg` on startup.

## Key Files

| File | Role |
|------|------|
| `app/frontend/brands/index.ts` | Brand loader (VITE_BRAND → config) |
| `app/frontend/brands/*/brand.config.ts` | Per-brand design tokens |
| `app/frontend/brands/*/logo.svg` | Per-brand company logo |
| `app/frontend/src/config/brand.config.ts` | Re-export (unchanged API for consumers) |
| `app/frontend/src/components/BrandIcon/CompanyLogo.tsx` | Renders `/company-logo.svg` |
| `app/frontend/src/components/BottomRightControls/` | Bottom-right icon row (legend, dark mode, chat, DB icon) |
| `deploy.sh` | `--brand` param, logo copy, VITE_BRAND pass-through |

## Brands Implemented

| Brand | Primary | Font | Status |
|-------|---------|------|--------|
| databricks | #FF3621 | DM Sans | Default, deployed to dev |
| sita.aero | #4c3de3 | Saans | Deployed to free |

## Adding a New Brand

1. Create `app/frontend/brands/<company>/`
2. Add `brand.config.ts` (copy from databricks, change values)
3. Add `logo.svg` (white version for dark header)
4. Add `index.ts` re-exporting brand
5. Register in `brands/index.ts` BRANDS map
6. Deploy: `./deploy.sh --brand <company> --target <target>`
