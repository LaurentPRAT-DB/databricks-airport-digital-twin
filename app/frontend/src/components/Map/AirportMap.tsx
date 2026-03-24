import { useEffect, useMemo, useCallback, useRef, useState } from 'react';
import { MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
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
  /** Show satellite imagery instead of street map */
  satellite?: boolean;
}

/**
 * Recenters the map when the airport config changes (e.g., gate positions move),
 * OR restores a shared viewport from the 3D view.
 */
function MapRecenter({ sharedViewport }: { sharedViewport?: SharedViewport | null }) {
  const map = useMap();
  const { getGates, getTerminals, currentAirport } = useAirportConfigContext();

  // Compute bounding box from terminals/gates for fitBounds
  const bounds = useMemo((): L.LatLngBoundsExpression | null => {
    const terminals = getTerminals();
    const gates = getGates();
    const items = terminals.length > 0 ? terminals : gates;

    if (items.length === 0) return null;

    let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
    let count = 0;
    for (const item of items) {
      const geo = (item as { geo?: { latitude?: number | string; longitude?: number | string } }).geo;
      const lat = Number(geo?.latitude);
      const lon = Number(geo?.longitude);
      if (lat && lon && !isNaN(lat) && !isNaN(lon)) {
        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
        minLon = Math.min(minLon, lon);
        maxLon = Math.max(maxLon, lon);
        count++;
      }
    }
    if (count === 0) return null;
    // Pad bounds by ~20% for breathing room
    const latPad = (maxLat - minLat) * 0.2 || 0.005;
    const lonPad = (maxLon - minLon) * 0.2 || 0.005;
    return [
      [minLat - latPad, minLon - lonPad],
      [maxLat + latPad, maxLon + lonPad],
    ];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getGates, getTerminals, currentAirport]);

  const prevAirportRef = useRef(currentAirport);

  useEffect(() => {
    const airportChanged = prevAirportRef.current !== currentAirport;
    prevAirportRef.current = currentAirport;

    // On airport switch, fit to terminal bounding box
    if (airportChanged && bounds) {
      map.flyToBounds(bounds, { duration: 1.5, maxZoom: 16 });
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
    // Otherwise, fit to terminal area
    if (bounds) {
      map.flyToBounds(bounds, { duration: 1.5, maxZoom: 16 });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds, map, currentAirport]);

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

/** Tracks map zoom and calls back with the current value. */
function ZoomTracker({ onZoom }: { onZoom: (z: number) => void }) {
  useMapEvents({
    zoomend: (e) => onZoom(e.target.getZoom()),
    zoom: (e) => onZoom(e.target.getZoom()),
  });
  return null;
}

// Expose __mapControl for headless video renderer (Playwright)
declare global {
  interface Window {
    __mapControl?: {
      setView: (lat: number, lon: number, zoom: number) => void;
      getView: () => { lat: number; lon: number; zoom: number };
    };
  }
}

function MapControlExposer() {
  const map = useMap();
  useEffect(() => {
    window.__mapControl = {
      setView: (lat: number, lon: number, zoom: number) => {
        map.setView([lat, lon], zoom, { animate: false });
      },
      getView: () => {
        const c = map.getCenter();
        return { lat: c.lat, lon: c.lng, zoom: map.getZoom() };
      },
    };
    return () => { delete window.__mapControl; };
  }, [map]);
  return null;
}

const STREET_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const STREET_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const SAT_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const SAT_ATTR = '&copy; Esri &mdash; Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, GIS User Community';

export default function AirportMap({ sharedViewport, onViewportChange, satellite = false }: AirportMapProps) {
  const { filteredFlights: flights, isLoading, error, lastUpdated } = useFlightContext();
  const [zoom, setZoom] = useState(sharedViewport?.zoom ?? DEFAULT_ZOOM);

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
          key={satellite ? 'sat' : 'street'}
          attribution={satellite ? SAT_ATTR : STREET_ATTR}
          url={satellite ? SAT_URL : STREET_URL}
        />
        <MapRecenter sharedViewport={sharedViewport} />
        <MapViewportSaver onViewportChange={onViewportChange} />
        <MapControlExposer />
        <ZoomTracker onZoom={setZoom} />
        <AirportOverlay />
        <TrajectoryLine />
        {flights
          .filter((f) => f.latitude != null && f.longitude != null && !isNaN(f.latitude) && !isNaN(f.longitude))
          .map((flight) => (
            <FlightMarker key={flight.icao24} flight={flight} zoom={zoom} />
          ))}
      </MapContainer>

      {/* Status overlay — hidden on mobile */}
      <div className="hidden md:block absolute bottom-4 left-4 bg-white/90 backdrop-blur-sm rounded-lg shadow-lg p-3 z-[1000]">
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
