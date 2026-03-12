import { useEffect, useMemo, useCallback, useRef } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { AIRPORT_CENTER, DEFAULT_ZOOM } from '../../constants/airportLayout';
import AirportOverlay from './AirportOverlay';
import FlightMarker from './FlightMarker';
import TrajectoryLine from './TrajectoryLine';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { SharedViewport } from '../../hooks/useViewportState';

interface AirportMapProps {
  /** Shared viewport from 3D view (if any) */
  sharedViewport?: SharedViewport | null;
  /** Callback to save viewport on unmount */
  onViewportChange?: (vp: SharedViewport) => void;
}

/**
 * Recenters the map when the airport config changes (e.g., gate positions move),
 * OR restores a shared viewport from the 3D view.
 */
function MapRecenter({ sharedViewport }: { sharedViewport?: SharedViewport | null }) {
  const map = useMap();
  const { getGates, getTerminals, currentAirport } = useAirportConfigContext();

  const center = useMemo((): [number, number] | null => {
    // Compute center from terminals or gates
    const terminals = getTerminals();
    const gates = getGates();
    const items = terminals.length > 0 ? terminals : gates;

    if (items.length === 0) return null;

    let sumLat = 0, sumLon = 0, count = 0;
    for (const item of items) {
      const geo = (item as { geo?: { latitude?: number | string; longitude?: number | string } }).geo;
      const lat = Number(geo?.latitude);
      const lon = Number(geo?.longitude);
      if (lat && lon && !isNaN(lat) && !isNaN(lon)) {
        sumLat += lat;
        sumLon += lon;
        count++;
      }
    }
    if (count === 0) return null;
    return [sumLat / count, sumLon / count];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getGates, getTerminals, currentAirport]);

  const prevAirportRef = useRef(currentAirport);

  useEffect(() => {
    const airportChanged = prevAirportRef.current !== currentAirport;
    prevAirportRef.current = currentAirport;

    // On airport switch, always recenter to the new airport
    if (airportChanged && center) {
      map.flyTo(center, DEFAULT_ZOOM, { duration: 1.5 });
      return;
    }
    // If we have a shared viewport from 3D (same airport), restore it
    if (sharedViewport) {
      map.setView(
        [sharedViewport.center.lat, sharedViewport.center.lon],
        sharedViewport.zoom,
        { animate: false }
      );
      return;
    }
    // Otherwise, recenter based on airport data
    if (center) {
      map.flyTo(center, DEFAULT_ZOOM, { duration: 1.5 });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center, map, currentAirport]);

  return null;
}

/**
 * Saves the current Leaflet viewport to shared state on unmount.
 */
function MapViewportSaver({ onViewportChange }: { onViewportChange?: (vp: SharedViewport) => void }) {
  const map = useMap();

  const saveViewport = useCallback(() => {
    if (!onViewportChange) return;
    try {
      const center = map.getCenter();
      const zoom = map.getZoom();
      onViewportChange({
        center: { lat: center.lat, lon: center.lng },
        zoom,
        bearing: 0, // 2D map has no rotation
      });
    } catch {
      // Map may be partially destroyed during unmount (e.g. in test environments)
    }
  }, [map, onViewportChange]);

  useEffect(() => {
    // Save on unmount
    return () => {
      saveViewport();
    };
  }, [saveViewport]);

  return null;
}

export default function AirportMap({ sharedViewport, onViewportChange }: AirportMapProps) {
  const { flights, isLoading, error, lastUpdated } = useFlightContext();

  // Use shared viewport center/zoom if available, otherwise defaults
  const initialCenter: [number, number] = sharedViewport
    ? [sharedViewport.center.lat, sharedViewport.center.lon]
    : AIRPORT_CENTER;
  const initialZoom = sharedViewport?.zoom ?? DEFAULT_ZOOM;

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={initialCenter}
        zoom={initialZoom}
        className="h-full w-full"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapRecenter sharedViewport={sharedViewport} />
        <MapViewportSaver onViewportChange={onViewportChange} />
        <AirportOverlay />
        <TrajectoryLine />
        {flights
          .filter((f) => f.latitude != null && f.longitude != null && !isNaN(f.latitude) && !isNaN(f.longitude))
          .map((flight) => (
            <FlightMarker key={flight.icao24} flight={flight} />
          ))}
      </MapContainer>

      {/* Status overlay */}
      <div className="absolute bottom-4 left-4 bg-white/90 backdrop-blur-sm rounded-lg shadow-lg p-3 z-[1000]">
        <div className="text-sm">
          <div className="flex items-center gap-2">
            <span className="font-medium">Flights:</span>
            <span className="font-mono">{flights.length}</span>
            {isLoading && (
              <span className="text-blue-500 animate-pulse">Updating...</span>
            )}
          </div>
          {lastUpdated && (
            <div className="text-gray-500 text-xs mt-1">
              Last updated: {new Date(lastUpdated).toLocaleTimeString()}
            </div>
          )}
          {error && (
            <div className="text-red-500 text-xs mt-1">
              Error: {error.message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
