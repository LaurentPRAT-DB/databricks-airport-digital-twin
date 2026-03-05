export interface Flight {
  icao24: string;
  callsign: string | null;
  latitude: number;
  longitude: number;
  altitude: number | null;
  velocity: number | null;
  heading: number | null;
  on_ground: boolean;
  vertical_rate: number | null;
  last_seen: string;
  data_source: string;
  flight_phase: "ground" | "climbing" | "descending" | "cruising";
}

export interface FlightsResponse {
  flights: Flight[];
  count: number;
  timestamp: string;
}
