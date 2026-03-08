import { createContext, useContext, useState, useMemo, useCallback, ReactNode } from 'react';
import { useFlights } from '../hooks/useFlights';
import { Flight } from '../types/flight';

interface FlightContextType {
  flights: Flight[];
  selectedFlight: Flight | null;
  setSelectedFlight: (flight: Flight | null) => void;
  showTrajectory: boolean;
  setShowTrajectory: (show: boolean) => void;
  isLoading: boolean;
  error: Error | null;
  lastUpdated: string | null;
  dataSource: 'live' | 'cached' | 'synthetic' | null;
}

const FlightContext = createContext<FlightContextType | null>(null);

export function FlightProvider({ children }: { children: ReactNode }) {
  const { flights, isLoading, error, lastUpdated, dataSource } = useFlights();
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
    selectedFlight,
    setSelectedFlight,
    showTrajectory,
    setShowTrajectory,
    isLoading,
    error,
    lastUpdated,
    dataSource,
  }), [flights, selectedFlight, setSelectedFlight, showTrajectory, setShowTrajectory, isLoading, error, lastUpdated, dataSource]);

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
