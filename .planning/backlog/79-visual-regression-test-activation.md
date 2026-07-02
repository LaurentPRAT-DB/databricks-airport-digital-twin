---
id: 79
title: Activate visual regression testing
priority: P2
area: testing
status: implemented
---

# Visual Regression Test Activation

## Problem
~3,475 frontend tests but zero active visual regression tests. CSS changes break the demo visually while all tests stay green.

## Implemented
1. Fixed stale `.leaflet-container` → `.maplibregl-map` selector in 3D spec
2. Activated skipped 3D screenshot test (baseline PNG already existed)
3. Added 3 map screenshot assertions (loaded, flight-selected, satellite)
4. Added 3 layout screenshot assertions (full page, detail panel, mobile)
5. Created shared E2E fixture (`e2e/fixtures.ts`)
6. Added AirportSelector component test (11 tests)

## Remaining
- Run `npx playwright test --update-snapshots` to generate baselines (requires running servers)
- Consider CI strategy for platform-specific baselines (darwin vs linux)
- Delete stale `3d-view-chromium-darwin.png` baseline after regeneration
