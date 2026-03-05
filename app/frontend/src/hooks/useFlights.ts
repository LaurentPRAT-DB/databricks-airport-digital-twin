import { useQuery } from '@tanstack/react-query';
import { Flight, FlightsResponse } from '../types/flight';

async function fetchFlights(): Promise<FlightsResponse> {
  const response = await fetch('/api/flights');
  if (!response.ok) {
    throw new Error(`Failed to fetch flights: ${response.statusText}`);
  }
  return response.json();
}

export interface UseFlightsResult {
  flights: Flight[];
  isLoading: boolean;
  error: Error | null;
  lastUpdated: string | null;
}

export function useFlights(): UseFlightsResult {
  const { data, isLoading, error } = useQuery<FlightsResponse, Error>({
    queryKey: ['flights'],
    queryFn: fetchFlights,
    refetchInterval: 5000, // Refresh every 5 seconds
    staleTime: 4000, // Consider data stale after 4 seconds
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
  });

  return {
    flights: data?.flights ?? [],
    isLoading,
    error: error ?? null,
    lastUpdated: data?.timestamp ?? null,
  };
}
