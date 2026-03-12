import { useMemo, useRef, useEffect } from 'react';
import { Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import { Flight } from '../../types/flight';
import { useFlightContext } from '../../context/FlightContext';

interface FlightMarkerProps {
  flight: Flight;
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

// Create airplane SVG icon with rotation, ARIA label, and optional gate label
function createAirplaneIcon(heading: number | null, phase: Flight['flight_phase'], isSelected: boolean, callsign?: string | null, icao24?: string, gateName?: string | null): L.DivIcon {
  const rotation = heading ?? 0;
  const color = isSelected ? SELECTION_COLOR : getPhaseColor(phase);
  const label = callsign || icao24 || 'Unknown';

  const gateLabel = gateName && phase === 'ground'
    ? `<div class="gate-label">${gateName}</div>`
    : '';

  const svgIcon = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="${color}" width="24" height="24" style="transform: rotate(${rotation}deg);" role="img" aria-label="Flight ${label}">
      <path d="M12 2L4 14h3l1 8h8l1-8h3L12 2z"/>
    </svg>
    ${gateLabel}
  `;

  return L.divIcon({
    html: svgIcon,
    className: 'flight-marker',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -12],
  });
}

// Format altitude for display
function formatAltitude(altitude: number | null): string {
  if (altitude === null) return 'N/A';
  return `${Math.round(altitude)} ft`;
}

export default function FlightMarker({ flight }: FlightMarkerProps) {
  const { selectedFlight, setSelectedFlight } = useFlightContext();
  const isSelected = selectedFlight?.icao24 === flight.icao24;
  const markerRef = useRef<L.Marker>(null);

  const icon = useMemo(
    () => createAirplaneIcon(flight.heading, flight.flight_phase, isSelected, flight.callsign, flight.icao24, flight.assigned_gate),
    [flight.heading, flight.flight_phase, isSelected, flight.callsign, flight.icao24, flight.assigned_gate]
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
