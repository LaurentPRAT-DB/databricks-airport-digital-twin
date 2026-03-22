import { createContext, useContext, useState, useMemo, useCallback, ReactNode } from 'react';
import { useFlights } from '../hooks/useFlights';
import { Flight } from '../types/flight';
import type { SimTrajectoryPoint } from '../hooks/useSimulationReplay';

/** Function that extracts trajectory from simulation frames for a given flight. */
export type SimTrajectoryProvider = (icao24: string) => SimTrajectoryPoint[];

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
  dataSource: 'live' | 'cached' | 'synthetic' | 'simulation' | null;
  simTrajectoryProvider: SimTrajectoryProvider | null;
}

const FlightContext = createContext<FlightContextType | null>(null);

export function FlightProvider({
  children,
  simulationFlights,
  simTrajectoryProvider,
}: {
  children: ReactNode;
  simulationFlights?: Flight[] | null;
  simTrajectoryProvider?: SimTrajectoryProvider | null;
}) {
  const { flights: liveFlights, isLoading, error, lastUpdated, dataSource: liveDataSource } = useFlights();

  // Use simulation flights when provided, otherwise live
  const flights = simulationFlights ?? liveFlights;
  const dataSource = simulationFlights ? 'simulation' as const : liveDataSource;
  // Phase filter state
  const [hiddenPhases, setHiddenPhasesState] = useState<Set<string>>(new Set());

  // Flights filtered by visible phases
  const filteredFlights = useMemo(() => {
    if (hiddenPhases.size === 0) return flights;
    return flights.filter(f => !hiddenPhases.has(f.flight_phase));
  }, [flights, hiddenPhases]);

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

  // Store selection by icao24 ID so it persists across data refreshes
  const [selectedFlightId, setSelectedFlightId] = useState<string | null>(null);
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
    isLoading,
    error,
    lastUpdated,
    dataSource,
    simTrajectoryProvider: simTrajectoryProvider ?? null,
  }), [flights, filteredFlights, hiddenPhases, togglePhase, setHiddenPhases, selectedFlight, setSelectedFlight, showTrajectory, setShowTrajectory, isLoading, error, lastUpdated, dataSource, simTrajectoryProvider]);

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
