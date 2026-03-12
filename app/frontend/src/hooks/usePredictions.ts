import { useQuery } from '@tanstack/react-query';
import {
  DelayPrediction,
  DelaysResponse,
  GateRecommendation,
  CongestionArea,
  CongestionSummaryResponse,
  Flight,
} from '../types/flight';

// Fetch delay predictions for all flights or a single flight
async function fetchDelays(icao24?: string): Promise<DelaysResponse> {
  const url = icao24
    ? `/api/predictions/delays?icao24=${icao24}`
    : '/api/predictions/delays';
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch delays: ${response.statusText}`);
  }
  return response.json();
}

// Fetch gate recommendations for a specific flight
async function fetchGateRecommendations(
  icao24: string,
  topK: number = 3
): Promise<GateRecommendation[]> {
  const response = await fetch(`/api/predictions/gates/${icao24}?top_k=${topK}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch gate recommendations: ${response.statusText}`);
  }
  return response.json();
}

// Fetch congestion summary (areas + bottlenecks in one call)
async function fetchCongestionSummary(): Promise<CongestionSummaryResponse> {
  const response = await fetch('/api/predictions/congestion-summary');
  if (!response.ok) {
    throw new Error(`Failed to fetch congestion summary: ${response.statusText}`);
  }
  return response.json();
}

export interface UsePredictionsResult {
  delays: Map<string, DelayPrediction>;
  isLoading: boolean;
  error: Error | null;
}

/**
 * Hook for fetching delay predictions for all flights.
 *
 * @param flights Array of flights to get predictions for
 * @returns Delay predictions keyed by icao24
 */
export function usePredictions(flights: Flight[]): UsePredictionsResult {
  const { data, isLoading, error } = useQuery<DelaysResponse, Error>({
    queryKey: ['predictions', 'delays', flights.map((f) => f.icao24).join(',')],
    queryFn: () => fetchDelays(),
    enabled: flights.length > 0,
    refetchInterval: 30000,
    staleTime: 25000,
    retry: 2,
  });

  const delays = new Map<string, DelayPrediction>();
  if (data?.delays) {
    for (const delay of data.delays) {
      delays.set(delay.icao24, delay);
    }
  }

  return {
    delays,
    isLoading,
    error: error ?? null,
  };
}

export interface UseDelayPredictionResult {
  delay: DelayPrediction | null;
  isLoading: boolean;
  error: Error | null;
}

/**
 * Hook for fetching delay prediction for a single flight.
 *
 * @param icao24 ICAO24 identifier of the flight
 * @returns Delay prediction for the flight
 */
export function useDelayPrediction(icao24: string | null): UseDelayPredictionResult {
  const { data, isLoading, error } = useQuery<DelaysResponse, Error>({
    queryKey: ['predictions', 'delay', icao24],
    queryFn: () => fetchDelays(icao24!),
    enabled: !!icao24,
    refetchInterval: 30000,
    staleTime: 25000,
    retry: 2,
  });

  return {
    delay: data?.delays?.[0] ?? null,
    isLoading,
    error: error ?? null,
  };
}

export interface UseGateRecommendationsResult {
  recommendations: GateRecommendation[];
  isLoading: boolean;
  error: Error | null;
}

/**
 * Hook for fetching gate recommendations for a flight.
 *
 * @param icao24 ICAO24 identifier of the flight
 * @param topK Number of recommendations to fetch (default 3)
 * @returns Gate recommendations sorted by score
 */
export function useGateRecommendations(
  icao24: string | null,
  topK: number = 3
): UseGateRecommendationsResult {
  const { data, isLoading, error } = useQuery<GateRecommendation[], Error>({
    queryKey: ['predictions', 'gates', icao24, topK],
    queryFn: () => fetchGateRecommendations(icao24!, topK),
    enabled: !!icao24,
    staleTime: 30000, // Gate recommendations less volatile
    retry: 2,
  });

  return {
    recommendations: data ?? [],
    isLoading,
    error: error ?? null,
  };
}

export interface UseCongestionResult {
  congestion: CongestionArea[];
  bottlenecks: CongestionArea[];
  isLoading: boolean;
  error: Error | null;
}

/**
 * Hook for fetching airport congestion data.
 * Refreshes every 10 seconds.
 *
 * @returns Congestion data for all areas and bottlenecks
 */
export function useCongestion(): UseCongestionResult {
  const { data, isLoading, error } = useQuery<CongestionSummaryResponse, Error>({
    queryKey: ['predictions', 'congestion-summary'],
    queryFn: fetchCongestionSummary,
    refetchInterval: 30000,
    staleTime: 25000,
    retry: 2,
  });

  return {
    congestion: data?.areas ?? [],
    bottlenecks: data?.bottlenecks ?? [],
    isLoading,
    error: error ?? null,
  };
}
