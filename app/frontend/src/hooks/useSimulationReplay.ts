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
  size_bytes?: number;
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
  assigned_gate?: string | null;
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
    vertical_rate: null,
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
  airport: string | null;
  simStartTime: string | null;
  simEndTime: string | null;

  // Actions
  loadFile: (filename: string, startHour?: number, endHour?: number) => Promise<void>;
  loadDemo: (airportIcao: string) => Promise<void>;
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
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);
  const [currentFrameIndex, setCurrentFrameIndex] = useState(0);
  const [flights, setFlights] = useState<Flight[]>([]);
  const [switchPaused, setSwitchPaused] = useState(false);

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
    setSwitchPaused(false);
  }, []);

  // Extract full trajectory for a flight across all simulation frames
  const getFlightTrajectory = useCallback((icao24: string): SimTrajectoryPoint[] => {
    if (!simData) return [];
    const points: SimTrajectoryPoint[] = [];
    const timestamps = simData.frame_timestamps;
    // Sample every Nth frame to avoid huge arrays (max ~500 points)
    const step = Math.max(1, Math.floor(timestamps.length / 500));
    for (let i = 0; i < timestamps.length; i += step) {
      const ts = timestamps[i];
      const snapshots = simData.frames[ts];
      if (!snapshots) continue;
      const snap = snapshots.find(s => s.icao24 === icao24);
      if (snap && snap.latitude != null && snap.longitude != null) {
        points.push({
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
    // Always include last frame if not already
    if (step > 1 && timestamps.length > 0) {
      const lastTs = timestamps[timestamps.length - 1];
      const lastSnaps = simData.frames[lastTs];
      if (lastSnaps) {
        const snap = lastSnaps.find(s => s.icao24 === icao24);
        if (snap && snap.latitude != null && snap.longitude != null) {
          const lastEpoch = Math.floor(new Date(lastTs).getTime() / 1000);
          if (points.length === 0 || points[points.length - 1].timestamp !== lastEpoch) {
            points.push({
              latitude: snap.latitude,
              longitude: snap.longitude,
              altitude: snap.altitude,
              velocity: snap.velocity,
              heading: snap.heading,
              on_ground: snap.on_ground,
              flight_phase: snap.phase,
              timestamp: lastEpoch,
            });
          }
        }
      }
    }
    return points;
  }, [simData]);

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
    airport: (simData?.config as Record<string, unknown>)?.airport as string | null ?? null,
    simStartTime,
    simEndTime,

    loadFile,
    loadDemo,
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
