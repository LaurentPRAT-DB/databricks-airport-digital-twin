# Plan: Long Simulation Navigation + Scene Capture

## Context

Calibrated simulations produce 27-152 MB JSON files for 24h runs. Multi-day or high-frequency simulations will exceed browser memory limits. Currently the entire file is loaded at once with no way to navigate by date/time. Operators need to:
1. Browse long simulations by day or time range without loading everything
2. Capture 2D/3D scenes as evidence for reports

The backend already has `start_hour`/`end_hour` server-side slicing (`app/backend/api/simulation.py:358-414`) but the frontend never exposes it. We'll build on this foundation.

---

## Phase 1: Backend — Date-Aware Time Window API

**Files:** `app/backend/api/simulation.py`

### 1a. Add simulation metadata endpoint

New endpoint `GET /api/simulation/metadata/{filename}` that returns config + summary + time range WITHOUT loading all frames. This lets the frontend show duration/days before loading data.

Response:
```json
{
  "config": {},
  "summary": {},
  "sim_start": "2026-03-15T00:00:00",
  "sim_end": "2026-03-15T23:59:30",
  "duration_hours": 24,
  "total_frames": 2880,
  "estimated_frames_per_hour": 120,
  "days": ["2026-03-15"]
}
```

For multi-day sims: `"days": ["2026-03-15", "2026-03-16", ...]`

Implementation: Load the file, read `config.start_time` + `config.duration_hours`, compute the day list. Only parse config and summary keys (use streaming JSON parser or just extract the first/last snapshot timestamps).

### 1b. Extend data endpoint with absolute time params

Add optional `start_time` / `end_time` ISO params to `GET /api/simulation/data/{filename}` as an alternative to the existing `start_hour`/`end_hour`. This supports arbitrary date windows.

---

## Phase 2: Frontend — Time Window Navigator

**Files:**
- `app/frontend/src/components/SimulationControls/SimulationControls.tsx`
- `app/frontend/src/hooks/useSimulationReplay.ts`
- New: `app/frontend/src/components/SimulationControls/TimeWindowPicker.tsx`

### 2a. TimeWindowPicker component

When a file is selected (before loading), show:
- Day selector (chips/tabs) — one per simulation day
- Time range slider — dual-handle for start/end hour within the selected day
- Frame estimate — "~360 frames, ~12 MB" based on metadata
- Load button — loads just that window

For single-day sims (most current files), this simplifies to just the time range slider.

### 2b. Window navigation during replay

Once loaded, add to the playback bar:
- Current time window indicator: "Day 1: 06:00-12:00"
- "Load Next/Prev Window" buttons that load the adjacent 6h chunk (configurable)
- The existing `start_hour`/`end_hour` in `loadFile()` already supports this — just need UI

### 2c. Update useSimulationReplay hook

- Add `loadMetadata(filename)` action that calls the metadata endpoint
- Expose metadata state (days, duration, frame estimates)
- Track `currentWindow: { startTime, endTime }` state
- Add `loadWindow(filename, startTime, endTime)` convenience method

---

## Phase 3: Scene Capture for Reporting

**Files:**
- New: `app/frontend/src/components/SceneCapture/SceneCapture.tsx`
- `app/frontend/src/components/Map/AirportMap.tsx` (Leaflet ref)
- `app/frontend/src/components/Map3D/AirportScene.tsx` (Three.js renderer ref)

### 3a. 2D Map Capture (Leaflet)

Use `leaflet-image` library (or `html2canvas` as fallback) to capture the Leaflet map container as a PNG. Include:
- Map tiles + overlays + flight markers
- Timestamp watermark (current sim time)

### 3b. 3D Scene Capture (Three.js)

Three.js renderer already supports `renderer.domElement.toDataURL('image/png')`. We need:
- Set `preserveDrawingBuffer: true` on the WebGL renderer (in `AirportScene.tsx`)
- Call `toDataURL()` on the canvas

### 3c. Capture UI

Add a camera icon button to the playback bar:
- Click → captures current view (2D or 3D depending on active mode)
- Downloads as `sim_capture_{airport}_{simtime}.png`
- Optional: copy to clipboard for pasting into reports
- Show brief "Captured!" toast

### 3d. Batch capture for reports (stretch)

Leverage the existing `video_renderer.py` (Playwright + ffmpeg) infrastructure. Add a mode that captures PNGs at key moments (scenario events, peak congestion) instead of every frame. This produces a ready-made evidence pack.

---

## Phase 4: File Picker Enhancement

**File:** `SimulationControls.tsx` (the `FilePickerModal`)

Enhance the existing file picker to show:
- Duration prominently (e.g., "24h", "7d")
- Date range (e.g., "Mar 15 - Mar 21")
- File size warning for >100 MB: "Large simulation — select a time window to load"
- Route to `TimeWindowPicker` instead of direct load for large files

---

## Implementation Order

1. Phase 1a — Metadata endpoint (backend, enables everything else)
2. Phase 2a — TimeWindowPicker component (the core UX)
3. Phase 2c — Hook updates (wire metadata + windowed loading)
4. Phase 2b — Window navigation in playback bar
5. Phase 3a/3b/3c — Scene capture (independent of time navigation)
6. Phase 4 — File picker enhancement
7. Phase 3d — Batch capture (stretch goal)

---

## Verification

1. Metadata endpoint: `curl localhost:8000/api/simulation/metadata/simulation_sfo_1000_thunderstorm.json` — should return days, duration, frame estimates without loading all data
2. Windowed loading: Load a 152 MB file with `start_hour=6&end_hour=12` — should return ~1/4 of the data, browser stays responsive
3. Scene capture: In replay, click capture button — PNG downloads with correct timestamp watermark
4. Frontend tests: `cd app/frontend && npm test -- --run` — all existing + new tests pass
5. Backend tests: `uv run pytest tests/ -v -k simulation` — metadata + time params tested
