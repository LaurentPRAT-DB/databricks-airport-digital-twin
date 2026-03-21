# Phase 27: Simulation Video Renderer — Server-side Headless Capture

## Goal

Produce standalone MP4 videos of simulation replay events using server-side headless rendering (Playwright + ffmpeg). Videos can be emailed and played independently without needing the app.

## Status: Plan — Not Started

## Prerequisites: Phase 23 (Simulation Mode) and the simulation replay UI must be working.

---

## Context

The simulation replay system plays back pre-computed flight data frame-by-frame in the 3D view. Currently there's no way to export this as a video file. The goal is to produce standalone MP4 videos of simulation events that can be emailed and played independently — using server-side headless rendering for automated, unattended capture.

---

## Architecture

```
Python CLI script
  └─ Playwright (headless Chromium + WebGL)
       └─ Loads app → 3D view → simulation file
       └─ Steps through frames via window.__simControl API
       └─ Screenshots each frame to temp dir
  └─ ffmpeg encodes screenshots → MP4
```

---

## Implementation Steps

### Step 1: Expose simulation control API on `window`

**File:** `app/frontend/src/hooks/useSimulationReplay.ts`

Add a `useEffect` that exposes `window.__simControl` when the hook is active. This lets Playwright drive the replay programmatically:

```typescript
window.__simControl = {
  loadFile: (filename: string) => Promise<void>,  // loads sim file
  seekTo: (frameIndex: number) => void,            // jump to frame
  getInfo: () => { totalFrames, currentFrame, isLoading, isActive },
}
```

Cleanup: remove `window.__simControl` on unmount.

---

### Step 2: Expose 3D view toggle on `window`

**File:** `app/frontend/src/App.tsx`

Add `window.__viewControl = { setViewMode }` so Playwright can switch to 3D without clicking DOM buttons. Expose current view mode too.

---

### Step 3: Create the Python video renderer

**File:** `src/simulation/video_renderer.py`

```python
class VideoRenderer:
    def __init__(self, app_url, output_path, simulation_file, ...):
        ...

    async def render(self):
        # 1. Launch Playwright headless Chromium (--enable-webgl)
        # 2. Navigate to app_url
        # 3. Wait for backend ready
        # 4. Switch to 3D: page.evaluate("window.__viewControl.setViewMode('3d')")
        # 5. Wait for canvas visible
        # 6. Load simulation: page.evaluate("window.__simControl.loadFile(...)")
        # 7. Get total frames
        # 8. For each frame (or every Nth for speed):
        #    - seekTo(frame)
        #    - Wait for requestAnimationFrame
        #    - page.screenshot() → temp dir
        # 9. Run ffmpeg to encode:
        #    ffmpeg -r 30 -i frame_%05d.png -c:v libx264 -pix_fmt yuv420p output.mp4
        # 10. Cleanup temp dir
```

**Key parameters:**
- `--fps 30` — output video framerate
- `--resolution 1920x1080` — viewport size
- `--speed 1` — sim frames per video frame (1 = every frame, 2 = skip every other, etc.)
- `--simulation-file` — which sim file to render
- `--crop-to-canvas` — crop screenshot to just the 3D canvas (no sidebars)

---

### Step 4: Create CLI entry point

**File:** `src/simulation/video_cli.py`

```bash
# Basic usage:
python -m src.simulation.video_cli \
  --simulation-file simulation_output_sfo_50.json \
  --output video_output/sfo_50_replay.mp4

# With options:
python -m src.simulation.video_cli \
  --simulation-file simulation_output_sfo_50.json \
  --output video_output/sfo_50_replay.mp4 \
  --fps 30 \
  --resolution 1920x1080 \
  --start-hour 6 --end-hour 10 \
  --app-url http://localhost:3000
```

---

### Step 5: Add video optional dependency group

**File:** `pyproject.toml`

```toml
[project.optional-dependencies]
video = ["playwright>=1.40"]
```

Users install with: `uv pip install -e ".[video]"` then `playwright install chromium`

ffmpeg is assumed to be installed system-wide (standard on macOS via `brew`, available everywhere).

---

## Files Modified

| File | Change |
|------|--------|
| `app/frontend/src/hooks/useSimulationReplay.ts` | Add `window.__simControl` API |
| `app/frontend/src/App.tsx` | Add `window.__viewControl` for view mode switching |
| `src/simulation/video_renderer.py` | New — Playwright frame-by-frame capture + ffmpeg encoding |
| `src/simulation/video_cli.py` | New — CLI entry point |
| `pyproject.toml` | Add video optional dependency |

---

## Key Design Decisions

1. **Frame-by-frame, not real-time recording:** Stepping through frames deterministically ensures every sim frame is captured perfectly, regardless of render speed. No dropped frames.

2. **Crop to 3D canvas:** By default, crop screenshots to just the canvas area (no flight list, header, sidebars). Option to include full UI if desired.

3. **ffmpeg for encoding:** Produces universally-compatible MP4 (H.264 + AAC). WebM from browser recording is less email-friendly.

4. **Lightweight `window` API:** Only 3 functions exposed on `window.__simControl`. No React architecture changes. The hook already has all the logic — we just expose it.

---

## Verification

1. Run `./dev.sh` to start the app
2. Ensure a simulation output file exists (e.g., `simulation_output_sfo_50.json`)
3. Run: `python -m src.simulation.video_cli --simulation-file simulation_output_sfo_50.json --output test_video.mp4`
4. Verify `test_video.mp4` plays in QuickTime / VLC and shows the 3D replay
5. Check frame count matches expected (`total_frames / speed * fps`)

---

## Estimated Scope

- **New files:** 2 (`video_renderer.py`, `video_cli.py`)
- **Modified files:** 3 (`useSimulationReplay.ts`, `App.tsx`, `pyproject.toml`)
- **Lines:** ~250 new Python code + ~30 TypeScript
- **Risk:** Medium — headless WebGL rendering can be flaky depending on GPU/driver. Playwright's `--enable-webgl` flag and `--use-gl=swiftshader` for software rendering are fallbacks. Frame capture speed depends on resolution (~0.5-2 fps for 1080p screenshots).
