import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import Map, { Source, Layer, useMap } from 'react-map-gl/maplibre';
import type maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { DEFAULT_ZOOM } from '../../constants/airportLayout';
import AirportOverlay from './AirportOverlay';
import FlightMarker from './FlightMarker';
import TrajectoryLine from './TrajectoryLine';
import { useFlightContext } from '../../context/FlightContext';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { SharedViewport } from '../../hooks/useViewportState';
import InpaintingOverlay, { TileEvent } from './InpaintingOverlay';

interface AirportMapProps {
  sharedViewport?: SharedViewport | null;
  onViewportChange?: (vp: SharedViewport) => void;
  satellite?: boolean;
  inpainting?: boolean;
  airportIcao?: string;
  onStaleDetected?: () => void;
  onWarmingUp?: () => void;
  onTileActivity?: (event: TileEvent) => void;
}

function MapRecenter({ sharedViewport }: { sharedViewport?: SharedViewport | null }) {
  const { current: map } = useMap();
  const { getGates, getTerminals, getAirportCenter, currentAirport } = useAirportConfigContext();

  const bounds = useMemo((): [[number, number], [number, number]] | null => {
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
    const latPad = (maxLat - minLat) * 0.2 || 0.005;
    const lonPad = (maxLon - minLon) * 0.2 || 0.005;
    return [
      [minLon - lonPad, minLat - latPad],
      [maxLon + lonPad, maxLat + latPad],
    ];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getGates, getTerminals, currentAirport]);

  const prevAirportRef = useRef(currentAirport);
  const lastFlewToBoundsRef = useRef<string | null>(null);

  useEffect(() => {
    if (!map) return;
    const airportChanged = prevAirportRef.current !== currentAirport;
    prevAirportRef.current = currentAirport;

    if (airportChanged) {
      lastFlewToBoundsRef.current = null;
    }

    const boundsKey = bounds ? JSON.stringify(bounds) : null;
    const alreadyAtTheseBounds = boundsKey !== null && boundsKey === lastFlewToBoundsRef.current;

    if (!alreadyAtTheseBounds && bounds) {
      map.fitBounds(bounds, { duration: 1500, maxZoom: 16 });
      lastFlewToBoundsRef.current = boundsKey;
      return;
    }

    if (airportChanged && !bounds) {
      const center = getAirportCenter();
      map.flyTo({ center: [center.lon, center.lat], zoom: 14, duration: 1500 });
      return;
    }

    if (!airportChanged && sharedViewport && alreadyAtTheseBounds) {
      map.jumpTo({
        center: [sharedViewport.center.lon, sharedViewport.center.lat],
        zoom: sharedViewport.zoom,
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds, map, currentAirport]);

  return null;
}

function MapViewportSaver({ onViewportChange }: { onViewportChange?: (vp: SharedViewport) => void }) {
  const { current: map } = useMap();

  useEffect(() => {
    if (!onViewportChange || !map) return;

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
    save();

    return () => {
      map.off('moveend', save);
      save();
    };
  }, [map, onViewportChange]);

  return null;
}

function ZoomTracker({ onZoom }: { onZoom: (z: number) => void }) {
  const { current: map } = useMap();

  useEffect(() => {
    if (!map) return;
    const handler = () => onZoom(map.getZoom());
    map.on('zoomend', handler);
    map.on('zoom', handler);
    return () => {
      map.off('zoomend', handler);
      map.off('zoom', handler);
    };
  }, [map, onZoom]);

  return null;
}

declare global {
  interface Window {
    __mapControl?: {
      setView: (lat: number, lon: number, zoom: number) => void;
      getView: () => { lat: number; lon: number; zoom: number };
    };
  }
}

function MapControlExposer() {
  const { current: map } = useMap();
  useEffect(() => {
    if (!map) return;
    window.__mapControl = {
      setView: (lat: number, lon: number, zoom: number) => {
        map.jumpTo({ center: [lon, lat], zoom });
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

const STREET_TILES = [
  'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
  'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
  'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png',
];
const STREET_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const SAT_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const SAT_ATTR = '&copy; Esri &mdash; Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, GIS User Community';

const STREET_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    'street-tiles': {
      type: 'raster',
      tiles: STREET_TILES,
      tileSize: 256,
      attribution: STREET_ATTR,
    },
  },
  layers: [
    { id: 'street-raster', type: 'raster', source: 'street-tiles' },
  ],
};

const SATELLITE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    'satellite-tiles': {
      type: 'raster',
      tiles: [SAT_URL],
      tileSize: 256,
      attribution: SAT_ATTR,
      maxzoom: 17,
    },
  },
  layers: [
    { id: 'satellite-raster', type: 'raster', source: 'satellite-tiles' },
  ],
};

function InpaintingTileLayer({ airportIcao, onStaleDetected, onWarmingUp, onTileEvent }: { airportIcao?: string; onStaleDetected?: () => void; onWarmingUp?: () => void; onTileEvent?: (event: TileEvent) => void }) {
  const { current: map } = useMap();
  const staleRef = useRef(onStaleDetected);
  staleRef.current = onStaleDetected;
  const warmRef = useRef(onWarmingUp);
  warmRef.current = onWarmingUp;
  const tileEventRef = useRef(onTileEvent);
  tileEventRef.current = onTileEvent;
  const protocolRegistered = useRef(false);

  useEffect(() => {
    if (!map) return;
    const maplibregl = map.getMap();
    const protocolId = 'inpaint';

    if (!protocolRegistered.current) {
      try {
        // @ts-expect-error maplibre addProtocol
        maplibregl.style?.map?.addProtocol?.(protocolId, (params: { url: string }, abortController: AbortController) => {
          return handleInpaintingTile(params.url, abortController, airportIcao, staleRef, warmRef, tileEventRef);
        });
      } catch {
        // Protocol may already be added or not supported — fall back to regular source
      }
      protocolRegistered.current = true;
    }

    return () => {
      protocolRegistered.current = false;
    };
  }, [map, airportIcao]);

  // Fallback: use a regular raster source that points to our inpainting proxy
  return (
    <Source
      id="inpainting-tiles"
      type="raster"
      tiles={[`/api/inpainting/clean-tile?url=${encodeURIComponent(SAT_URL)}&airport_icao=${airportIcao || ''}&z={z}&x={x}&y={y}`]}
      tileSize={256}
      attribution={SAT_ATTR}
      maxzoom={17}
    >
      <Layer id="inpainting-raster" type="raster" />
    </Source>
  );
}

async function handleInpaintingTile(
  _url: string,
  abortController: AbortController,
  airportIcao?: string,
  staleRef?: React.MutableRefObject<(() => void) | undefined>,
  warmRef?: React.MutableRefObject<(() => void) | undefined>,
  _tileEventRef?: React.MutableRefObject<((event: TileEvent) => void) | undefined>,
) {
  const esriUrl = SAT_URL.replace('{z}', '0').replace('{y}', '0').replace('{x}', '0');
  const params = new URLSearchParams({ url: esriUrl });
  if (airportIcao) params.set('airport_icao', airportIcao);

  const cacheParams = new URLSearchParams(params);
  cacheParams.set('cache_only', 'true');

  try {
    const resp = await fetch(`/api/inpainting/clean-tile?${cacheParams.toString()}`, {
      method: 'POST',
      signal: abortController.signal,
    });

    if (resp.status === 204) {
      const fullResp = await fetch(`/api/inpainting/clean-tile?${params.toString()}`, {
        method: 'POST',
        signal: abortController.signal,
      });
      if (fullResp.status === 503) {
        warmRef?.current?.();
        throw new Error('warming_up');
      }
      if (!fullResp.ok) throw new Error(`HTTP ${fullResp.status}`);
      const blob = await fullResp.blob();
      return { data: await blob.arrayBuffer() };
    }

    if (resp.ok) {
      const isStale = resp.headers.get('X-Cache') === 'STALE';
      if (isStale) staleRef?.current?.();
      const blob = await resp.blob();
      return { data: await blob.arrayBuffer() };
    }

    throw new Error(`HTTP ${resp.status}`);
  } catch {
    // Return empty on failure — map shows blank tile
    return { data: new ArrayBuffer(0) };
  }
}

const FOLLOW_MAX_DISTANCE_DEG = 0.5;

function FlightFollower() {
  const { current: map } = useMap();
  const { selectedFlight } = useFlightContext();
  const { getAirportCenter } = useAirportConfigContext();
  const userPannedRef = useRef(false);
  const prevSelectedIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!map) return;
    const handler = () => { userPannedRef.current = true; };
    map.on('dragend', handler);
    return () => { map.off('dragend', handler); };
  }, [map]);

  useEffect(() => {
    if (!map) return;
    const id = selectedFlight?.icao24 ?? null;
    if (id !== prevSelectedIdRef.current) {
      userPannedRef.current = false;
      prevSelectedIdRef.current = id;

      if (selectedFlight && selectedFlight.latitude != null && selectedFlight.longitude != null) {
        const zoom = Math.max(map.getZoom(), 13);
        map.flyTo({ center: [selectedFlight.longitude, selectedFlight.latitude], zoom, duration: 1000 });
      }
    }
  }, [selectedFlight?.icao24, selectedFlight, map]);

  useEffect(() => {
    if (!map || !selectedFlight || userPannedRef.current) return;
    const { latitude, longitude } = selectedFlight;
    if (latitude == null || longitude == null || isNaN(latitude) || isNaN(longitude)) return;

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
      map.panTo([longitude, latitude], { duration: 300 });
    }
  }, [map, selectedFlight, getAirportCenter]);

  return null;
}

export default function AirportMap({ sharedViewport, onViewportChange, satellite = false, inpainting = false, airportIcao, onStaleDetected, onWarmingUp, onTileActivity }: AirportMapProps) {
  const { filteredFlights: flights, isLoading, error, lastUpdated } = useFlightContext();
  const { getAirportCenter } = useAirportConfigContext();
  const [zoom, setZoom] = useState(sharedViewport?.zoom ?? DEFAULT_ZOOM);
  const [tileEvents, setTileEvents] = useState<TileEvent[]>([]);

  const handleTileEvent = useCallback((event: TileEvent) => {
    setTileEvents((prev) => {
      const updated = prev.filter((e) => e.id !== event.id);
      updated.push(event);
      return updated;
    });
    onTileActivity?.(event);
  }, [onTileActivity]);

  const dynamicCenter = getAirportCenter();
  const initialCenter: [number, number] = sharedViewport
    ? [sharedViewport.center.lon, sharedViewport.center.lat]
    : [dynamicCenter.lon, dynamicCenter.lat];
  const initialZoom = sharedViewport?.zoom ?? DEFAULT_ZOOM;

  const tileSource = useMemo(() => {
    if (satellite && inpainting && zoom >= 17) return 'inpainting';
    return satellite ? 'satellite' : 'street';
  }, [satellite, inpainting, zoom]);

  const mapStyle = useMemo(() => {
    if (tileSource === 'street') return STREET_STYLE;
    return SATELLITE_STYLE;
  }, [tileSource]);

  return (
    <div className="relative h-full w-full">
      <Map
        initialViewState={{
          longitude: initialCenter[0],
          latitude: initialCenter[1],
          zoom: initialZoom,
        }}
        style={{ width: '100%', height: '100%' }}
        mapStyle={mapStyle}
        attributionControl={true as unknown as false}
      >
        {tileSource === 'inpainting' && (
          <>
            <InpaintingTileLayer airportIcao={airportIcao} onStaleDetected={onStaleDetected} onWarmingUp={onWarmingUp} onTileEvent={handleTileEvent} />
            <InpaintingOverlay events={tileEvents} />
          </>
        )}
        <MapRecenter sharedViewport={sharedViewport} />
        <MapViewportSaver onViewportChange={onViewportChange} />
        <MapControlExposer />
        <FlightFollower />
        <ZoomTracker onZoom={setZoom} />
        <AirportOverlay />
        <TrajectoryLine />
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
      </Map>

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
