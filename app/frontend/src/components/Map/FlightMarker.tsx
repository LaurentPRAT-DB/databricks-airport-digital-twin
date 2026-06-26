import { useMemo, useRef } from 'react';
import { Marker } from 'react-map-gl/maplibre';
import { Flight } from '../../types/flight';
import { useFlightContext } from '../../context/FlightContext';
import { isGroundPhase } from '../../utils/phaseUtils';

interface FlightMarkerProps {
  flight: Flight;
  zoom?: number;
}

const SELECTION_COLOR = '#22c55e';

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

const SILHOUETTE_PATHS: Record<AircraftCategory, string> = {
  default: `M50 2 C52 2 54 8 54 18 L55 38 L92 56 L92 62 L55 52 L55.5 76 L70 86 L70 90 L55.5 84 L55 92 C55 96 54 98 50 98 C46 98 45 96 45 92 L44.5 84 L30 90 L30 86 L44.5 76 L45 52 L8 62 L8 56 L45 38 L46 18 C46 8 48 2 50 2 Z`,
  narrow: `M50 2 C52 2 53.5 8 53.5 18 L54.5 38 L90 54 L90 59 L54.5 50 L55 76 L68 85 L68 89 L55 83 L54.5 93 C54 96 53 98 50 98 C47 98 46 96 45.5 93 L45 83 L32 89 L32 85 L45 76 L45.5 50 L10 59 L10 54 L45.5 38 L46.5 18 C46.5 8 48 2 50 2 Z`,
  wideTwin: `M50 2 C53 2 55 8 55 18 L56 36 L95 52 L95 58 L56 49 L56.5 75 L72 84 L72 88 L56.5 82 L56 93 C55.5 96 54 98 50 98 C46 98 44.5 96 44 93 L43.5 82 L28 88 L28 84 L43.5 75 L44 49 L5 58 L5 52 L44 36 L45 18 C45 8 47 2 50 2 Z M60 44 C62 44 63 42 63 40 C63 38 62 36 60 36 C58 36 57 38 57 40 C57 42 58 44 60 44 Z M40 44 C42 44 43 42 43 40 C43 38 42 36 40 36 C38 36 37 38 37 40 C37 42 38 44 40 44 Z`,
  wideQuad: `M50 2 C53.5 2 56 8 56 18 L57 34 L97 50 L97 56 L57 47 L57.5 74 L74 83 L74 87 L57.5 81 L57 93 C56.5 96 55 98 50 98 C45 98 43.5 96 43 93 L42.5 81 L26 87 L26 83 L42.5 74 L43 47 L3 56 L3 50 L43 34 L44 18 C44 8 46.5 2 50 2 Z M63 42 C65 42 66 40 66 38 C66 36 65 34 63 34 C61 34 60 36 60 38 C60 40 61 42 63 42 Z M76 48 C78 48 79 46 79 44 C79 42 78 40 76 40 C74 40 73 42 73 44 C73 46 74 48 76 48 Z M37 42 C39 42 40 40 40 38 C40 36 39 34 37 34 C35 34 34 36 34 38 C34 40 35 42 37 42 Z M24 48 C26 48 27 46 27 44 C27 42 26 40 24 40 C22 40 21 42 21 44 C21 46 22 48 24 48 Z`,
};

const AIRCRAFT_WINGSPAN_M: Record<string, number> = {
  A318: 34.1, A319: 35.8, A320: 35.8, A321: 35.8,
  B737: 35.8, B738: 35.8, B739: 35.8,
  A330: 60.9, A350: 64.8, B777: 65.0, B787: 60.1,
  A380: 79.7, A340: 63.5, A345: 63.5, A310: 44.0,
};
const DEFAULT_WINGSPAN_M = 36;

function getIconSize(zoom: number, aircraftType?: string, latitude?: number): number {
  const lat = latitude ?? 40;
  const metersPerPixel = (156543 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, zoom);
  const wingspan = AIRCRAFT_WINGSPAN_M[(aircraftType ?? '').toUpperCase()] ?? DEFAULT_WINGSPAN_M;
  const rawPixels = wingspan / metersPerPixel;
  return Math.round(Math.max(6, Math.min(rawPixels, 96)));
}

export function createAirplaneIconHtml(heading: number | null, phase: Flight['flight_phase'], isSelected: boolean, size: number, callsign?: string | null, icao24?: string, gateName?: string | null, aircraftType?: string): string {
  const rotation = heading ?? 0;
  const label = callsign || icao24 || 'Unknown';
  const category = getAircraftCategory(aircraftType);
  const path = SILHOUETTE_PATHS[category];

  const gateLabel = gateName && isGroundPhase(phase)
    ? `<div class="gate-label">${gateName}</div>`
    : '';

  const displaySize = isSelected ? Math.round(size * 1.6) : size;

  const fill = isSelected ? SELECTION_COLOR : '#f0f0f0';
  const stroke = isSelected ? '#166534' : '#4a4a4a';
  const strokeWidth = isSelected ? 3 : 1.5;
  const shadow = isSelected
    ? 'drop-shadow(0 0 6px rgba(34,197,94,0.9))'
    : 'drop-shadow(1px 1px 2px rgba(0,0,0,0.6))';

  const pulseRing = isSelected
    ? `<div class="selected-pulse-ring" style="width:${displaySize + 20}px;height:${displaySize + 20}px;top:${-10}px;left:${-10}px;"></div>`
    : '';

  return `
    ${pulseRing}
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${displaySize}" height="${displaySize}" style="transform: rotate(${rotation}deg); transform-origin: center; filter: ${shadow};" role="img" aria-label="Flight ${label}">
      <path d="${path}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>
    </svg>
    ${gateLabel}
  `;
}


/** Compute bearing (degrees, 0=N clockwise) between two lat/lon points. */
export function computeBearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const y = Math.sin(dLon) * Math.cos(lat2 * Math.PI / 180);
  const x = Math.cos(lat1 * Math.PI / 180) * Math.sin(lat2 * Math.PI / 180)
    - Math.sin(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.cos(dLon);
  return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
}

const MIN_MOVE_DEG_SQ = 0.00001 * 0.00001;

export default function FlightMarker({ flight, zoom = 14 }: FlightMarkerProps) {
  const { selectedFlight, setSelectedFlight } = useFlightContext();
  const isSelected = selectedFlight?.icao24 === flight.icao24;
  const size = getIconSize(zoom, flight.aircraft_type, flight.latitude);

  const prevPosRef = useRef<{ lat: number; lon: number; bearing: number | null }>({ lat: flight.latitude, lon: flight.longitude, bearing: null });

  const movementBearing = useMemo(() => {
    const prev = prevPosRef.current;
    const dlat = flight.latitude - prev.lat;
    const dlon = flight.longitude - prev.lon;
    const distSq = dlat * dlat + dlon * dlon;

    if (distSq > MIN_MOVE_DEG_SQ) {
      const bearing = computeBearing(prev.lat, prev.lon, flight.latitude, flight.longitude);
      prev.lat = flight.latitude;
      prev.lon = flight.longitude;
      prev.bearing = bearing;
      return bearing;
    }
    return prev.bearing;
  }, [flight.latitude, flight.longitude]);

  const effectiveHeading = movementBearing ?? flight.heading;

  const iconHtml = useMemo(
    () => createAirplaneIconHtml(effectiveHeading, flight.flight_phase, isSelected, size, flight.callsign, flight.icao24, flight.assigned_gate, flight.aircraft_type),
    [effectiveHeading, flight.flight_phase, isSelected, size, flight.callsign, flight.icao24, flight.assigned_gate, flight.aircraft_type, flight.latitude]
  );

  if (flight.latitude == null || flight.longitude == null || isNaN(flight.latitude) || isNaN(flight.longitude)) {
    return null;
  }

  const displaySize = isSelected ? Math.round(size * 1.6) : size;
  const MIN_TOUCH = 44;
  const hitSize = Math.max(displaySize, MIN_TOUCH);

  return (
    <Marker
      longitude={flight.longitude}
      latitude={flight.latitude}
      anchor="center"
      onClick={() => setSelectedFlight(flight)}
      style={{ zIndex: isSelected ? 1000 : 0 }}
    >
      <div
        className={`flight-marker${isSelected ? ' flight-marker-selected' : ''}`}
        style={{ width: hitSize, height: hitSize, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
        dangerouslySetInnerHTML={{ __html: iconHtml }}
      />
    </Marker>
  );
}
