import { createContext, useContext, useState, useMemo, ReactNode } from 'react';
import { useFlights } from '../hooks/useFlights';
import { Flight } from '../types/flight';

interface FlightContextType {
  flights: Flight[];
  selectedFlight: Flight | null;
  setSelectedFlight: (flight: Flight | null) => void;
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

  // Derive selected flight from current flights array
  // This ensures selection stays in sync with latest flight data
  const selectedFlight = useMemo(() => {
    if (!selectedFlightId) return null;
    return flights.find((f) => f.icao24 === selectedFlightId) || null;
  }, [flights, selectedFlightId]);

  // Wrapper to set selection by flight object or null
  const setSelectedFlight = (flight: Flight | null) => {
    setSelectedFlightId(flight?.icao24 || null);
  };

  return (
    <FlightContext.Provider value={{
      flights,
      selectedFlight,
      setSelectedFlight,
      isLoading,
      error,
      lastUpdated,
      dataSource
    }}>
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
