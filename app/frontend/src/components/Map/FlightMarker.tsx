import { useMemo } from 'react';
import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { Flight } from '../../types/flight';

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

// Create airplane SVG icon with rotation
function createAirplaneIcon(heading: number | null, phase: Flight['flight_phase']): L.DivIcon {
  const rotation = heading ?? 0;
  const color = getPhaseColor(phase);

  const svgIcon = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="${color}" width="24" height="24" style="transform: rotate(${rotation}deg);">
      <path d="M12 2L4 14h3l1 8h8l1-8h3L12 2z"/>
    </svg>
  `;

  return L.divIcon({
    html: svgIcon,
    className: 'flight-marker',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -12],
  });
}

// Format speed for display
function formatSpeed(velocity: number | null): string {
  if (velocity === null) return 'N/A';
  return `${Math.round(velocity)} m/s`;
}

// Format altitude for display
function formatAltitude(altitude: number | null): string {
  if (altitude === null) return 'N/A';
  return `${Math.round(altitude)} m`;
}

// Format timestamp for display
function formatTime(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleTimeString();
  } catch {
    return timestamp;
  }
}

export default function FlightMarker({ flight }: FlightMarkerProps) {
  const icon = useMemo(
    () => createAirplaneIcon(flight.heading, flight.flight_phase),
    [flight.heading, flight.flight_phase]
  );

  return (
    <Marker
      position={[flight.latitude, flight.longitude]}
      icon={icon}
    >
      <Popup>
        <div className="min-w-[200px]">
          <h3 className="font-bold text-lg mb-2">
            {flight.callsign || flight.icao24}
          </h3>
          <table className="text-sm w-full">
            <tbody>
              <tr>
                <td className="text-gray-600">ICAO24:</td>
                <td className="font-mono">{flight.icao24}</td>
              </tr>
              <tr>
                <td className="text-gray-600">Phase:</td>
                <td>
                  <span
                    className="px-2 py-0.5 rounded text-white text-xs"
                    style={{ backgroundColor: getPhaseColor(flight.flight_phase) }}
                  >
                    {flight.flight_phase}
                  </span>
                </td>
              </tr>
              <tr>
                <td className="text-gray-600">Altitude:</td>
                <td>{formatAltitude(flight.altitude)}</td>
              </tr>
              <tr>
                <td className="text-gray-600">Speed:</td>
                <td>{formatSpeed(flight.velocity)}</td>
              </tr>
              <tr>
                <td className="text-gray-600">Heading:</td>
                <td>{flight.heading !== null ? `${Math.round(flight.heading)}` : 'N/A'}</td>
              </tr>
              <tr>
                <td className="text-gray-600">On Ground:</td>
                <td>{flight.on_ground ? 'Yes' : 'No'}</td>
              </tr>
              <tr>
                <td className="text-gray-600">Source:</td>
                <td>{flight.data_source}</td>
              </tr>
              <tr>
                <td className="text-gray-600">Last Seen:</td>
                <td>{formatTime(flight.last_seen)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Popup>
    </Marker>
  );
}
