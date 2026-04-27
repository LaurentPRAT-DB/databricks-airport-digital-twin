import { useQuery } from '@tanstack/react-query';

export interface KPICard {
  label: string;
  value: string;
  color: string;
}

export interface CongestionRow {
  area_id: string;
  area_type: string;
  level: string;
  flight_count: number;
  capacity: number;
  wait_minutes: number;
}

export interface DelayRow {
  icao24: string;
  callsign: string;
  delay_minutes: number;
  confidence: number;
  category: string;
}

export interface PredictionsDashboard {
  kpi_cards: KPICard[];
  congestion_areas: CongestionRow[];
  delay_table: DelayRow[];
  total_flights: number;
}

async function fetchDashboard(): Promise<PredictionsDashboard> {
  const response = await fetch('/api/predictions/dashboard');
  if (!response.ok) throw new Error('Failed to fetch predictions dashboard');
  return response.json();
}

export function usePredictionDashboard(enabled: boolean = true) {
  const { data, isLoading, error } = useQuery<PredictionsDashboard, Error>({
    queryKey: ['predictions', 'dashboard'],
    queryFn: fetchDashboard,
    enabled,
    refetchInterval: 30000,
    staleTime: 25000,
    retry: 2,
  });

  return {
    dashboard: data ?? null,
    isLoading,
    error: error ?? null,
  };
}
