import { useState, useEffect, useRef, useCallback } from 'react';
import { Flight } from '../types/flight';
import { debugLog } from '../utils/debugLogger';

export type PlaybackSpeed = 0.25 | 0.5 | 1 | 2 | 4 | 10 | 30 | 60;

export interface SimulationFile {
  filename: string;
  airport: string;
  total_flights: number;
  arrivals: number;
  departures: number;
  duration_hours: number;
  size_kb: number;
  size_bytes?: number;
  scenario_name?: string | null;
}

export interface RecordingFile {
  airport_icao: string;
  date: string;
  aircraft_count: number;
  state_count: number;
  first_seen: string;
  last_seen: string;
  duration_minutes: number;
  data_source: string;
}

export interface SimulationMetadata {
  config: Record<string, unknown>;
  summary: Record<string, unknown>;
  sim_start: string | null;
  sim_end: string | null;
  duration_hours: number;
  total_frames: number;
  estimated_frames_per_hour: number;
  days: string[];
  total_snapshots: number;
}

export interface TimeWindow {
  startTime: string;
  endTime: string;
}

export interface PositionSnapshot {
  time: string;
  icao24: string;
  callsign: string;
  latitude: number;
  longitude: number;
  altitude: number;
  velocity: number;
  heading: number;
  phase: string;
  on_ground: boolean;
  aircraft_type: string;
  assigned_gate?: string | null;
  vertical_rate?: number | null;
  origin_airport?: string | null;
  destination_airport?: string | null;
}

/** Altitude ceiling for trajectory segment filtering (go-around enroute interludes). */
const GO_AROUND_ALT_CEILING = 15000;

export interface ScenarioEvent {
  time: string;
  event_type: string;   // "weather" | "runway" | "ground" | "traffic" | "capacity"
  description: string;
  [key: string]: unknown;
}

interface SimulationData {
  config: Record<string, unknown>;
  summary: Record<string, unknown>;
  schedule: Record<string, unknown>[];
  frames: Record<string, PositionSnapshot[]>;
  frame_timestamps: string[];
  frame_count: number;
  phase_transitions: Record<string, unknown>[];
  gate_events: Record<string, unknown>[];
  scenario_events: ScenarioEvent[];
}

/** Map simulation/recorded phase names to the frontend flight_phase enum. */
function mapPhase(phase: string): Flight['flight_phase'] {
  const map: Record<string, Flight['flight_phase']> = {
    // Simulation engine phases
    approaching: 'approaching',
    landing: 'landing',
    taxi_to_gate: 'taxi_in',
    parked: 'parked',
    pushback: 'pushback',
    taxi_to_runway: 'taxi_out',
    takeoff: 'takeoff',
    departing: 'departing',
    enroute: 'enroute',
    // Legacy/fallback aliases (recorded data before enrichment)
    ground: 'parked',
    climb: 'departing',
    descent: 'approaching',
    cruise: 'enroute',
    approach: 'approaching',
    departure: 'departing',
    taxi_in: 'taxi_in',
    taxi_out: 'taxi_out',
  };
  return map[phase] ?? 'parked';
}

/** Convert a position snapshot to the Flight interface. */
function snapshotToFlight(
  snap: PositionSnapshot,
  dataSource: string = 'simulation',
): Flight {
  return {
    icao24: snap.icao24,
    callsign: snap.callsign,
    latitude: snap.latitude,
    longitude: snap.longitude,
    altitude: snap.altitude,
    velocity: snap.velocity,
    heading: snap.heading,
    on_ground: snap.on_ground,
    vertical_rate: snap.vertical_rate ?? null,
    last_seen: snap.time,
    data_source: dataSource,
    flight_phase: mapPhase(snap.phase),
    aircraft_type: snap.aircraft_type,
    assigned_gate: snap.assigned_gate ?? null,
    origin_airport: snap.origin_airport ?? undefined,
    destination_airport: snap.destination_airport ?? undefined,
  };
}

/** Trajectory point extracted from simulation frames. */
export interface SimTrajectoryPoint {
  latitude: number;
  longitude: number;
  altitude: number;
  velocity: number;
  heading: number;
  on_ground: boolean;
  flight_phase: string;
  timestamp: number; // epoch seconds
}

export interface UseSimulationReplayResult {
  // State
  isActive: boolean;
  isPlaying: boolean;
  isLoading: boolean;
  isFetchingFiles: boolean;
  isFetchingMetadata: boolean;
  switchPaused: boolean;
  speed: PlaybackSpeed;
  currentFrameIndex: number;
  totalFrames: number;
  currentSimTime: string | null;
  flights: Flight[];
  availableFiles: SimulationFile[];
  availableRecordings: RecordingFile[];
  isFetchingRecordings: boolean;
  loadedFile: string | null;
  summary: Record<string, unknown> | null;
  scenarioEvents: ScenarioEvent[];
  scenarioName: string | null;
  schedule: Record<string, unknown>[];
  airport: string | null;
  simStartTime: string | null;
  simEndTime: string | null;
  metadata: SimulationMetadata | null;
  currentWindow: TimeWindow | null;
  markdownReport: string | null;

  // Actions
  loadFile: (filename: string, startHour?: number, endHour?: number) => Promise<void>;
  loadWindow: (filename: string, startTime: string, endTime: string) => Promise<void>;
  loadDemo: (airportIcao: string) => Promise<void>;
  loadRecording: (airport: string, date: string, hint?: { state_count?: number; first_seen?: string; last_seen?: string }) => Promise<void>;
  fetchMetadata: (filename: string) => Promise<SimulationMetadata | null>;
  fetchRecordings: () => Promise<void>;
  play: () => void;
  pause: () => void;
  togglePlayPause: () => void;
  setSpeed: (speed: PlaybackSpeed) => void;
  seekTo: (frameIndex: number) => void;
  seekToPercent: (pct: number) => void;
  seekToTime: (isoTime: string) => void;
  seekToFlight: (isoTime: string, icao24: string, callsign?: string) => boolean;
  stop: () => void;
  fetchFiles: () => Promise<void>;
  pauseForSwitch: () => void;
  getFlightTrajectory: (icao24: string) => SimTrajectoryPoint[];
  getFlightLog: (icao24: string) => PositionSnapshot[];
}

// TypeScript declaration for the headless video renderer control API
declare global {
  interface Window {
    __simControl?: {
      loadFile: (filename: string, startHour?: number, endHour?: number) => Promise<void>;
      seekTo: (frameIndex: number) => void;
      clearSwitchPause: () => void;
      getInfo: () => {
        totalFrames: number;
        currentFrame: number;
        currentSimTime: string | null;
        isLoading: boolean;
        isActive: boolean;
        switchPaused: boolean;
      };
    };
  }
}

export function useSimulationReplay(): UseSimulationReplayResult {
  const [availableFiles, setAvailableFiles] = useState<SimulationFile[]>([]);
  const [simData, setSimData] = useState<SimulationData | null>(null);
  const [loadedFile, setLoadedFile] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isFetchingFiles, setIsFetchingFiles] = useState(false);
  const [isFetchingMetadata, setIsFetchingMetadata] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);
  const [currentFrameIndex, setCurrentFrameIndex] = useState(0);
  const [flights, setFlights] = useState<Flight[]>([]);
  const [switchPaused, setSwitchPaused] = useState(false);
  const [metadata, setMetadata] = useState<SimulationMetadata | null>(null);
  const [currentWindow, setCurrentWindow] = useState<TimeWindow | null>(null);
  const [availableRecordings, setAvailableRecordings] = useState<RecordingFile[]>([]);
  const [isFetchingRecordings, setIsFetchingRecordings] = useState(false);
  const [markdownReport, setMarkdownReport] = useState<string | null>(null);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dataSourceRef = useRef<string>('simulation');
  const wantsAutoPlayRef = useRef(false);
  const recordingWindowRef = useRef<{
    airport: string;
    date: string;
    totalStartTime: string;
    totalEndTime: string;
    loadedEndTime: string;
    windowHours: number;
    isLoadingNext: boolean;
  } | null>(null);
  // Last-seen snapshot cache: keeps flights visible during thinning gaps
  const lastSeenRef = useRef<Map<string, { snap: PositionSnapshot; frameIndex: number }>>(new Map());
  // Tracked flight: exempt from enroute distance filter (set by seekToFlight)
  const trackedIcao24Ref = useRef<string | null>(null);
  // Stale-position detection: hide airborne flights whose position stops changing
  const staleCountRef = useRef<Map<string, { lat: number; lon: number; count: number }>>(new Map());

  const isActive = simData !== null;
  const totalFrames = simData?.frame_count ?? 0;
  const currentSimTime = simData && simData.frame_timestamps[currentFrameIndex]
    ? simData.frame_timestamps[currentFrameIndex]
    : null;
  const simStartTime = simData?.frame_timestamps?.[0] ?? null;
  const simEndTime = recordingWindowRef.current?.totalEndTime
    ?? simData?.frame_timestamps?.[simData.frame_timestamps.length - 1] ?? null;

  // Fetch list of available simulation files
  const fetchFiles = useCallback(async () => {
    setIsFetchingFiles(true);
    try {
      const res = await fetch('/api/simulation/files');
      if (res.ok) {
        const data = await res.json();
        setAvailableFiles(data.files || []);
      }
    } catch {
      // Silently fail — simulation might not be available
    } finally {
      setIsFetchingFiles(false);
    }
  }, []);

  // Fetch metadata for a simulation file (lightweight, no frame data)
  const fetchMetadata = useCallback(async (filename: string): Promise<SimulationMetadata | null> => {
    setIsFetchingMetadata(true);
    try {
      const res = await fetch(`/api/simulation/metadata/${encodeURIComponent(filename)}`);
      if (!res.ok) return null;
      const meta: SimulationMetadata = await res.json();
      setMetadata(meta);
      return meta;
    } catch {
      return null;
    } finally {
      setIsFetchingMetadata(false);
    }
  }, []);

  // Load a simulation file with hour-based window (original API)
  const loadFile = useCallback(async (filename: string, startHour = 0, endHour = 24) => {
    setIsLoading(true);
    setIsPlaying(false);
    trackedIcao24Ref.current = null;
    dataSourceRef.current = 'simulation';
    try {
      const res = await fetch(
        `/api/simulation/data/${encodeURIComponent(filename)}?start_hour=${startHour}&end_hour=${endHour}`
      );
      if (!res.ok) throw new Error(`Failed to load: ${res.statusText}`);
      const data: SimulationData = await res.json();
      setSimData(data);
      setLoadedFile(filename);
      setCurrentFrameIndex(0);
      setCurrentWindow(null);

      // Set initial frame
      if (data.frame_timestamps.length > 0) {
        const firstTimestamp = data.frame_timestamps[0];
        const snapshots = data.frames[firstTimestamp] || [];
        setFlights(snapshots.map((s) => snapshotToFlight(s, 'simulation')));
      }
    } catch (err) {
      console.error('Failed to load simulation file:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Load a simulation file with absolute time window
  const loadWindow = useCallback(async (filename: string, startTime: string, endTime: string) => {
    setIsLoading(true);
    setIsPlaying(false);
    trackedIcao24Ref.current = null;
    dataSourceRef.current = 'simulation';
    try {
      const params = new URLSearchParams({
        start_time: startTime,
        end_time: endTime,
      });
      const res = await fetch(
        `/api/simulation/data/${encodeURIComponent(filename)}?${params}`
      );
      if (!res.ok) throw new Error(`Failed to load window: ${res.statusText}`);
      const data: SimulationData = await res.json();
      setSimData(data);
      setLoadedFile(filename);
      setCurrentFrameIndex(0);
      setCurrentWindow({ startTime, endTime });

      if (data.frame_timestamps.length > 0) {
        const firstTimestamp = data.frame_timestamps[0];
        const snapshots = data.frames[firstTimestamp] || [];
        setFlights(snapshots.map((s) => snapshotToFlight(s, 'simulation')));
      }
    } catch (err) {
      console.error('Failed to load simulation window:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Load a demo simulation by airport ICAO code
  const loadDemo = useCallback(async (airportIcao: string) => {
    setIsLoading(true);
    setIsPlaying(false);
    trackedIcao24Ref.current = null;
    setSwitchPaused(false);
    dataSourceRef.current = 'simulation';
    wantsAutoPlayRef.current = true;
    try {
      // Retry loop: demo may still be generating (202) after airport switch
      const maxRetries = 5;
      const retryDelayMs = 2000;
      let res: Response | null = null;
      for (let attempt = 0; attempt < maxRetries; attempt++) {
        res = await fetch(`/api/simulation/demo/${encodeURIComponent(airportIcao)}`);
        if (res.status !== 202) break;
        if (attempt < maxRetries - 1) {
          await new Promise((r) => setTimeout(r, retryDelayMs));
        }
      }
      if (!res || res.status === 202) {
        console.warn('Demo simulation still generating after retries for', airportIcao);
        return;
      }
      if (!res.ok) throw new Error(`Failed to load demo: ${res.statusText}`);
      const data: SimulationData = await res.json();
      setSimData(data);
      setLoadedFile(`demo_${airportIcao}`);
      setCurrentFrameIndex(0);
      // Set initial frame
      if (data.frame_timestamps.length > 0) {
        const firstTimestamp = data.frame_timestamps[0];
        const snapshots = data.frames[firstTimestamp] || [];
        setFlights(snapshots.map((s) => snapshotToFlight(s, 'simulation')));
      }

      // Auto-play demo
      setIsPlaying(true);
      wantsAutoPlayRef.current = false;
    } catch (err) {
      wantsAutoPlayRef.current = false;
      console.error('Failed to load demo simulation:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Fetch available recorded OpenSky sessions
  const fetchRecordings = useCallback(async () => {
    setIsFetchingRecordings(true);
    try {
      const [cloudRes, localRes] = await Promise.all([
        fetch('/api/opensky/recordings'),
        fetch('/api/opensky/recordings/local'),
      ]);

      let cloud: RecordingFile[] = [];
      if (cloudRes.ok) {
        const data = await cloudRes.json();
        cloud = (data.recordings || []).map((r: RecordingFile) => ({ ...r, data_source: r.data_source || 'cloud' }));
      }

      let local: RecordingFile[] = [];
      if (localRes.ok) {
        const localData = await localRes.json();
        local = (localData || []).map((r: { filename: string; airport_icao: string; timestamp: string; state_count: number }) => ({
          airport_icao: r.airport_icao,
          date: r.filename,
          aircraft_count: 0,
          state_count: r.state_count,
          first_seen: r.timestamp,
          last_seen: r.timestamp,
          duration_minutes: 0,
          data_source: 'local',
        }));
      }

      const all = [...local, ...cloud];
      debugLog('info', 'fetchRecordings', `${all.length} recordings found (${local.length} local, ${cloud.length} cloud)`);
      setAvailableRecordings(all);
    } catch (err) {
      debugLog('error', 'fetchRecordings', `network error: ${err}`);
    } finally {
      setIsFetchingRecordings(false);
    }
  }, []);

  // Load a recorded OpenSky session for replay
  const loadRecording = useCallback(async (airport: string, date: string, hint?: { state_count?: number; first_seen?: string; last_seen?: string }) => {
    setIsLoading(true);
    setIsPlaying(false);
    trackedIcao24Ref.current = null;
    setSwitchPaused(false);
    dataSourceRef.current = 'opensky_recorded';
    wantsAutoPlayRef.current = true;
    recordingWindowRef.current = null;
    try {
      const isLocal = date.endsWith('.jsonl');

      if (isLocal) {
        // Local recordings: load fully (small files)
        const url = `/api/opensky/recordings/local/${encodeURIComponent(date)}`;
        debugLog('info', 'loadRecording', `fetching local ${url}...`);
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data: SimulationData = await res.json();
        setSimData(data);
        setLoadedFile(`recording_${airport}_${date}`);
        setCurrentFrameIndex(0);
        setCurrentWindow(null);
        if (data.frame_timestamps.length > 0) {
          const snapshots = data.frames[data.frame_timestamps[0]] || [];
          setFlights(snapshots.map((s) => snapshotToFlight(s, 'opensky_recorded')));
        }
        setIsPlaying(true);
        wantsAutoPlayRef.current = false;
        return;
      }

      // Cloud recordings: check metadata to determine if windowing needed
      const WINDOW_HOURS = 0.5;
      const baseUrl = `/api/opensky/recordings/${encodeURIComponent(airport)}/${encodeURIComponent(date)}`;
      let url = baseUrl;
      let needsWindowing = false;

      // Try metadata with 8s timeout — if it fails, use recording list info to decide
      const metaUrl = `${baseUrl}/metadata`;
      debugLog('info', 'loadRecording', `checking metadata...`);
      let meta: { snapshot_count: number; time_window: { start_time: string; end_time: string }; requires_windowing: boolean } | null = null;
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 8000);
        const metaRes = await fetch(metaUrl, { signal: controller.signal });
        clearTimeout(timeout);
        if (metaRes.ok) {
          meta = await metaRes.json();
          needsWindowing = meta?.requires_windowing === true;
        }
      } catch {
        // Metadata endpoint timed out or failed — use hint from recording list if available
        needsWindowing = (hint?.state_count ?? 0) > 20000;
        if (!needsWindowing && hint?.state_count) {
          debugLog('info', 'loadRecording', `metadata timeout but hint says ${hint.state_count} states — loading fully`);
        } else if (needsWindowing) {
          debugLog('info', 'loadRecording', `metadata timeout, hint says ${hint?.state_count} states — using windowed load`);
        }
      }

      if (needsWindowing) {
        // Use metadata time_window if available, otherwise use hint from recording list
        const totalStart = meta?.time_window?.start_time ?? hint?.first_seen ?? `${date}T00:00:00`;
        const totalEnd = meta?.time_window?.end_time ?? hint?.last_seen ?? `${date}T23:59:59`;
        const windowEnd = new Date(new Date(totalStart).getTime() + WINDOW_HOURS * 3600000).toISOString();
        url += `?start_time=${encodeURIComponent(totalStart)}&end_time=${encodeURIComponent(windowEnd)}`;
        debugLog('info', 'loadRecording', `windowed load: ${totalStart} → ${windowEnd} (${meta?.snapshot_count ?? '?'} total snaps)`);

        recordingWindowRef.current = {
          airport, date,
          totalStartTime: totalStart,
          totalEndTime: totalEnd,
          loadedEndTime: windowEnd,
          windowHours: WINDOW_HOURS,
          isLoadingNext: false,
        };
      } else {
        debugLog('info', 'loadRecording', `small recording (${meta?.snapshot_count} snaps), loading fully`);
      }

      const res = await fetch(url);
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`${res.status} ${res.statusText}: ${body}`);
      }
      const data: SimulationData = await res.json();
      debugLog('info', 'loadRecording', `loaded ${data.frame_timestamps.length} frames, ${data.frame_count} frame_count`);

      // For windowed recordings, override frame_count to reflect total duration
      if (needsWindowing && recordingWindowRef.current) {
        const meta = recordingWindowRef.current;
        const totalDurationMs = new Date(meta.totalEndTime).getTime() - new Date(meta.totalStartTime).getTime();
        const loadedDurationMs = new Date(meta.loadedEndTime).getTime() - new Date(meta.totalStartTime).getTime();
        const estimatedTotalFrames = Math.round(
          (data.frame_timestamps.length / loadedDurationMs) * totalDurationMs
        );
        data.frame_count = estimatedTotalFrames;
      }

      setSimData(data);
      setSwitchPaused(false);
      setLoadedFile(`recording_${airport}_${date}`);
      setCurrentFrameIndex(0);
      setCurrentWindow(null);

      if (data.frame_timestamps.length > 0) {
        const firstTimestamp = data.frame_timestamps[0];
        const snapshots = data.frames[firstTimestamp] || [];
        setFlights(snapshots.map((s) => snapshotToFlight(s, 'opensky_recorded')));
      }

      setIsPlaying(true);
      wantsAutoPlayRef.current = false;
    } catch (err) {
      wantsAutoPlayRef.current = false;
      debugLog('error', 'loadRecording', `failed: ${err}`);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Pause simulation (for airport switch)
  const pauseForSwitch = useCallback(() => {
    wantsAutoPlayRef.current = false;
    setIsPlaying(false);
    setSwitchPaused(true);
  }, []);

  // Fetch markdown analysis report when a simulation file is loaded
  useEffect(() => {
    if (!loadedFile) {
      setMarkdownReport(null);
      return;
    }
    let cancelled = false;
    fetch(`/api/simulation/report/${encodeURIComponent(loadedFile)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled) setMarkdownReport(data?.content ?? null);
      })
      .catch(() => {
        if (!cancelled) setMarkdownReport(null);
      });
    return () => { cancelled = true; };
  }, [loadedFile]);

  // Update flights when frame index changes
  useEffect(() => {
    if (!simData || currentFrameIndex >= simData.frame_timestamps.length) return;
    const timestamp = simData.frame_timestamps[currentFrameIndex];
    const snapshots = simData.frames[timestamp] || [];
    const src = dataSourceRef.current;
    // Filter out departing enroute flights (at cruise altitude, heading away).
    // Airport center for coordinate bounds checking.
    // New sim files include airport_center in config; older files fall back to
    // median of parked flights in the current frame.
    const cfg = simData.config as Record<string, unknown>;
    const cfgCenter = cfg.airport_center as { latitude: number; longitude: number } | undefined;
    let centerLat = cfgCenter?.latitude;
    let centerLon = cfgCenter?.longitude;
    if (centerLat == null || centerLon == null) {
      const parked = snapshots.filter(s => s.phase === 'parked' && s.latitude && s.longitude);
      if (parked.length > 0) {
        const lats = parked.map(s => s.latitude).sort((a, b) => a - b);
        const lons = parked.map(s => s.longitude).sort((a, b) => a - b);
        centerLat = lats[Math.floor(lats.length / 2)];
        centerLon = lons[Math.floor(lons.length / 2)];
      }
    }
    const MAX_GROUND_DIST_SQ = 0.05 * 0.05; // ~3 NM — no airport taxi exceeds this
    const MAX_AIRBORNE_DIST_SQ = 0.4 * 0.4; // ~0.4° ≈ 25 NM — hide departing/arriving beyond this
    const groundPhases = new Set(['taxi_in', 'taxi_out', 'parked', 'pushback']);

    const relevant = snapshots.filter((s) => {
      if (centerLat == null || centerLon == null) return true;
      const dLat = s.latitude - centerLat;
      const dLon = s.longitude - centerLon!;
      const distSq = dLat * dLat + dLon * dLon;

      if (groundPhases.has(s.phase)) {
        return distSq <= MAX_GROUND_DIST_SQ;
      }
      // All airborne phases: hide when beyond visibility radius
      return distSq <= MAX_AIRBORNE_DIST_SQ;
    });

    // Persist flights across thinning gaps: if a flight was visible recently
    // but has no snapshot in this frame, keep showing it at its last position.
    const seenIds = new Set(relevant.map(s => s.icao24));
    const MAX_GAP_FRAMES = 30; // keep visible for ~30 frames (~60s at 2s/frame)
    for (const [id, cached] of lastSeenRef.current) {
      if (!seenIds.has(id) && currentFrameIndex - cached.frameIndex <= MAX_GAP_FRAMES) {
        const snap = cached.snap;
        // Don't persist tracked flight — let it disappear cleanly at boundary
        if (id === trackedIcao24Ref.current) continue;
        // Apply same distance filter to cached snapshots
        if (centerLat != null && centerLon != null) {
          const dLat = snap.latitude - centerLat;
          const dLon = snap.longitude - centerLon!;
          const distSq = dLat * dLat + dLon * dLon;
          const limit = groundPhases.has(snap.phase) ? MAX_GROUND_DIST_SQ : MAX_AIRBORNE_DIST_SQ;
          if (distSq > limit) continue;
        }
        relevant.push(snap);
        seenIds.add(id);
      }
    }

    // Update last-seen cache
    for (const s of relevant) {
      lastSeenRef.current.set(s.icao24, { snap: s, frameIndex: currentFrameIndex });
    }
    // Prune old entries
    for (const [id, cached] of lastSeenRef.current) {
      if (currentFrameIndex - cached.frameIndex > MAX_GAP_FRAMES * 2) {
        lastSeenRef.current.delete(id);
      }
    }

    // Drop airborne flights whose position hasn't changed for 5+ frames (stale/frozen)
    const STALE_THRESHOLD = 5;
    const filtered = relevant.filter((s) => {
      if (groundPhases.has(s.phase)) return true; // parked/taxi can be stationary
      const prev = staleCountRef.current.get(s.icao24);
      if (prev && Math.abs(s.latitude - prev.lat) < 0.0001 && Math.abs(s.longitude - prev.lon) < 0.0001) {
        prev.count++;
        if (prev.count >= STALE_THRESHOLD) return false;
      } else {
        staleCountRef.current.set(s.icao24, { lat: s.latitude, lon: s.longitude, count: 0 });
      }
      return true;
    });

    setFlights(filtered.map((s) => snapshotToFlight(s, src)));
  }, [simData, currentFrameIndex]);

  // Compute sim-seconds between consecutive frames from the loaded data.
  // Falls back to 30 if data is insufficient.
  const simSecondsPerFrame = (() => {
    if (!simData || simData.frame_timestamps.length < 2) return 30;
    const t0 = new Date(simData.frame_timestamps[0]).getTime();
    const t1 = new Date(simData.frame_timestamps[1]).getTime();
    const diff = (t1 - t0) / 1000;
    return diff > 0 ? diff : 30;
  })();

  // Playback interval — advances frame index.
  // Base rate: 1x = 1 sim-minute per real second (60 sim-sec/real-sec).
  // framesPerRealSecond = 60 * speed / simSecondsPerFrame
  // If ≤60 fps: one frame per tick at interval = 1000/fps.
  // If >60 fps: multiple frames per 16ms tick.
  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (!isPlaying || !simData) return;

    const framesPerRealSecond = (60 * speed) / simSecondsPerFrame;
    let intervalMs: number;
    let framesPerTick: number;

    if (framesPerRealSecond <= 60) {
      intervalMs = Math.round(1000 / framesPerRealSecond);
      framesPerTick = 1;
    } else {
      intervalMs = 16;
      framesPerTick = Math.ceil(framesPerRealSecond / 60);
    }

    intervalRef.current = setInterval(() => {
      setCurrentFrameIndex((prev) => {
        const next = prev + framesPerTick;
        // Stop at end of loaded frames (not estimated total — more may be loading)
        const loadedCount = simData?.frame_timestamps.length ?? 0;
        if (next >= loadedCount) {
          // If we have a windowing ref with more data coming, pause at boundary
          if (recordingWindowRef.current && new Date(recordingWindowRef.current.loadedEndTime) < new Date(recordingWindowRef.current.totalEndTime)) {
            return Math.min(prev, loadedCount - 1);
          }
          setIsPlaying(false);
          return Math.min(prev, loadedCount - 1);
        }
        return next;
      });
    }, intervalMs);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isPlaying, speed, simData, simSecondsPerFrame]);

  // Defensive auto-play: if a load function requested auto-play but the
  // inline setIsPlaying(true) was lost (e.g. React batching edge case or
  // a concurrent effect resetting state), this effect catches it.
  useEffect(() => {
    if (wantsAutoPlayRef.current && simData && !isPlaying && !isLoading) {
      wantsAutoPlayRef.current = false;
      setIsPlaying(true);
    }
  }, [simData, isPlaying, isLoading]);

  // Auto-load next window for large recordings when approaching end of loaded data
  useEffect(() => {
    const win = recordingWindowRef.current;
    if (!win || !simData || !isPlaying || win.isLoadingNext) return;

    const loadedFrameCount = simData.frame_timestamps.length;
    const threshold = Math.floor(loadedFrameCount * 0.8);
    if (currentFrameIndex < threshold) return;

    // Already loaded everything?
    if (new Date(win.loadedEndTime) >= new Date(win.totalEndTime)) return;

    win.isLoadingNext = true;
    const nextStart = win.loadedEndTime;
    const nextEndMs = new Date(nextStart).getTime() + win.windowHours * 3600000;
    const nextEnd = new Date(Math.min(nextEndMs, new Date(win.totalEndTime).getTime())).toISOString();

    debugLog('info', 'loadRecording', `prefetching next window: ${nextStart} → ${nextEnd}`);

    const url = `/api/opensky/recordings/${encodeURIComponent(win.airport)}/${encodeURIComponent(win.date)}?start_time=${encodeURIComponent(nextStart)}&end_time=${encodeURIComponent(nextEnd)}`;

    fetch(url)
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((nextData: SimulationData) => {
        setSimData((prev) => {
          if (!prev) return prev;
          const mergedFrames = { ...prev.frames };
          const mergedTimestamps = [...prev.frame_timestamps];
          for (const ts of nextData.frame_timestamps) {
            if (!mergedFrames[ts]) {
              mergedFrames[ts] = nextData.frames[ts];
              mergedTimestamps.push(ts);
            }
          }
          mergedTimestamps.sort();
          return {
            ...prev,
            frames: mergedFrames,
            frame_timestamps: mergedTimestamps,
            frame_count: prev.frame_count, // keep estimated total
            phase_transitions: [...prev.phase_transitions, ...nextData.phase_transitions],
            gate_events: [...prev.gate_events, ...nextData.gate_events],
            scenario_events: [...prev.scenario_events, ...nextData.scenario_events],
          };
        });
        win.loadedEndTime = nextEnd;
        win.isLoadingNext = false;
        debugLog('info', 'loadRecording', `appended window, loaded up to ${nextEnd}`);
      })
      .catch((err) => {
        debugLog('error', 'loadRecording', `prefetch failed: ${err}`);
        win.isLoadingNext = false;
      });
  }, [currentFrameIndex, simData, isPlaying]);

  const play = useCallback(() => {
    if (!simData) return;
    // If at end, restart
    if (currentFrameIndex >= simData.frame_count - 1) {
      setCurrentFrameIndex(0);
    }
    setIsPlaying(true);
  }, [simData, currentFrameIndex]);

  const pause = useCallback(() => {
    wantsAutoPlayRef.current = false;
    setIsPlaying(false);
  }, []);

  const togglePlayPause = useCallback(() => {
    if (isPlaying) {
      pause();
    } else {
      play();
    }
  }, [isPlaying, play, pause]);

  const seekTo = useCallback((frameIndex: number) => {
    setCurrentFrameIndex(Math.max(0, Math.min(frameIndex, totalFrames - 1)));
  }, [totalFrames]);

  const seekToPercent = useCallback((pct: number) => {
    if (totalFrames === 0) return;
    const idx = Math.round((pct / 100) * (totalFrames - 1));
    seekTo(idx);
  }, [totalFrames, seekTo]);

  const seekToTime = useCallback((isoTime: string) => {
    if (!simData || simData.frame_timestamps.length === 0) return;
    const targetMs = new Date(isoTime).getTime();
    let bestIdx = 0;
    let bestDiff = Infinity;
    for (let i = 0; i < simData.frame_timestamps.length; i++) {
      const diff = Math.abs(new Date(simData.frame_timestamps[i]).getTime() - targetMs);
      if (diff < bestDiff) {
        bestDiff = diff;
        bestIdx = i;
      }
    }
    seekTo(bestIdx);
  }, [simData, seekTo]);

  const seekToFlight = useCallback((isoTime: string, icao24: string, callsign?: string): boolean => {
    if (!simData || simData.frame_timestamps.length === 0) return false;
    const targetMs = new Date(isoTime).getTime();
    let centerIdx = 0;
    let bestDiff = Infinity;
    for (let i = 0; i < simData.frame_timestamps.length; i++) {
      const diff = Math.abs(new Date(simData.frame_timestamps[i]).getTime() - targetMs);
      if (diff < bestDiff) { bestDiff = diff; centerIdx = i; }
    }
    const maxSearch = 30;
    for (let offset = 0; offset <= maxSearch; offset++) {
      for (const idx of offset === 0 ? [centerIdx] : [centerIdx - offset, centerIdx + offset]) {
        if (idx < 0 || idx >= simData.frame_timestamps.length) continue;
        const ts = simData.frame_timestamps[idx];
        const snapshots = simData.frames[ts] || [];
        const match = snapshots.find(s =>
          (s.icao24 === icao24 || (callsign && s.callsign?.replace(/\s+/g, '') === callsign))
        );
        if (match) {
          trackedIcao24Ref.current = match.icao24;
          debugLog('info', 'seekToFlight', 'found flight', {
            icao24, callsign, offset, frameIdx: idx, phase: match.phase,
            totalFrames: simData.frame_timestamps.length,
          });
          seekTo(idx);
          return true;
        }
      }
    }
    const centerTs = simData.frame_timestamps[centerIdx];
    const centerSnaps = simData.frames[centerTs] || [];
    const anyMatch = centerSnaps.find(s =>
      s.icao24 === icao24 || (callsign && s.callsign?.replace(/\s+/g, '') === callsign)
    );
    debugLog('warn', 'seekToFlight', 'flight not found in ±30 frames', {
      icao24, callsign, centerIdx, centerTime: centerTs,
      totalFrames: simData.frame_timestamps.length,
      nearestMatchPhase: anyMatch?.phase ?? 'absent',
      flightsAtCenter: centerSnaps.length,
    });
    seekTo(centerIdx);
    return false;
  }, [simData, seekTo]);

  const stop = useCallback(() => {
    wantsAutoPlayRef.current = false;
    trackedIcao24Ref.current = null;
    setIsPlaying(false);
    setSimData(null);
    setLoadedFile(null);
    setCurrentFrameIndex(0);
    setFlights([]);
    setSwitchPaused(false);
    setMetadata(null);
    setCurrentWindow(null);
    lastSeenRef.current.clear();
    dataSourceRef.current = 'simulation';
  }, []);

  // Phase groups for trajectory segmentation.
  // Airborne segments only — taxi/ground movement creates messy zigzag lines.
  const ARRIVAL_AIRBORNE = new Set(['approaching', 'landing']);
  const DEPARTURE_AIRBORNE = new Set(['takeoff', 'departing', 'enroute']);
  // Ground segments shown separately when the flight is on the ground.
  const ARRIVAL_GROUND = new Set(['taxi_to_gate']);
  const DEPARTURE_GROUND = new Set(['pushback', 'taxi_to_runway']);

  // Extract trajectory for a flight, scoped to the current phase segment
  const getFlightTrajectory = useCallback((icao24: string): SimTrajectoryPoint[] => {
    if (!simData) return [];

    const timestamps = simData.frame_timestamps;
    if (timestamps.length === 0) return [];

    // Determine the flight's current phase from the current frame.
    // If the flight has no snapshot in this exact frame (thinning gap),
    // search backward for the most recent snapshot to avoid losing the
    // trajectory during phase transitions (e.g., go-around ENROUTE).
    let currentSnap: PositionSnapshot | undefined;
    for (let i = currentFrameIndex; i >= Math.max(0, currentFrameIndex - 30); i--) {
      const ts = timestamps[i];
      const snaps = ts ? simData.frames[ts] : null;
      const snap = snaps?.find(s => s.icao24 === icao24);
      if (snap) { currentSnap = snap; break; }
    }
    const currentPhase = currentSnap?.phase ?? '';

    // Pick the right phase set based on current flight phase:
    // - Airborne arrival (approaching/landing/go-around enroute) → show full arrival trajectory
    // - Ground arrival (taxi_to_gate) → show taxi-in path
    // - Parked → no trajectory
    // - Ground departure (pushback/taxi_to_runway) → show taxi-out path
    // - Airborne departure (takeoff/departing/enroute) → show departure trajectory
    let allowedPhases: Set<string>;
    if (ARRIVAL_AIRBORNE.has(currentPhase) ||
        (currentPhase === 'enroute' && currentSnap)) {
      // Include enroute so trajectory bridges across go-around interludes
      allowedPhases = new Set([...ARRIVAL_AIRBORNE, 'enroute']);
    } else if (ARRIVAL_GROUND.has(currentPhase)) {
      allowedPhases = ARRIVAL_GROUND;
    } else if (DEPARTURE_GROUND.has(currentPhase)) {
      allowedPhases = DEPARTURE_GROUND;
    } else if (DEPARTURE_AIRBORNE.has(currentPhase)) {
      allowedPhases = DEPARTURE_AIRBORNE;
    } else {
      // parked or unknown — no trajectory
      return [];
    }

    // Airport center for distance-based enroute filtering
    const cfg = simData.config as Record<string, unknown>;
    const cfgCenter = cfg.airport_center as { latitude: number; longitude: number } | undefined;
    const apLat = cfgCenter?.latitude;
    const apLon = cfgCenter?.longitude;

    // Check if a snapshot is valid for the trajectory segment.
    // For enroute frames, only include those near the airport and below the
    // altitude ceiling (go-around pattern). Distant/high enroute = cruise.
    const MAX_ENROUTE_DIST_SQ = 0.3 * 0.3; // ~0.3° ≈ 20 NM from airport
    const isTracked = icao24 === trackedIcao24Ref.current;
    const isValidForSegment = (snap: PositionSnapshot): boolean => {
      if (!allowedPhases.has(snap.phase)) return false;
      if (snap.phase === 'enroute' && !isTracked) {
        if (snap.altitude > GO_AROUND_ALT_CEILING) return false;
        if (apLat != null && apLon != null) {
          const dLat = snap.latitude - apLat;
          const dLon = snap.longitude - apLon;
          if (dLat * dLat + dLon * dLon > MAX_ENROUTE_DIST_SQ) return false;
        }
      }
      return true;
    };

    // Collect points for the CURRENT continuous segment only.
    // The segment spans across go-around enroute interludes (low altitude)
    // but stops at high-altitude enroute (initial cruise entry).

    // Step 1: Scan backward from current frame to find segment start.
    // Skip frames where the flight has no snapshot (thinned holding recordings
    // only emit every 30s but frames arrive every few seconds). Only break
    // when a snapshot IS found but fails the phase/altitude filter — the
    // altitude ceiling provides the natural break at initial cruise entry.
    let segStart = currentFrameIndex;
    for (let i = currentFrameIndex - 1; i >= 0; i--) {
      const ts = timestamps[i];
      const snapshots = simData.frames[ts];
      if (!snapshots) continue;
      const snap = snapshots.find(s => s.icao24 === icao24);
      if (!snap) continue;
      if (!isValidForSegment(snap)) break;
      segStart = i;
    }

    // Step 2: Scan forward from current frame to find segment end.
    let segEnd = currentFrameIndex;
    for (let i = currentFrameIndex + 1; i < timestamps.length; i++) {
      const ts = timestamps[i];
      const snapshots = simData.frames[ts];
      if (!snapshots) continue;
      const snap = snapshots.find(s => s.icao24 === icao24);
      if (!snap) continue;
      if (!isValidForSegment(snap)) break;
      segEnd = i;
    }

    // Step 3: Collect points from segment range
    const allPoints: SimTrajectoryPoint[] = [];
    for (let i = segStart; i <= segEnd; i++) {
      const ts = timestamps[i];
      const snapshots = simData.frames[ts];
      if (!snapshots) continue;
      const snap = snapshots.find(s => s.icao24 === icao24);
      if (snap && snap.latitude != null && snap.longitude != null && isValidForSegment(snap)) {
        allPoints.push({
          latitude: snap.latitude,
          longitude: snap.longitude,
          altitude: snap.altitude,
          velocity: snap.velocity,
          heading: snap.heading,
          on_ground: snap.on_ground,
          flight_phase: snap.phase,
          timestamp: Math.floor(new Date(ts).getTime() / 1000),
        });
      }
    }

    // Downsample to max ~500 points if needed
    if (allPoints.length <= 500) return allPoints;
    const step = Math.ceil(allPoints.length / 500);
    const sampled: SimTrajectoryPoint[] = [];
    for (let i = 0; i < allPoints.length; i += step) {
      sampled.push(allPoints[i]);
    }
    // Always include the last point
    if (sampled[sampled.length - 1] !== allPoints[allPoints.length - 1]) {
      sampled.push(allPoints[allPoints.length - 1]);
    }
    return sampled;
  }, [simData, currentFrameIndex]);

  // Extract full flight log (all frames) for a given flight — used for CSV export
  const getFlightLog = useCallback((icao24: string): PositionSnapshot[] => {
    if (!simData) return [];
    const timestamps = simData.frame_timestamps;
    const log: PositionSnapshot[] = [];
    for (const ts of timestamps) {
      const snapshots = simData.frames[ts];
      if (!snapshots) continue;
      const snap = snapshots.find(s => s.icao24 === icao24);
      if (snap) log.push(snap);
    }
    return log;
  }, [simData]);

  // Expose control API on window for headless video renderer (Playwright)
  useEffect(() => {
    window.__simControl = {
      loadFile,
      seekTo,
      clearSwitchPause: () => setSwitchPaused(false),
      getInfo: () => ({
        totalFrames,
        currentFrame: currentFrameIndex,
        currentSimTime,
        isLoading,
        isActive,
        switchPaused,
      }),
    };
    return () => {
      delete window.__simControl;
    };
  }, [loadFile, seekTo, totalFrames, currentFrameIndex, currentSimTime, isLoading, isActive, switchPaused]);

  return {
    isActive,
    isPlaying,
    isLoading,
    isFetchingFiles,
    isFetchingMetadata,
    switchPaused,
    speed,
    currentFrameIndex,
    totalFrames,
    currentSimTime,
    flights,
    availableFiles,
    availableRecordings,
    isFetchingRecordings,
    loadedFile,
    summary: simData?.summary as Record<string, unknown> | null ?? null,
    scenarioEvents: simData?.scenario_events ?? [],
    scenarioName: (simData?.summary as Record<string, unknown>)?.scenario_name as string | null ?? null,
    schedule: simData?.schedule ?? [],
    airport: (simData?.config as Record<string, unknown>)?.airport as string | null ?? null,
    simStartTime,
    simEndTime,
    metadata,
    currentWindow,
    markdownReport,

    loadFile,
    loadWindow,
    loadDemo,
    loadRecording,
    fetchMetadata,
    fetchRecordings,
    play,
    pause,
    togglePlayPause,
    setSpeed,
    seekTo,
    seekToPercent,
    seekToTime,
    seekToFlight,
    stop,
    fetchFiles,
    pauseForSwitch,
    getFlightTrajectory,
    getFlightLog,
  };
}
