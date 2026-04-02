import { useState, useEffect, useRef, useCallback } from 'react';
import { Flight } from '../types/flight';

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

interface PositionSnapshot {
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
}

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

/** Map simulation phase names to the frontend flight_phase enum (fine-grained). */
function mapPhase(phase: string): Flight['flight_phase'] {
  const map: Record<string, Flight['flight_phase']> = {
    approaching: 'approaching',
    landing: 'landing',
    taxi_to_gate: 'taxi_in',
    parked: 'parked',
    pushback: 'pushback',
    taxi_to_runway: 'taxi_out',
    takeoff: 'takeoff',
    departing: 'departing',
    enroute: 'enroute',
  };
  return map[phase] ?? 'parked';
}

/** Convert a position snapshot to the Flight interface. */
function snapshotToFlight(snap: PositionSnapshot): Flight {
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
    data_source: 'simulation',
    flight_phase: mapPhase(snap.phase),
    aircraft_type: snap.aircraft_type,
    assigned_gate: snap.assigned_gate ?? null,
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

  // Actions
  loadFile: (filename: string, startHour?: number, endHour?: number) => Promise<void>;
  loadWindow: (filename: string, startTime: string, endTime: string) => Promise<void>;
  loadDemo: (airportIcao: string) => Promise<void>;
  fetchMetadata: (filename: string) => Promise<SimulationMetadata | null>;
  play: () => void;
  pause: () => void;
  togglePlayPause: () => void;
  setSpeed: (speed: PlaybackSpeed) => void;
  seekTo: (frameIndex: number) => void;
  seekToPercent: (pct: number) => void;
  stop: () => void;
  fetchFiles: () => Promise<void>;
  pauseForSwitch: () => void;
  getFlightTrajectory: (icao24: string) => SimTrajectoryPoint[];
}

// TypeScript declaration for the headless video renderer control API
declare global {
  interface Window {
    __simControl?: {
      loadFile: (filename: string, startHour?: number, endHour?: number) => Promise<void>;
      seekTo: (frameIndex: number) => void;
      getInfo: () => {
        totalFrames: number;
        currentFrame: number;
        isLoading: boolean;
        isActive: boolean;
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

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isActive = simData !== null;
  const totalFrames = simData?.frame_count ?? 0;
  const currentSimTime = simData && simData.frame_timestamps[currentFrameIndex]
    ? simData.frame_timestamps[currentFrameIndex]
    : null;
  const simStartTime = simData?.frame_timestamps?.[0] ?? null;
  const simEndTime = simData?.frame_timestamps?.[simData.frame_timestamps.length - 1] ?? null;

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
        setFlights(snapshots.map(snapshotToFlight));
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
        setFlights(snapshots.map(snapshotToFlight));
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
    setSwitchPaused(false);
    try {
      const res = await fetch(`/api/simulation/demo/${encodeURIComponent(airportIcao)}`);
      if (res.status === 202) {
        // Still generating — caller should retry
        console.log('Demo simulation still generating for', airportIcao);
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
        setFlights(snapshots.map(snapshotToFlight));
      }

      // Auto-play demo
      setIsPlaying(true);
    } catch (err) {
      console.error('Failed to load demo simulation:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Pause simulation (for airport switch)
  const pauseForSwitch = useCallback(() => {
    setIsPlaying(false);
    setSwitchPaused(true);
  }, []);

  // Update flights when frame index changes
  useEffect(() => {
    if (!simData || currentFrameIndex >= simData.frame_timestamps.length) return;
    const timestamp = simData.frame_timestamps[currentFrameIndex];
    const snapshots = simData.frames[timestamp] || [];
    setFlights(snapshots.map(snapshotToFlight));
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
        if (next >= (simData?.frame_count ?? 0)) {
          setIsPlaying(false);
          return Math.min(prev, (simData?.frame_count ?? 1) - 1);
        }
        return next;
      });
    }, intervalMs);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isPlaying, speed, simData, simSecondsPerFrame]);

  const play = useCallback(() => {
    if (!simData) return;
    // If at end, restart
    if (currentFrameIndex >= simData.frame_count - 1) {
      setCurrentFrameIndex(0);
    }
    setIsPlaying(true);
  }, [simData, currentFrameIndex]);

  const pause = useCallback(() => setIsPlaying(false), []);

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

  const stop = useCallback(() => {
    setIsPlaying(false);
    setSimData(null);
    setLoadedFile(null);
    setCurrentFrameIndex(0);
    setFlights([]);
    setSwitchPaused(false);
    setMetadata(null);
    setCurrentWindow(null);
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

    // Determine the flight's current phase from the current frame
    const currentTs = timestamps[currentFrameIndex];
    const currentSnaps = currentTs ? simData.frames[currentTs] : null;
    const currentSnap = currentSnaps?.find(s => s.icao24 === icao24);
    const currentPhase = currentSnap?.phase ?? '';

    // Pick the right phase set based on current flight phase:
    // - Airborne arrival (approaching/landing) → show approach trajectory
    // - Ground arrival (taxi_to_gate) → show taxi-in path
    // - Parked → no trajectory
    // - Ground departure (pushback/taxi_to_runway) → show taxi-out path
    // - Airborne departure (takeoff/departing/enroute) → show departure trajectory
    let allowedPhases: Set<string>;
    if (ARRIVAL_AIRBORNE.has(currentPhase)) {
      allowedPhases = ARRIVAL_AIRBORNE;
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

    // Collect all points for this flight in the allowed phase group
    const allPoints: SimTrajectoryPoint[] = [];
    for (let i = 0; i < timestamps.length; i++) {
      const ts = timestamps[i];
      const snapshots = simData.frames[ts];
      if (!snapshots) continue;
      const snap = snapshots.find(s => s.icao24 === icao24);
      if (snap && snap.latitude != null && snap.longitude != null && allowedPhases.has(snap.phase)) {
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

  // Expose control API on window for headless video renderer (Playwright)
  useEffect(() => {
    window.__simControl = {
      loadFile,
      seekTo,
      getInfo: () => ({
        totalFrames,
        currentFrame: currentFrameIndex,
        isLoading,
        isActive,
      }),
    };
    return () => {
      delete window.__simControl;
    };
  }, [loadFile, seekTo, totalFrames, currentFrameIndex, isLoading, isActive]);

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

    loadFile,
    loadWindow,
    loadDemo,
    fetchMetadata,
    play,
    pause,
    togglePlayPause,
    setSpeed,
    seekTo,
    seekToPercent,
    stop,
    fetchFiles,
    pauseForSwitch,
    getFlightTrajectory,
  };
}
