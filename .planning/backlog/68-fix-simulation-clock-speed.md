# Fix Simulation Clock Speed

## Context

The sim clock runs way too fast even at "1x". Snapshots are 30 sim-seconds apart. Currently 1x = 1 frame/sec = 30 sim-sec/real-sec (effectively 30x real-time). The user wants 1x = 1 real second = 1 sim minute (60x real-time), so a 24h sim plays in ~24 minutes and the clock is human-readable when paused.

---

## Files to Modify

1. `app/frontend/src/hooks/useSimulationReplay.ts` — playback interval logic
2. `app/frontend/src/components/SimulationControls/SimulationControls.tsx` — speed buttons
3. `app/frontend/src/hooks/useSimulationReplay.test.ts` — update speed type refs
4. `app/frontend/src/components/SimulationControls/SimulationControls.test.tsx` — update speed refs

---

## Change 1: Playback interval (`useSimulationReplay.ts`)

Update `PlaybackSpeed` type (line 4):

```typescript
export type PlaybackSpeed = 1 | 2 | 4 | 10 | 30 | 60;
```

Replace the playback interval logic (lines 264-292):

**Currently:** `intervalMs = Math.max(16, Math.round(1000 / speed))` — always 1 frame per tick.

**New approach:** compute from actual frame timestamps.
- On data load, compute `simSecondsPerFrame` from first two timestamps (expect ~30)
- Base rate: 1x = 1 sim minute per real second = 60 sim-sec/real-sec
- `framesPerRealSecond = 60 * speed / simSecondsPerFrame` (at 1x with 30s frames = 2 fps)
- If `framesPerRealSecond <= 60`: use `setInterval(1000 / framesPerRealSecond)`, advance 1 frame
- If `framesPerRealSecond > 60`: use `setInterval(16)`, advance `Math.ceil(framesPerRealSecond / 60)` frames per tick

| Button | framesPerRealSec | Interval | Frames/tick | 24h plays in |
|--------|------------------|----------|-------------|--------------|
| 1x     | 2                | 500ms    | 1           | 24 min       |
| 2x     | 4                | 250ms    | 1           | 12 min       |
| 4x     | 8                | 125ms    | 1           | 6 min        |
| 10x    | 20               | 50ms     | 1           | 2.4 min      |
| 30x    | 60               | 16ms     | 1           | 48 sec       |
| 60x    | 120              | 16ms     | 2           | 24 sec       |

## Change 2: Speed buttons (`SimulationControls.tsx`)

Line 10: Change `[1, 2, 5, 10, 30, 60]` -> `[1, 2, 4, 10, 30, 60]`

## Change 3: Tests

Update any references to `PlaybackSpeed` value `5` -> `4` in both test files.

---

## Verification

```bash
cd app/frontend && npm test -- --run
```

Manual: load demo, confirm 1x clock ticks ~1 sim-minute per real second, pause and read time.
