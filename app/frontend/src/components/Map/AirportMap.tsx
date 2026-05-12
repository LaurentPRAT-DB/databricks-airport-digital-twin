import { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { DEFAULT_ZOOM } from '../../constants/airportLayout';
import AirportOverlay from './AirportOverlay';
import FlightMarker from './FlightMarker';
import TrajectoryLine from './TrajectoryLine';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { SharedViewport } from '../../hooks/useViewportState';

interface AirportMapProps {
  sharedViewport?: SharedViewport | null;
  onViewportChange?: (vp: SharedViewport) => void;
  satellite?: boolean;
  inpainting?: boolean;
  airportIcao?: string;
  onStaleDetected?: () => void;
  onWarmingUp?: () => void;
}

/**
 * Recenters the map when the airport config changes (e.g., gate positions move),
 * OR restores a shared viewport from the 3D view.
 */
function MapRecenter({ sharedViewport }: { sharedViewport?: SharedViewport | null }) {
  const map = useMap();
  const { getGates, getTerminals, getAirportCenter, currentAirport } = useAirportConfigContext();

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
  const lastFlewToBoundsRef = useRef<string | null>(null);

  useEffect(() => {
    const airportChanged = prevAirportRef.current !== currentAirport;
    prevAirportRef.current = currentAirport;

    if (airportChanged) {
      lastFlewToBoundsRef.current = null;
      console.log(`[MapRecenter] Airport changed to ${currentAirport}, bounds=${bounds ? 'yes' : 'no'}`);
    }

    // Serialize bounds for value comparison — fly again when bounds actually change
    const boundsKey = bounds ? JSON.stringify(bounds) : null;
    const alreadyAtTheseBounds = boundsKey !== null && boundsKey === lastFlewToBoundsRef.current;

    if (!alreadyAtTheseBounds && bounds) {
      console.log(`[MapRecenter] flyToBounds for ${currentAirport}`);
      map.flyToBounds(bounds, { duration: 1.5, maxZoom: 16 });
      lastFlewToBoundsRef.current = boundsKey;
      return;
    }

    if (airportChanged && !bounds) {
      const center = getAirportCenter();
      console.log(`[MapRecenter] flyTo center for ${currentAirport}: ${center.lat}, ${center.lon}`);
      map.flyTo([center.lat, center.lon], 14, { duration: 1.5 });
      return;
    }

    // If we have a shared viewport from 3D (same airport), restore it
    if (!airportChanged && sharedViewport && alreadyAtTheseBounds) {
      map.setView(
        [sharedViewport.center.lat, sharedViewport.center.lon],
        sharedViewport.zoom,
        { animate: false }
      );
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds, map, currentAirport]);

  return null;
}

/**
 * Saves the current Leaflet viewport to shared state on every pan/zoom
 * so the 3D view can pick it up when the user switches views.
 * (The 2D map stays mounted but invisible, so unmount-only save doesn't work.)
 */
function MapViewportSaver({ onViewportChange }: { onViewportChange?: (vp: SharedViewport) => void }) {
  const map = useMap();

  useEffect(() => {
    if (!onViewportChange) return;

    const save = () => {
      try {
        const center = map.getCenter();
        const zoom = map.getZoom();
        onViewportChange({
          center: { lat: center.lat, lon: center.lng },
          zoom,
          bearing: 0,
        });
      } catch { /* Map may be partially destroyed */ }
    };

    map.on('moveend', save);
    save(); // Save current state immediately

    return () => {
      map.off('moveend', save);
      save();
    };
  }, [map, onViewportChange]);

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

/**
 * Custom Leaflet GridLayer that fetches satellite tiles through the
 * inpainting proxy (`POST /api/inpainting/clean-tile`) to remove aircraft.
 *
 * Uses two-phase loading for cache efficiency:
 * 1. cache_only=true — fast path, returns cached tile (HIT/STALE) or 204 (MISS)
 * 2. Full inpaint — only on cache miss, calls the serving endpoint
 *
 * Reports stale tiles via onStaleDetected callback so the UI can notify the user.
 */
const InpaintingGridLayer = L.GridLayer.extend({
  createTile(coords: { x: number; y: number; z: number }, done: (err: Error | null, tile: HTMLElement) => void) {
    const tile = document.createElement('img') as HTMLImageElement;
    tile.setAttribute('role', 'presentation');
    tile.style.width = tile.style.height = `${this.getTileSize().x}px`;

    const esriUrl = SAT_URL
      .replace('{z}', String(coords.z))
      .replace('{y}', String(coords.y))
      .replace('{x}', String(coords.x));

    const opts = this.options as { airportIcao?: string; onStaleDetected?: () => void; onWarmingUp?: () => void };
    const params = new URLSearchParams({ url: esriUrl });
    if (opts.airportIcao) params.set('airport_icao', opts.airportIcao);

    let tileResolved = false;
    const loadBlob = (blob: Blob) => {
      const objectUrl = URL.createObjectURL(blob);
      const prev = tile.src;
      tile.src = objectUrl;
      tile.onload = () => {
        URL.revokeObjectURL(objectUrl);
        if (!tileResolved) {
          tileResolved = true;
          done(null, tile);
        }
      };
      tile.onerror = () => {
        URL.revokeObjectURL(objectUrl);
        if (!tileResolved) {
          tileResolved = true;
          done(null, tile);
        }
      };
      if (prev && prev.startsWith('blob:')) URL.revokeObjectURL(prev);
    };

    const fullInpaint = () =>
      fetch(`/api/inpainting/clean-tile?${params.toString()}`, { method: 'POST' })
        .then((r) => {
          if (r.status === 503) {
            opts.onWarmingUp?.();
            throw new Error('warming_up');
          }
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.blob();
        })
        .then(loadBlob);

    // Phase 1: cache-only check (fast path)
    const cacheParams = new URLSearchParams(params);
    cacheParams.set('cache_only', 'true');

    fetch(`/api/inpainting/clean-tile?${cacheParams.toString()}`, { method: 'POST' })
      .then((resp) => {
        if (resp.ok) {
          const isStale = resp.headers.get('X-Cache') === 'STALE';
          if (isStale) opts.onStaleDetected?.();
          resp.blob().then(loadBlob);
          // Background re-inpaint when satellite imagery has been updated
          if (isStale) fullInpaint().catch(() => {});
          return;
        }
        if (resp.status === 204) {
          // No cache — Phase 2: full inpaint (may take minutes on cold start)
          return fullInpaint();
        }
        throw new Error(`HTTP ${resp.status}`);
      })
      .catch(() => {
        tile.onload = () => { if (!tileResolved) { tileResolved = true; done(null, tile); } };
        tile.onerror = () => { if (!tileResolved) { tileResolved = true; done(null, tile); } };
        tile.src = esriUrl;
      });

    return tile;
  },
});

/** React wrapper for the inpainting grid layer. */
function InpaintingTileLayer({ airportIcao, onStaleDetected, onWarmingUp }: { airportIcao?: string; onStaleDetected?: () => void; onWarmingUp?: () => void }) {
  const map = useMap();
  const layerRef = useRef<L.GridLayer | null>(null);
  const staleRef = useRef(onStaleDetected);
  staleRef.current = onStaleDetected;
  const warmRef = useRef(onWarmingUp);
  warmRef.current = onWarmingUp;

  useEffect(() => {
    const layer = new (InpaintingGridLayer as unknown as new (opts: object) => L.GridLayer)({
      attribution: SAT_ATTR,
      maxNativeZoom: 17,
      airportIcao,
      onStaleDetected: () => staleRef.current?.(),
      onWarmingUp: () => warmRef.current?.(),
    });
    layer.addTo(map);
    layerRef.current = layer;
    return () => {
      map.removeLayer(layer);
    };
  }, [map, airportIcao]);

  return null;
}

/**
 * Auto-pans the map to follow the selected flight during replay.
 * Disables follow when the user manually pans; re-enables on new flight selection.
 */
// Max distance (degrees) from airport center before camera-follow stops panning.
// ~0.1° ≈ 11km / 6nm — keeps the airport visible while tracking nearby flights.
const FOLLOW_MAX_DISTANCE_DEG = 0.5;

function FlightFollower() {
  const map = useMap();
  const { selectedFlight } = useFlightContext();
  const { getAirportCenter } = useAirportConfigContext();
  const userPannedRef = useRef(false);
  const prevSelectedIdRef = useRef<string | null>(null);

  // Fly to flight on initial selection, then track with panTo
  useEffect(() => {
    const id = selectedFlight?.icao24 ?? null;
    if (id !== prevSelectedIdRef.current) {
      userPannedRef.current = false;
      prevSelectedIdRef.current = id;

      // Fly to the newly selected flight
      if (selectedFlight && selectedFlight.latitude != null && selectedFlight.longitude != null) {
        const zoom = Math.max(map.getZoom(), 13);
        map.flyTo([selectedFlight.latitude, selectedFlight.longitude], zoom, { duration: 1 });
      }
    }
  }, [selectedFlight?.icao24, selectedFlight, map]);

  // Detect user-initiated pans (dragend) to disable follow
  useMapEvents({
    dragend: () => {
      userPannedRef.current = true;
    },
  });

  // Pan to selected flight position on each update, clamped to airport vicinity
  useEffect(() => {
    if (!selectedFlight || userPannedRef.current) return;
    const { latitude, longitude } = selectedFlight;
    if (latitude == null || longitude == null || isNaN(latitude) || isNaN(longitude)) return;

    // Clamp: don't pan if the flight is too far from the airport center
    const airportCenter = getAirportCenter();
    if (airportCenter) {
      const dLat = Math.abs(latitude - airportCenter.lat);
      const dLng = Math.abs(longitude - airportCenter.lon);
      if (dLat > FOLLOW_MAX_DISTANCE_DEG || dLng > FOLLOW_MAX_DISTANCE_DEG) return;
    }

    const currentCenter = map.getCenter();
    const dx = Math.abs(currentCenter.lat - latitude);
    const dy = Math.abs(currentCenter.lng - longitude);
    if (dx > 0.0001 || dy > 0.0001) {
      map.panTo([latitude, longitude], { animate: true, duration: 0.3 });
    }
  }, [map, selectedFlight, getAirportCenter]);

  return null;
}

export default function AirportMap({ sharedViewport, onViewportChange, satellite = false, inpainting = false, airportIcao, onStaleDetected, onWarmingUp }: AirportMapProps) {
  const { filteredFlights: flights, isLoading, error, lastUpdated } = useFlightContext();
  const { getAirportCenter } = useAirportConfigContext();
  const [zoom, setZoom] = useState(sharedViewport?.zoom ?? DEFAULT_ZOOM);

  // Use shared viewport center/zoom if available, then dynamic airport center, then SFO fallback
  const dynamicCenter = getAirportCenter();
  const initialCenter: [number, number] = sharedViewport
    ? [sharedViewport.center.lat, sharedViewport.center.lon]
    : [dynamicCenter.lat, dynamicCenter.lon];
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
        {satellite && inpainting && (
          <InpaintingTileLayer key="inpaint" airportIcao={airportIcao} onStaleDetected={onStaleDetected} onWarmingUp={onWarmingUp} />
        )}
        <MapRecenter sharedViewport={sharedViewport} />
        <MapViewportSaver onViewportChange={onViewportChange} />
        <MapControlExposer />
        <FlightFollower />
        <ZoomTracker onZoom={setZoom} />
        <AirportOverlay />
        <TrajectoryLine />
        {/* Deduplicate by icao24 to prevent multiple markers with same key */}
        {(() => {
          const seen = new Set<string>();
          return flights
            .filter((f) => {
              if (f.latitude == null || f.longitude == null || isNaN(f.latitude) || isNaN(f.longitude)) return false;
              if (seen.has(f.icao24)) return false;
              seen.add(f.icao24);
              return true;
            })
            .map((flight) => (
              <FlightMarker key={flight.icao24} flight={flight} zoom={zoom} />
            ));
        })()}
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
