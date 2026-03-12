import { useMemo, useRef, useEffect } from 'react';
import { Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import { Flight } from '../../types/flight';
import { useFlightContext } from '../../context/FlightContext';

interface FlightMarkerProps {
  flight: Flight;
  zoom?: number;
}

// Get color based on flight phase
function getPhaseColor(phase: Flight['flight_phase']): string {
  switch (phase) {
    case 'ground':
      return '#6b7280'; // gray-500
    case 'climbing':
      return '#22c55e'; // green-500
    case 'descending':
      return '#f97316'; // orange-500
    case 'cruising':
      return '#3b82f6'; // blue-500
    default:
      return '#9ca3af'; // gray-400
  }
}

// Selection color (green)
const SELECTION_COLOR = '#22c55e';

// Airplane pixel size by zoom level — scales with the map so it looks natural
// At zoom 18, ~1px ≈ 0.6m, so 40px ≈ 24m (small regional jet)
// At zoom 14, ~1px ≈ 10m, so 14px is still visible but not oversized
function getIconSize(zoom: number): number {
  if (zoom >= 18) return 40;
  if (zoom >= 17) return 34;
  if (zoom >= 16) return 28;
  if (zoom >= 15) return 22;
  if (zoom >= 14) return 16;
  if (zoom >= 13) return 12;
  return 10;
}

// Create airplane SVG icon with rotation, ARIA label, and optional gate label
function createAirplaneIcon(heading: number | null, phase: Flight['flight_phase'], isSelected: boolean, size: number, callsign?: string | null, icao24?: string, gateName?: string | null): L.DivIcon {
  const rotation = heading ?? 0;
  const color = isSelected ? SELECTION_COLOR : getPhaseColor(phase);
  const label = callsign || icao24 || 'Unknown';

  const gateLabel = gateName && phase === 'ground'
    ? `<div class="gate-label">${gateName}</div>`
    : '';

  const half = size / 2;

  // Airplane top-down silhouette: nose at top (0° heading = north).
  const svgIcon = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="${color}" width="${size}" height="${size}" style="transform: rotate(${rotation}deg); transform-origin: center; filter: drop-shadow(1px 1px 1px rgba(0,0,0,0.4));" role="img" aria-label="Flight ${label}">
      <path d="M128 8 L120 80 L28 130 L28 145 L120 120 L116 200 L88 224 L88 240 L128 224 L168 240 L168 224 L140 200 L136 120 L228 145 L228 130 L136 80 Z"/>
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
  const size = getIconSize(zoom);

  const icon = useMemo(
    () => createAirplaneIcon(flight.heading, flight.flight_phase, isSelected, size, flight.callsign, flight.icao24, flight.assigned_gate),
    [flight.heading, flight.flight_phase, isSelected, size, flight.callsign, flight.icao24, flight.assigned_gate]
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
