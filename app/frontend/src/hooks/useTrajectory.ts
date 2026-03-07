import { useQuery } from '@tanstack/react-query';

interface TrajectoryPoint {
  icao24: string;
  callsign: string | null;
  latitude: number | null;
  longitude: number | null;
  altitude: number | null;
  velocity: number | null;
  heading: number | null;
  vertical_rate: number | null;
  on_ground: boolean;
  flight_phase: string | null;
  timestamp: number;
}

interface TrajectoryResponse {
  icao24: string;
  callsign: string | null;
  points: TrajectoryPoint[];
  count: number;
  start_time: number | null;
  end_time: number | null;
}

async function fetchTrajectory(icao24: string, minutes: number = 60): Promise<TrajectoryResponse> {
  const response = await fetch(`/api/flights/${icao24}/trajectory?minutes=${minutes}&limit=1000`, {
    credentials: 'include',
  });

  if (!response.ok) {
    if (response.status === 404) {
      return {
        icao24,
        callsign: null,
        points: [],
        count: 0,
        start_time: null,
        end_time: null,
      };
    }
    throw new Error(`Failed to fetch trajectory: ${response.statusText}`);
  }

  return response.json();
}

export function useTrajectory(icao24: string | null, enabled: boolean = true, minutes: number = 60) {
  return useQuery({
    queryKey: ['trajectory', icao24, minutes],
    queryFn: () => fetchTrajectory(icao24!, minutes),
    enabled: enabled && !!icao24,
    staleTime: 30000, // 30 seconds
    refetchInterval: enabled ? 30000 : false, // Refetch every 30s when enabled
  });
}

export type { TrajectoryPoint, TrajectoryResponse };
