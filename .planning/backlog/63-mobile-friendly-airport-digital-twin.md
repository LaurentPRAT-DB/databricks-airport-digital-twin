# Mobile-Friendly Airport Digital Twin

## Context

The app is 100% desktop-only: fixed 3-column layout (320px + flex + 320px), zero responsive Tailwind classes, and a header with ~10 items in a single row. It's unusable below ~960px.
The goal is to make it usable on tablets and phones using a bottom tab bar pattern — each view is full-screen, one at a time.

## Approach: Responsive Breakpoint + Bottom Tab Bar

- **Desktop (md: 768px+):** No changes — existing 3-column layout preserved.
- **Mobile (<768px):** Bottom tab bar with full-screen views.

## Mobile Layout

```
┌─────────────────────────┐
│  ✈ KJFK   ☰  [2D|3D]   │  <- Compact header (airport + hamburger + view toggle)
│                         │
│   ACTIVE TAB CONTENT    │
│   (full screen)         │
│                         │
├─────────────────────────┤
│ 🗺 Map  │ ✈ Flights │ ℹ Info │  <- Bottom tab bar (fixed)
└─────────────────────────┘
```

**Tabs:**
1. **Map** — Full-screen 2D/3D map with ViewToggle overlay
2. **Flights** — Full-screen FlightList (selecting a flight switches to Info tab)
3. **Info** — FlightDetail + GateStatus stacked (scrollable), with a sub-tab or accordion

## Header on Mobile

Current header has: title, version, airport selector, weather, sim controls, FIDS, dark mode, phase filter, status dot, platform links.

**Mobile header:** Airport selector + hamburger menu only. The hamburger opens a slide-down panel containing: weather, sim controls, FIDS button, dark mode, phase filter, platform links.

---

## Implementation Steps

### Step 1: Add useIsMobile hook

- **New file:** `app/frontend/src/hooks/useIsMobile.ts`
- Simple hook using `window.matchMedia('(max-width: 767px)')` with resize listener
- Returns boolean

### Step 2: Create MobileTabBar component

- **New file:** `app/frontend/src/components/MobileTabBar/MobileTabBar.tsx`
- Fixed to bottom of screen, 3 tabs: Map / Flights / Info
- Icons + labels, highlight active tab
- Touch-friendly: 48px minimum height, full-width tap targets

### Step 3: Create MobileHeader component

- **New file:** `app/frontend/src/components/Header/MobileHeader.tsx`
- Compact: airport code/selector on left, hamburger on right
- Hamburger opens a dropdown panel with: weather, sim controls, FIDS, dark mode toggle, phase filter, platform links, version
- ViewToggle (2D/3D + satellite) stays as a map overlay, not in header

### Step 4: Make App.tsx responsive

- **Modify:** `app/frontend/src/App.tsx`
- Use `useIsMobile()` to conditionally render:
  - Desktop: Current layout (unchanged)
  - Mobile: MobileHeader + active tab content + MobileTabBar
- Add `activeTab` state (`'map' | 'flights' | 'info'`)
- When a flight is selected (from FlightList or map marker), auto-switch to Info tab
- All existing components (FlightList, FlightDetail, GateStatus, AirportMap, Map3D) rendered as-is inside mobile full-screen containers

### Step 5: Make existing components mobile-friendly

- **Modify:** `app/frontend/src/components/FlightList/FlightList.tsx`
  - Remove `border-r` on mobile (it's full-screen now)
  - Larger touch targets on FlightRow (min 44px height)
- **Modify:** `app/frontend/src/components/FlightList/FlightRow.tsx`
  - Add `min-h-[44px]` for touch targets
- **Modify:** `app/frontend/src/components/FlightDetail/FlightDetail.tsx`
  - Full-width on mobile, no changes to content structure
- **Modify:** `app/frontend/src/components/GateStatus/GateStatus.tsx`
  - Gate grid: change from `grid-cols-8` to responsive `grid-cols-6` on mobile for bigger tap targets
- **Modify:** `app/frontend/src/components/FIDS/FIDS.tsx`
  - Already a modal — make it full-screen on mobile (`max-w-4xl` → `md:max-w-4xl w-full h-full md:h-auto`)
  - Horizontal scroll on the table or card layout for narrow screens

### Step 6: Map touch improvements

- **Modify:** `app/frontend/src/components/Map/FlightMarker.tsx`
  - Increase marker hit area on mobile (bigger invisible touch target)
- ViewToggle buttons: ensure 44px min touch targets

### Step 7: Add tests

- Test `useIsMobile` hook with mocked `matchMedia`
- Test MobileTabBar renders tabs, handles clicks
- Test MobileHeader hamburger toggle
- Test App.tsx renders mobile layout when screen is narrow
- Run existing test suites to verify no desktop regressions

---

## Files Changed

| File | Action | Notes |
|------|--------|-------|
| `src/hooks/useIsMobile.ts` | Create | matchMedia hook |
| `src/components/MobileTabBar/MobileTabBar.tsx` | Create | Bottom tab bar |
| `src/components/Header/MobileHeader.tsx` | Create | Compact header + hamburger |
| `src/App.tsx` | Modify | Conditional mobile/desktop layout |
| `src/components/FlightList/FlightList.tsx` | Modify | Remove border-r on mobile |
| `src/components/FlightList/FlightRow.tsx` | Modify | Touch targets |
| `src/components/GateStatus/GateStatus.tsx` | Modify | Responsive grid |
| `src/components/FIDS/FIDS.tsx` | Modify | Full-screen on mobile |
| `src/components/Map/FlightMarker.tsx` | Modify | Bigger touch targets |

All paths relative to `app/frontend/`.

---

## Verification

1. **Desktop regression:** `cd app/frontend && npm test -- --run` — all ~635 tests pass
2. **Python tests:** `uv run pytest tests/ -v` — no backend changes expected
3. **Visual check:** Open in Chrome DevTools responsive mode (iPhone 14 Pro, iPad) and verify:
   - Tab bar shows at bottom, tapping switches views
   - Header is compact with working hamburger menu
   - Flight list items are tappable, selecting switches to Info tab
   - Map fills screen, 2D/3D toggle works
   - Gate grid is tappable
   - FIDS opens full-screen
4. **Build:** `cd app/frontend && npm run build` succeeds
