# License Audit — Commercial Use Assessment

**Date:** 2026-06-26
**Project license:** MIT

## Summary

| Status | Count | Details |
|--------|-------|---------|
| ✅ Permissive (MIT/BSD/Apache) | ~460 | Safe for commercial use |
| ⚠️ Copyleft (LGPL) | 3 | Dynamic linking OK, attribution required |
| ⚠️ Non-OSI (Hippocratic) | 2 | **Blocker** — react-leaflet |
| ⚠️ Data licenses (ODbL) | 2 | Attribution required |

---

## Python Dependencies

| Dependency | License | Commercial Use | Notes |
|-----------|---------|----------------|-------|
| fastapi | MIT | ✅ | |
| uvicorn | BSD-3-Clause | ✅ | |
| pydantic | MIT | ✅ | |
| requests | Apache-2.0 | ✅ | |
| httpx | BSD-3-Clause | ✅ | |
| scikit-learn | BSD-3-Clause | ✅ | |
| catboost | Apache-2.0 | ✅ | |
| matplotlib | PSF/Matplotlib | ✅ | Permissive, attribution required |
| lxml | BSD-3-Clause | ✅ | |
| pyyaml | MIT | ✅ | |
| websockets | BSD-3-Clause | ✅ | |
| databricks-sql-connector | Apache-2.0 | ✅ | |
| databricks-sdk | Apache-2.0 | ✅ | |
| **openap** | **LGPLv3** | ⚠️ | Dynamic linking (Python import) = OK. Don't vendor/modify source. Allow version substitution. |
| **psycopg2-binary** | **LGPL + exceptions** | ✅ | Exception clause explicitly permits proprietary linking |

## Frontend Dependencies (npm)

| License | Package Count |
|---------|--------------|
| MIT | 414 |
| ISC | 23 |
| Apache-2.0 | 17 |
| BSD-3-Clause | 7 |
| BSD-2-Clause | 3 |
| **Hippocratic-2.1** | **2** |
| **LGPL-3.0-or-later** | **1** |

### Problematic Packages

| Package | License | Risk | Mitigation |
|---------|---------|------|-----------|
| **react-leaflet@4.2.1** | Hippocratic 2.1 | ⚠️ HIGH | Not OSI-approved. Adds ethical-use restrictions. Replace with MapLibre GL JS (BSD-3) + react-map-gl |
| **@react-leaflet/core@2.1.0** | Hippocratic 2.1 | ⚠️ HIGH | Transitive from react-leaflet |
| @img/sharp-libvips | LGPL-3.0 | ✅ LOW | Dev/build only, not shipped at runtime |

## Data & API Licenses

| Source | License | Obligation |
|--------|---------|------------|
| OpenStreetMap (Overpass API) | ODbL | Attribution: "© OpenStreetMap contributors". Derived database redistribution must be ODbL. Display with attribution = commercial OK |
| Leaflet map tiles (OSM default) | CC-BY-SA 2.0 | Attribution on map |
| OpenFlights (route/airport data) | ODbL | Attribution required |

## Required Actions

### Must Fix (blockers for commercial)

1. **react-leaflet → MapLibre GL JS** — Hippocratic 2.1 is not OSI-approved. Alternative: `react-map-gl` + `maplibre-gl` (BSD-3-Clause)
2. **Add LICENSE file** — MIT license text at repo root ✅ DONE
3. **Fix package.json license** — Set `"license": "MIT"` ✅ DONE

### Should Fix (compliance)

4. **OSM attribution** — Verify "© OpenStreetMap contributors" visible on map tiles
5. **openap attribution** — Add to NOTICE file; document substitutability
6. **NOTICE file** — List all third-party deps with licenses

### Nice to Have

7. SBOM generation in CI (`cyclonedx-bom` or `syft`)
8. Automated license-check gate in CI (`license-checker --failOn`)

## openap (LGPLv3) — Detailed Analysis

Used in `src/simulation/openap_profiles.py` for realistic flight performance profiles (descent/climb rates, speeds). Python `import` = dynamic linking under LGPL interpretation.

**Commercial use is permitted if:**
- openap is not modified (we use it as-is via pip)
- Users can substitute their own version (standard pip install)
- Attribution is provided

**If replacing:** could pre-compute flight profiles and hardcode them (already has fallback profiles for when openap unavailable).

## react-leaflet (Hippocratic 2.1) — Detailed Analysis

The Hippocratic License adds:
- Cannot use for human rights violations
- Cannot use for surveillance
- Cannot use for environmental harm

While seemingly benign, it's:
- **Not OSI-approved** — many corporate legal teams auto-reject
- **Ambiguous enforcement** — "human rights" interpretation varies
- **Incompatible** with MIT/BSD ecosystem assumptions

**Replacement path:** MapLibre GL JS is a drop-in for vector tile maps, actively maintained, BSD-3 licensed. Migration effort: ~2-3 days (replace Leaflet components with react-map-gl equivalents).
