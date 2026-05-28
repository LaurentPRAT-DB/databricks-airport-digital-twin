import { createContext, useContext, useState, useMemo, useCallback, useEffect, useRef, ReactNode } from 'react';
import { useFlights } from '../hooks/useFlights';
import { Flight, DelayPrediction } from '../types/flight';
import type { SimTrajectoryPoint, PositionSnapshot } from '../hooks/useSimulationReplay';
import { usePredictions } from '../hooks/usePredictions';
import { useAirportConfigContext } from './AirportConfigContext';

/** Function that extracts trajectory from simulation frames for a given flight. */
export type SimTrajectoryProvider = (icao24: string) => SimTrajectoryPoint[];

/** Function that extracts full flight log (all frames) for CSV export. */
export type SimFlightLogProvider = (icao24: string) => PositionSnapshot[];

export type DataMode = 'simulation' | 'live' | 'recorded';

interface FlightContextType {
  flights: Flight[];
  filteredFlights: Flight[];
  hiddenPhases: Set<string>;
  togglePhase: (phase: string) => void;
  setHiddenPhases: (phases: Set<string>) => void;
  selectedFlight: Flight | null;
  setSelectedFlight: (flight: Flight | null) => void;
  showTrajectory: boolean;
  setShowTrajectory: (show: boolean) => void;
  isLoading: boolean;
  error: Error | null;
  lastUpdated: string | null;
  dataSource: 'live' | 'cached' | 'synthetic' | 'simulation' | 'opensky' | 'opensky_recorded' | null;
  simTrajectoryProvider: SimTrajectoryProvider | null;
  simFlightLogProvider: SimFlightLogProvider | null;
  dataMode: DataMode;
  setDataMode: (mode: DataMode) => void;
  delayMap: Map<string, DelayPrediction>;
  delayedCount: number;
}

const FlightContext = createContext<FlightContextType | null>(null);

export function FlightProvider({
  children,
  simulationFlights,
  simTrajectoryProvider,
  simFlightLogProvider,
}: {
  children: ReactNode;
  simulationFlights?: Flight[] | null;
  simTrajectoryProvider?: SimTrajectoryProvider | null;
  simFlightLogProvider?: SimFlightLogProvider | null;
}) {
  const { flights: liveFlights, isLoading, error, lastUpdated, dataSource: liveDataSource } = useFlights();

  const { currentAirport, getAirportCenter } = useAirportConfigContext();

  // Data mode: persisted to localStorage so live mode survives page reload
  const [dataMode, setDataModeState] = useState<DataMode>(() => {
    try {
      const stored = localStorage.getItem('airport-dt-data-mode');
      if (stored === 'live' || stored === 'recorded' || stored === 'simulation') return stored;
    } catch { /* SSR / test env */ }
    return 'simulation';
  });
  const [openSkyFlights, setOpenSkyFlights] = useState<Flight[]>([]);
  const [openSkyLoading, setOpenSkyLoading] = useState(false);
  const [openSkyLastUpdated, setOpenSkyLastUpdated] = useState<string | null>(null);
  const openSkyIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Live position history for trajectory trails
  const liveTrailsRef = useRef<Map<string, SimTrajectoryPoint[]>>(new Map());
  const [trailVersion, setTrailVersion] = useState(0);
  const MAX_TRAIL_POINTS = 200;

  // Fetch OpenSky flights
  const fetchOpenSkyFlights = useCallback(async () => {
    try {
      setOpenSkyLoading(true);
      const params = currentAirport ? `?airport=${encodeURIComponent(currentAirport)}` : '';
      const res = await fetch(`/api/opensky/flights${params}`);
      if (res.ok) {
        const data = await res.json();
        const nowEpoch = Date.now() / 1000;
        const flights: Flight[] = (data.flights || []).map((f: Record<string, unknown>) => ({
          ...f,
          data_source: 'opensky',
          flight_phase: f.flight_phase || 'cruise',
          last_seen: typeof f.last_seen === 'number' ? new Date(Number(f.last_seen) * 1000).toISOString() : String(f.last_seen || ''),
        }));

        // Accumulate position history for trajectory trails
        const trails = liveTrailsRef.current;
        const seenIcaos = new Set<string>();
        for (const f of flights) {
          const id = f.icao24;
          seenIcaos.add(id);
          if (f.latitude == null || f.longitude == null) continue;
          const point: SimTrajectoryPoint = {
            latitude: Number(f.latitude),
            longitude: Number(f.longitude),
            altitude: Number(f.altitude ?? 0),
            velocity: Number(f.velocity ?? 0),
            heading: Number(f.heading ?? 0),
            on_ground: !!f.on_ground,
            flight_phase: f.flight_phase || 'cruise',
            timestamp: nowEpoch,
          };
          const trail = trails.get(id);
          if (trail) {
            const last = trail[trail.length - 1];
            if (Math.abs(last.latitude - point.latitude) > 0.0001 || Math.abs(last.longitude - point.longitude) > 0.0001) {
              trail.push(point);
              if (trail.length > MAX_TRAIL_POINTS) trail.shift();
            }
          } else {
            trails.set(id, [point]);
          }
        }
        // Prune trails for aircraft no longer visible
        for (const id of trails.keys()) {
          if (!seenIcaos.has(id)) trails.delete(id);
        }

        setTrailVersion(v => v + 1);
        setOpenSkyFlights(flights);
        setOpenSkyLastUpdated(new Date().toISOString());
      }
    } catch {
      // Silently fail — will retry on next interval
    } finally {
      setOpenSkyLoading(false);
    }
  }, [currentAirport]);

  // Poll OpenSky when in live mode
  useEffect(() => {
    if (dataMode === 'live') {
      liveTrailsRef.current.clear();
      fetchOpenSkyFlights();
      openSkyIntervalRef.current = setInterval(fetchOpenSkyFlights, 15000);
      return () => {
        if (openSkyIntervalRef.current) clearInterval(openSkyIntervalRef.current);
      };
    } else {
      setOpenSkyFlights([]);
      liveTrailsRef.current.clear();
      if (openSkyIntervalRef.current) clearInterval(openSkyIntervalRef.current);
    }
  }, [dataMode, fetchOpenSkyFlights]);

  // Live trajectory provider — returns accumulated trail for a given flight
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const liveTrajectoryProvider = useCallback((icao24: string): SimTrajectoryPoint[] => {
    return [...(liveTrailsRef.current.get(icao24) || [])];
  }, [trailVersion]);

  const setDataMode = useCallback((mode: DataMode) => {
    setDataModeState(mode);
    try { localStorage.setItem('airport-dt-data-mode', mode); } catch { /* test env */ }
  }, []);

  // Use simulation flights when provided, otherwise live/opensky based on mode
  // In recorded mode, ONLY show recording flights — never fall back to WebSocket demo data
  const flights = dataMode === 'live'
    ? openSkyFlights
    : dataMode === 'recorded'
      ? (simulationFlights ?? [])
      : (simulationFlights ?? liveFlights);
  const dataSource = dataMode === 'live'
    ? 'opensky' as const
    : dataMode === 'recorded'
      ? 'opensky_recorded' as const
      : (simulationFlights ? 'simulation' as const : liveDataSource);
  // Delay predictions — polls /api/predictions/delays every 30s
  const { delays: delayMap } = usePredictions(flights);
  const delayedCount = useMemo(() => {
    let count = 0;
    delayMap.forEach((pred) => { if (pred.delay_minutes > 15) count++; });
    return count;
  }, [delayMap]);

  // PWA Badge — show delayed flight count on app icon
  useEffect(() => {
    if (!('setAppBadge' in navigator)) return;
    if (delayedCount > 0) {
      navigator.setAppBadge(delayedCount).catch(() => {});
    } else {
      navigator.clearAppBadge().catch(() => {});
    }
  }, [delayedCount]);

  // Phase filter state
  const [hiddenPhases, setHiddenPhasesState] = useState<Set<string>>(new Set());

  // Store selection by icao24 ID so it persists across data refreshes
  const [selectedFlightId, setSelectedFlightId] = useState<string | null>(null);

  // Flights filtered by visible phases + enroute proximity filter
  const filteredFlights = useMemo(() => {
    let result = flights;

    if (hiddenPhases.size > 0) {
      result = result.filter(f => !hiddenPhases.has(f.flight_phase));
    }

    // Hide enroute/cruising flights near the airport (~10nm) unless selected
    const center = getAirportCenter();
    result = result.filter(f => {
      if (f.flight_phase !== 'enroute' && f.flight_phase !== 'cruising') return true;
      if (f.icao24 === selectedFlightId) return true;
      const dLat = Math.abs(f.latitude - center.lat);
      const dLon = Math.abs(f.longitude - center.lon);
      return dLat > 0.165 || dLon > 0.165; // ~10nm
    });

    return result;
  }, [flights, hiddenPhases, selectedFlightId, getAirportCenter]);

  const togglePhase = useCallback((phase: string) => {
    setHiddenPhasesState(prev => {
      const next = new Set(prev);
      if (next.has(phase)) next.delete(phase);
      else next.add(phase);
      return next;
    });
  }, []);

  const setHiddenPhases = useCallback((phases: Set<string>) => {
    setHiddenPhasesState(phases);
  }, []);
  // Trajectory display toggle
  const [showTrajectory, setShowTrajectoryState] = useState(false);

  // Derive selected flight from current flights array
  // This ensures selection stays in sync with latest flight data
  const selectedFlight = useMemo(() => {
    if (!selectedFlightId) return null;
    return flights.find((f) => f.icao24 === selectedFlightId) || null;
  }, [flights, selectedFlightId]);

  // Stable callback for setting selected flight
  const setSelectedFlight = useCallback((flight: Flight | null) => {
    setSelectedFlightId(flight?.icao24 || null);
    // Auto-enable trajectory when selecting, disable when deselecting
    setShowTrajectoryState(!!flight);
  }, []);

  // Stable callback for trajectory toggle
  const setShowTrajectory = useCallback((show: boolean) => {
    setShowTrajectoryState(show);
  }, []);

  // Memoize context value to prevent unnecessary re-renders
  const contextValue = useMemo(() => ({
    flights,
    filteredFlights,
    hiddenPhases,
    togglePhase,
    setHiddenPhases,
    selectedFlight,
    setSelectedFlight,
    showTrajectory,
    setShowTrajectory,
    isLoading: dataMode === 'live' ? openSkyLoading : isLoading,
    error,
    lastUpdated: dataMode === 'live' ? openSkyLastUpdated : lastUpdated,
    dataSource,
    simTrajectoryProvider: dataMode === 'live' ? liveTrajectoryProvider : (simTrajectoryProvider ?? null),
    simFlightLogProvider: simFlightLogProvider ?? null,
    dataMode,
    setDataMode,
    delayMap,
    delayedCount,
  }), [flights, filteredFlights, hiddenPhases, togglePhase, setHiddenPhases, selectedFlight, setSelectedFlight, showTrajectory, setShowTrajectory, isLoading, error, lastUpdated, dataSource, simTrajectoryProvider, simFlightLogProvider, dataMode, setDataMode, openSkyLoading, openSkyLastUpdated, liveTrajectoryProvider, delayMap, delayedCount]);

  return (
    <FlightContext.Provider value={contextValue}>
      {children}
    </FlightContext.Provider>
  );
}

export function useFlightContext() {
  const context = useContext(FlightContext);
  if (!context) {
    throw new Error('useFlightContext must be used within FlightProvider');
  }
  return context;
}
