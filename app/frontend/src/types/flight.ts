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
  aircraft_type?: string; // ICAO aircraft type code (e.g., A320, B738)
}

export interface FlightsResponse {
  flights: Flight[];
  count: number;
  timestamp: string;
  data_source: 'live' | 'cached' | 'synthetic';
}

// Prediction types
export interface DelayPrediction {
  icao24: string;
  delay_minutes: number;
  confidence: number;
  category: "on_time" | "slight" | "moderate" | "severe";
}

export interface GateRecommendation {
  gate_id: string;
  score: number;
  reasons: string[];
  taxi_time: number;
}

export interface CongestionArea {
  area_id: string;
  area_type: "runway" | "taxiway" | "apron" | "terminal";
  level: "low" | "moderate" | "high" | "critical";
  flight_count: number;
  wait_minutes: number;
}

export interface DelaysResponse {
  delays: DelayPrediction[];
  count: number;
}

export interface CongestionResponse {
  areas: CongestionArea[];
  count: number;
}

export interface FlightWithPredictions extends Flight {
  delayPrediction?: DelayPrediction;
  gateRecommendations?: GateRecommendation[];
}
