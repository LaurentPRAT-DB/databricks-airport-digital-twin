---
status: in-progress
area: frontend
related: [pwa, mobile, ios, ux]
---

# Mobile PWA Best Practices & Fixes

## Problem Statement

1. Bottom tab bar sometimes not displayed on iOS (viewport height + safe-area mismatch)
2. iOS icons not properly managed (missing splash screens, combined maskable+any purpose)
3. Missing PWA best practices (no update prompt, no offline fallback, no overscroll prevention)

## Priority 1: Fix Bottom Tab Bar Disappearing

**Root cause:** `h-screen` uses `100vh` which on iOS Safari includes the URL bar area. When the bar animates, the fixed-bottom tab bar shifts off-screen. Additionally, `pb-20` (80px) doesn't account for safe-area-inset-bottom on notched devices (~82px total).

**Fixes:**
- Replace `h-screen` with `h-dvh` (dynamic viewport height) for mobile root container
- Use CSS variable for tab bar height including safe-area, replace hardcoded `pb-20`
- Add `overscroll-behavior: none` on html/body to prevent rubber-band bounce
- Ensure SimulationControls `bottom-12` accounts for actual tab bar height

## Priority 2: Fix iOS Icons/PWA Manifest

**Fixes:**
- Separate `"any"` and `"maskable"` into distinct icon entries in manifest.json
- Add `id`, `scope`, `display_override` to manifest
- Add iOS splash screen `<link rel="apple-touch-startup-image">` (key device sizes)
- Add favicon.ico fallback

## Priority 3: Performance & UX Best Practices

**Fixes:**
- Add `touch-action: manipulation` to interactive elements for faster taps
- Add `overscroll-behavior: none` on root elements
- Add service worker version-aware update notification (toast prompting reload)
- Add offline fallback page in service worker
- Pre-cache critical navigation shell in SW

## Acceptance Criteria

- Bottom tab bar visible 100% of the time on iOS Safari + PWA standalone
- No white flash on iOS PWA launch (splash screens)
- Correct icon display on iOS home screen (properly masked)
- Update prompt shown after new deploy
- App works gracefully offline (shows friendly message)
