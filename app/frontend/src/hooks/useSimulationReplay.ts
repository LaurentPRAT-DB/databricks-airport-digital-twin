import { useState, useEffect, useRef, useCallback } from 'react';
import { Flight } from '../types/flight';

export type PlaybackSpeed = 1 | 2 | 5 | 10 | 30 | 60;

export interface SimulationFile {
  filename: string;
  airport: string;
  total_flights: number;
  arrivals: number;
  departures: number;
  duration_hours: number;
  size_kb: number;
  scenario_name?: string | null;
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

/** Map simulation phase names to the frontend flight_phase enum. */
function mapPhase(phase: string): Flight['flight_phase'] {
  switch (phase) {
    case 'approaching':
    case 'landing':
      return 'descending';
    case 'taxi_to_gate':
    case 'parked':
    case 'pushback':
    case 'taxi_to_runway':
      return 'ground';
    case 'takeoff':
    case 'departing':
      return 'climbing';
    default:
      return 'ground';
  }
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
    vertical_rate: null,
    last_seen: snap.time,
    data_source: 'simulation',
    flight_phase: mapPhase(snap.phase),
    aircraft_type: snap.aircraft_type,
  };
}

export interface UseSimulationReplayResult {
  // State
  isActive: boolean;
  isPlaying: boolean;
  isLoading: boolean;
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
  simStartTime: string | null;
  simEndTime: string | null;

  // Actions
  loadFile: (filename: string, startHour?: number, endHour?: number) => Promise<void>;
  play: () => void;
  pause: () => void;
  togglePlayPause: () => void;
  setSpeed: (speed: PlaybackSpeed) => void;
  seekTo: (frameIndex: number) => void;
  seekToPercent: (pct: number) => void;
  stop: () => void;
  fetchFiles: () => Promise<void>;
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
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);
  const [currentFrameIndex, setCurrentFrameIndex] = useState(0);
  const [flights, setFlights] = useState<Flight[]>([]);

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
    try {
      const res = await fetch('/api/simulation/files');
      if (res.ok) {
        const data = await res.json();
        setAvailableFiles(data.files || []);
      }
    } catch {
      // Silently fail — simulation might not be available
    }
  }, []);

  // Load a simulation file
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

  // Update flights when frame index changes
  useEffect(() => {
    if (!simData || currentFrameIndex >= simData.frame_timestamps.length) return;
    const timestamp = simData.frame_timestamps[currentFrameIndex];
    const snapshots = simData.frames[timestamp] || [];
    setFlights(snapshots.map(snapshotToFlight));
  }, [simData, currentFrameIndex]);

  // Playback interval — advances frame index
  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (!isPlaying || !simData) return;

    // Base interval: simulation snapshots are every 30 sim-seconds.
    // At 1x speed, advance 1 frame per 1000ms (1 real second = 30 sim seconds).
    // At 60x speed, advance 1 frame per ~16ms.
    const intervalMs = Math.max(16, Math.round(1000 / speed));

    intervalRef.current = setInterval(() => {
      setCurrentFrameIndex((prev) => {
        const next = prev + 1;
        if (next >= (simData?.frame_count ?? 0)) {
          setIsPlaying(false);
          return prev;
        }
        return next;
      });
    }, intervalMs);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isPlaying, speed, simData]);

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
  }, []);

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
    simStartTime,
    simEndTime,

    loadFile,
    play,
    pause,
    togglePlayPause,
    setSpeed,
    seekTo,
    seekToPercent,
    stop,
    fetchFiles,
  };
}
