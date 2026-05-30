---
status: complete
area: ui
related: [brand.config.ts, deploy.sh]
---

# Feature 38: Multi-Brand White-Label System

## Summary

Directory-based brand configuration enabling white-label deployments. Each company gets its own brand directory with design tokens, logo, default airport, and font config. Selected at build time via `VITE_BRAND` env var and `deploy.sh --brand <name>`.

## Architecture

```
app/frontend/brands/
├── databricks/          (default)
│   ├── brand.config.ts  — colors, typography, spacing, components, defaultAirport
│   ├── logo.svg         — official Databricks wordmark (white text)
│   └── index.ts
├── sita.aero/
│   ├── brand.config.ts  — SITA tokens (#4c3de3, Saans font, defaultAirport: LSGG)
│   ├── logo.svg         — official SITA logo (white fill)
│   └── index.ts
└── index.ts             — loader (reads VITE_BRAND, defaults to databricks)
```

## Brand Config Schema

Each `brand.config.ts` exports a config object with:

| Field | Purpose |
|-------|---------|
| `colors` | Primary scale, neutrals, flight phase, accents |
| `typography` | Font family, sizes, weights, Google Fonts import URL |
| `spacing` | Padding/margin/gap scale |
| `borderRadius` | Corner radius tokens |
| `shadows` | Box shadow definitions |
| `backdrop` | Blur and overlay styles |
| `logo` | SVG paths, brand mark type, company logo type |
| `layout` | Header, sidebar, playbar, FAB dimensions and z-indexes |
| `components` | Button, card, badge, navbar, modal, FAB class overrides |
| `defaultAirport` | (optional) ICAO code to load on startup (e.g. `'LSGG'`) |

### Default Airport

When `defaultAirport` is set in the brand config, the app loads that airport on startup instead of the system default. This allows white-label deployments to open directly at the customer's primary airport.

Example in `brands/sita.aero/brand.config.ts`:
```ts
defaultAirport: 'LSGG',  // Geneva — SITA headquarters
```

The `brands/index.ts` loader exposes `defaultAirport` as an optional field on the `BrandShape` type.

## Header Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Airport Digital Twin]  │ [KSFO ▼] [Sim|Live|Rec]  [Weather] [KPI] [FIDS] [Platform] │ [Logo] │
│ v1.0.1099               │         ← aligned with map left edge                        │        │
│ w-64                    │         ← flex-1 center section                              │ w-80   │
└──────────────────────────────────────────────────────────────────────────┘
```

- Title block: `w-64` (matches left flight panel width)
- Center: airport selector, mode toggles, weather, KPI, FIDS, Platform
- Right: `w-80` (matches right detail panel width) — company logo only
- All buttons use `h-8` with consistent `px-3 rounded-lg text-sm`

## Bottom Controls

```
Bottom-right floating row (same height as playbar):
[Legend] [Dark mode] [Assistant] [Databricks icon]
```

All `w-9 h-9 md:w-10 md:h-10 rounded-full` — same size as playbar pause button.

## Logo Serving

The SPA catch-all route (`/{path}`) would intercept logo requests. Explicit FastAPI routes serve them:
- `GET /company-logo.svg` — brand-specific logo (copied at build time)
- `GET /company-logo.jpeg` — fallback generic aviation logo
- `GET /databricks-logo.svg` — legacy path

If no brand logo exists, `no-company-logo.jpeg` (generic aviation logo) is used as fallback.

## Deployment

```bash
./deploy.sh --brand sita.aero --target free   # SITA on free workspace
./deploy.sh --brand sita.aero --target dev    # SITA on dev (testing)
./deploy.sh --target dev                       # Databricks (default)
BRAND=sita.aero ./deploy.sh --target prod      # env var also works
```

Deploy.sh:
1. Copies `brands/$BRAND/logo.svg` → `public/company-logo.svg` (or fallback jpeg)
2. Passes `VITE_BRAND=$BRAND` to `npm run build`
3. Vite bundles only the selected brand's config
4. `SKIP_BUILD=1` skips rebuild (uses whatever's in dist — must match brand)

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
| `app/frontend/brands/*/brand.config.ts` | Per-brand design tokens + defaultAirport |
| `app/frontend/brands/*/logo.svg` | Per-brand company logo (white for dark bg) |
| `app/frontend/src/config/brand.config.ts` | Re-export (unchanged API for consumers) |
| `app/frontend/src/components/BrandIcon/CompanyLogo.tsx` | Renders `/company-logo.svg` with jpeg fallback |
| `app/frontend/src/components/BottomRightControls/` | Bottom-right icon row |
| `app/frontend/src/components/Header/Header.tsx` | Header with 3-section layout |
| `app/frontend/public/no-company-logo.jpeg` | Generic fallback logo |
| `app/backend/main.py` | Explicit routes for logo serving |
| `deploy.sh` | `--brand` param, logo copy, VITE_BRAND pass-through |

## Brands Implemented

| Brand | Primary | Font | Default Airport | Status |
|-------|---------|------|-----------------|--------|
| databricks | #FF3621 | DM Sans | (system default) | Default, deployed to dev |
| sita.aero | #4c3de3 | Saans | LSGG (Geneva) | Deployed to free |

## Adding a New Brand

1. Create `app/frontend/brands/<company>/`
2. Add `brand.config.ts` — copy from databricks, change:
   - `colors` — primary scale, neutrals, flight phases
   - `typography.fontFamily` — brand font stack
   - `logo.brandMark` — brand identifier
   - `defaultAirport` — customer's home airport (optional)
3. Add `logo.svg` — white version for dark header background
4. Add `index.ts` re-exporting brand
5. Register in `brands/index.ts` BRANDS map
6. Deploy: `./deploy.sh --brand <company> --target <target>`
