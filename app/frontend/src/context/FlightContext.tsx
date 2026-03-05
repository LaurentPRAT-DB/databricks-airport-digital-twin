import { createContext, useContext, useState, ReactNode } from 'react';
import { useFlights } from '../hooks/useFlights';
import { Flight } from '../types/flight';

interface FlightContextType {
  flights: Flight[];
  selectedFlight: Flight | null;
  setSelectedFlight: (flight: Flight | null) => void;
  isLoading: boolean;
  error: Error | null;
  lastUpdated: string | null;
}

const FlightContext = createContext<FlightContextType | null>(null);

export function FlightProvider({ children }: { children: ReactNode }) {
  const { flights, isLoading, error, lastUpdated } = useFlights();
  const [selectedFlight, setSelectedFlight] = useState<Flight | null>(null);

  return (
    <FlightContext.Provider value={{
      flights,
      selectedFlight,
      setSelectedFlight,
      isLoading,
      error,
      lastUpdated
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
