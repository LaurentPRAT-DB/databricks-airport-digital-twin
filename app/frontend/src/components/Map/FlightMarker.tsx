import { useMemo, useRef, useEffect } from 'react';
import { Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import { Flight } from '../../types/flight';
import { useFlightContext } from '../../context/FlightContext';
import { PHASE_COLORS, isGroundPhase } from '../../utils/phaseUtils';

interface FlightMarkerProps {
  flight: Flight;
  zoom?: number;
}

// Get color based on flight phase
function getPhaseColor(phase: Flight['flight_phase']): string {
  return PHASE_COLORS[phase] ?? '#9ca3af';
}

// Selection color (green)
const SELECTION_COLOR = '#22c55e';

// Aircraft silhouette categories based on ICAO type codes
type AircraftCategory = 'narrow' | 'wideTwin' | 'wideQuad' | 'default';

function getAircraftCategory(aircraftType?: string): AircraftCategory {
  if (!aircraftType) return 'default';
  const t = aircraftType.toUpperCase();
  switch (t) {
    case 'A318': case 'A319': case 'A320': case 'A321':
    case 'B737': case 'B738': case 'B739':
      return 'narrow';
    case 'A330': case 'A350': case 'B777': case 'B787':
      return 'wideTwin';
    case 'A380': case 'A340': case 'A345': case 'A310':
      return 'wideQuad';
    default:
      return 'default';
  }
}

// Top-down SVG silhouettes per category (viewBox 0 0 100 100, nose at top).
// Visual differences: fuselage width, wing span, engine pod count.
const SILHOUETTE_PATHS: Record<AircraftCategory, string> = {
  // Default: generic mid-size jet (same as original)
  default: `M50 2 C52 2 54 8 54 18 L55 38 L92 56 L92 62 L55 52 L55.5 76 L70 86 L70 90 L55.5 84 L55 92 C55 96 54 98 50 98 C46 98 45 96 45 92 L44.5 84 L30 90 L30 86 L44.5 76 L45 52 L8 62 L8 56 L45 38 L46 18 C46 8 48 2 50 2 Z`,

  // Narrow-body (A320/B737): slender fuselage, moderate swept wings
  narrow: `M50 2 C52 2 53.5 8 53.5 18 L54.5 38 L90 54 L90 59 L54.5 50 L55 76 L68 85 L68 89 L55 83 L54.5 93 C54 96 53 98 50 98 C47 98 46 96 45.5 93 L45 83 L32 89 L32 85 L45 76 L45.5 50 L10 59 L10 54 L45.5 38 L46.5 18 C46.5 8 48 2 50 2 Z`,

  // Wide-body twin (A330/B777): wider fuselage, longer wingspan, 2 engine pods
  wideTwin: `M50 2 C53 2 55 8 55 18 L56 36 L95 52 L95 58 L56 49 L56.5 75 L72 84 L72 88 L56.5 82 L56 93 C55.5 96 54 98 50 98 C46 98 44.5 96 44 93 L43.5 82 L28 88 L28 84 L43.5 75 L44 49 L5 58 L5 52 L44 36 L45 18 C45 8 47 2 50 2 Z M60 44 C62 44 63 42 63 40 C63 38 62 36 60 36 C58 36 57 38 57 40 C57 42 58 44 60 44 Z M40 44 C42 44 43 42 43 40 C43 38 42 36 40 36 C38 36 37 38 37 40 C37 42 38 44 40 44 Z`,

  // Wide-body quad (A380/A340): 4 engine pods, very wide wingspan
  wideQuad: `M50 2 C53.5 2 56 8 56 18 L57 34 L97 50 L97 56 L57 47 L57.5 74 L74 83 L74 87 L57.5 81 L57 93 C56.5 96 55 98 50 98 C45 98 43.5 96 43 93 L42.5 81 L26 87 L26 83 L42.5 74 L43 47 L3 56 L3 50 L43 34 L44 18 C44 8 46.5 2 50 2 Z M63 42 C65 42 66 40 66 38 C66 36 65 34 63 34 C61 34 60 36 60 38 C60 40 61 42 63 42 Z M76 48 C78 48 79 46 79 44 C79 42 78 40 76 40 C74 40 73 42 73 44 C73 46 74 48 76 48 Z M37 42 C39 42 40 40 40 38 C40 36 39 34 37 34 C35 34 34 36 34 38 C34 40 35 42 37 42 Z M24 48 C26 48 27 46 27 44 C27 42 26 40 24 40 C22 40 21 42 21 44 C21 46 22 48 24 48 Z`,
};

// Real wingspans in meters per ICAO type code
const AIRCRAFT_WINGSPAN_M: Record<string, number> = {
  A318: 34.1, A319: 35.8, A320: 35.8, A321: 35.8,
  B737: 35.8, B738: 35.8, B739: 35.8,
  A330: 60.9, A350: 64.8, B777: 65.0, B787: 60.1,
  A380: 79.7, A340: 63.5, A345: 63.5, A310: 44.0,
};
const DEFAULT_WINGSPAN_M = 36; // midsize jet fallback

// Geo-realistic sizing: pixel size derived from real wingspan and Leaflet meters-per-pixel.
// At zoom 18 (~0.46 m/px at lat 40): B737→78px, B777→141→capped 96px.
// At zoom 16 (~1.83 m/px): B737→20px, B777→36px.
// At zoom 14 (~7.33 m/px): B737→5→clamped 6px.
function getIconSize(zoom: number, aircraftType?: string, latitude?: number): number {
  const lat = latitude ?? 40;
  const metersPerPixel = (156543 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, zoom);
  const wingspan = AIRCRAFT_WINGSPAN_M[(aircraftType ?? '').toUpperCase()] ?? DEFAULT_WINGSPAN_M;
  const rawPixels = wingspan / metersPerPixel;
  return Math.round(Math.max(6, rawPixels));
}

// Create airplane SVG icon with rotation, ARIA label, aircraft-type silhouette, and optional gate label
function createAirplaneIcon(heading: number | null, phase: Flight['flight_phase'], isSelected: boolean, size: number, callsign?: string | null, icao24?: string, gateName?: string | null, aircraftType?: string): L.DivIcon {
  const rotation = heading ?? 0;
  const color = isSelected ? SELECTION_COLOR : getPhaseColor(phase);
  const label = callsign || icao24 || 'Unknown';
  const category = getAircraftCategory(aircraftType);
  const path = SILHOUETTE_PATHS[category];

  const gateLabel = gateName && isGroundPhase(phase)
    ? `<div class="gate-label">${gateName}</div>`
    : '';

  const half = size / 2;

  const svgIcon = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="${color}" width="${size}" height="${size}" style="transform: rotate(${rotation}deg); transform-origin: center; filter: drop-shadow(1px 1px 1px rgba(0,0,0,0.4));" role="img" aria-label="Flight ${label}">
      <path d="${path}"/>
    </svg>
    ${gateLabel}
  `;

  return L.divIcon({
    html: svgIcon,
    className: 'flight-marker',
    iconSize: [size, size],
    iconAnchor: [half, half],
    popupAnchor: [0, -half],
  });
}

// Format altitude for display
function formatAltitude(altitude: number | null): string {
  if (altitude === null) return 'N/A';
  return `${Math.round(altitude)} ft`;
}

export default function FlightMarker({ flight, zoom = 14 }: FlightMarkerProps) {
  const { selectedFlight, setSelectedFlight } = useFlightContext();
  const isSelected = selectedFlight?.icao24 === flight.icao24;
  const markerRef = useRef<L.Marker>(null);
  const size = getIconSize(zoom, flight.aircraft_type, flight.latitude);

  const icon = useMemo(
    () => createAirplaneIcon(flight.heading, flight.flight_phase, isSelected, size, flight.callsign, flight.icao24, flight.assigned_gate, flight.aircraft_type),
    [flight.heading, flight.flight_phase, isSelected, size, flight.callsign, flight.icao24, flight.assigned_gate, flight.aircraft_type, flight.latitude]
  );

  // Update marker icon when selection changes without full re-render
  useEffect(() => {
    if (markerRef.current) {
      markerRef.current.setIcon(icon);
    }
  }, [icon]);

  // Guard against invalid coordinates (defense in depth)
  if (flight.latitude == null || flight.longitude == null || isNaN(flight.latitude) || isNaN(flight.longitude)) {
    return null;
  }

  return (
    <Marker
      ref={markerRef}
      position={[flight.latitude, flight.longitude]}
      icon={icon}
      eventHandlers={{
        click: () => setSelectedFlight(flight),
      }}
    >
      <Tooltip direction="top" offset={[0, -12]}>
        <div className="text-sm">
          <div className="font-bold">{flight.callsign || flight.icao24}</div>
          <div className="text-gray-500">
            {flight.flight_phase} • {formatAltitude(flight.altitude)}
            {flight.assigned_gate && ` • Gate ${flight.assigned_gate}`}
          </div>
        </div>
      </Tooltip>
    </Marker>
  );
}
