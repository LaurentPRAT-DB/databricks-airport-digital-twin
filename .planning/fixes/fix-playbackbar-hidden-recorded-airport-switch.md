# Fix: PlaybackBar hidden when loading recorded data for a different airport

## Context

When the user switches to "Recorded" mode and loads a recording for a different airport, the PlaybackBar (timeline + play/pause controls) fails to appear. The root cause is a race condition between the airport switch logic and recording loading.

## Root Cause

In `SimulationControls.tsx`, the airport switch effect (lines 700-716) is designed for simulation mode: when the user changes airports during a demo, it pauses the simulation and offers to restart for the new airport. However, this same effect fires in recorded mode too.

When loading a recording for a different airport:
1. `handleLoadRecording` calls both `onAirportChange(airport)` and `sim.loadRecording(airport, date)` (both async)
2. `loadRecording` clears `switchPaused` at the start, loads data, sets `sim.isActive = true`
3. When `loadAirport` resolves, `currentAirport` changes, triggering the airport switch effect
4. The effect sees `sim.isActive = true`, compares airport codes, and if there's any mismatch (IATA vs ICAO, or null config), calls `sim.pauseForSwitch()` setting `switchPaused = true`
5. The PlaybackBar condition `sim.isActive && !sim.switchPaused` becomes false — PlaybackBar disappears
6. In recorded mode, there's no PausedBar (only exists for simulation mode), so user sees no controls at all

## Fix

**File:** `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

### Change 1: Guard the airport switch effect for simulation mode only (line ~701)

Add `if (dataMode !== 'simulation') return;` at the top of the airport switch effect. This prevents recordings from being paused when the airport changes.

```tsx
useEffect(() => {
    if (!currentAirport) return;
    if (dataMode !== 'simulation') return; // Don't pause in recorded/live mode
    if (sim.isActive && currentAirport !== pendingAirport) {
      // ... existing IATA/ICAO check and pauseForSwitch logic
    }
}, [currentAirport]);
```

### Change 2: Clear switchPaused after recording data loads (defensive, in useSimulationReplay.ts line ~400)

In the `loadRecording` function, add a second `setSwitchPaused(false)` after `setSimData(data)` to ensure any lingering pause state is cleared when recording data arrives.

```tsx
setSimData(data);
setSwitchPaused(false); // Ensure no stale pause from prior mode
```

## Files Modified

- `app/frontend/src/components/SimulationControls/SimulationControls.tsx` — guard airport switch effect
- `app/frontend/src/hooks/useSimulationReplay.ts` — defensive switchPaused clear in loadRecording

## Verification

1. `cd app/frontend && npm test -- --run` — all existing tests pass
2. `cd app/frontend && npm run build` — no build errors
3. Manual flow: Switch to Recorded mode → load recording for a different airport → PlaybackBar with timeline and play/pause should be visible at the bottom
