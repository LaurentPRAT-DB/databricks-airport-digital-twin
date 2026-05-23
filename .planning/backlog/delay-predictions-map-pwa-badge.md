---
title: Add Delay Predictions Map to FlightContext + PWA Badge + Test Coverage
status: planned
area: frontend
priority: medium
related:
  - mobile-pwa-best-practices.md
---

# Add Delay Predictions Map to FlightContext + PWA Badge + Test Coverage

## Context

Flight delay predictions exist as a separate API (`/api/predictions/delays`) and a bulk hook (`usePredictions` in `src/hooks/usePredictions.ts`), but they're never consumed at the context level. The `usePredictions` hook is defined but unused. To enable the PWA Badge API (show delayed flight count on app icon) without modifying `Flight[]` type, we'll expose a `delayMap: Map<string, DelayPrediction>` from FlightContext as a parallel lookup. This avoids type cascades and re-render storms.

## Approach: Separate Delay Map (zero impact on existing Flight consumers)

### 1. Add delayMap to FlightContext (`src/context/FlightContext.tsx`)

- Import `usePredictions` from `../hooks/usePredictions`
- Call `usePredictions(flights)` inside FlightProvider — polls `/api/predictions/delays` every 30s
- Add `delayMap: Map<string, DelayPrediction>` to `FlightContextType` interface
- Add `delayedCount: number` (derived: entries with `delay_minutes > 15`)
- Include in `contextValue` useMemo (depend on delays from hook)

### 2. Add PWA Badge effect (`src/context/FlightContext.tsx`)

- `useEffect` watching `delayedCount` → call `navigator.setAppBadge(count)` or `clearAppBadge()`
- Already have type declarations in `vite-env.d.ts`

### 3. Create useDelayMap convenience hook (`src/hooks/useDelayMap.ts`)

- Thin wrapper: `useFlightContext().delayMap`
- Avoids consumers importing full context when they only need delays

### 4. Tests

| File | Tests |
|------|-------|
| `src/context/FlightContext.test.tsx` | Add: delayMap exposed, delayedCount correct, badge API called |
| `src/hooks/useOnlineStatus.test.ts` | New: online→offline→online transitions |
| `src/hooks/useDelayMap.test.ts` | New: returns map from context |
| `src/components/ConnectionStatus.test.tsx` | New: renders when offline, hidden when online |

### 5. Files Modified

- `src/context/FlightContext.tsx` — add delayMap + badge effect
- `src/hooks/useDelayMap.ts` — new convenience hook
- `src/context/FlightContext.test.tsx` — add delay/badge tests
- `src/hooks/useOnlineStatus.test.ts` — new
- `src/hooks/useDelayMap.test.ts` — new
- `src/components/ConnectionStatus.test.tsx` — new

## Key Patterns to Reuse

- `usePredictions` hook already handles fetch + Map construction (`src/hooks/usePredictions.ts:56`)
- MSW handler at `src/test/mocks/handlers.ts:254` already mocks `/api/predictions/delays`
- Mock data: `mockDelayPrediction` has `icao24=a12345`, `delay=15min`, `category=slight`
- Test wrapper pattern: `createWrapper()` with QueryClient + providers (from existing `FlightContext.test.tsx`)

## Regression Guards

- `Flight[]` type unchanged — no cascade to 15+ consuming components
- `delayMap` is additive to context interface — existing consumers unaffected
- `usePredictions` is already tested (MSW handlers in place)
- Badge API calls are behind feature detection (`'setAppBadge' in navigator`)
- Badge effect only fires when `delayedCount` changes (not on every render)
