import React, { useEffect, useRef, useMemo, useState } from 'react';
import { Source, Layer, Marker } from 'react-map-gl/maplibre';

export interface Detection {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  confidence: number;
  class_name?: string;
}

export type TilePhase = 'loading' | 'detected' | 'done' | 'cached';

export interface TileEvent {
  id: string;
  zoom: number;
  tileX: number;
  tileY: number;
  phase: TilePhase;
  detections: Detection[];
  aircraftCount: number;
  cacheStatus: 'HIT' | 'STALE' | 'MISS';
  processingMs?: number;
  timestamp: number;
}

const TILE_SIZE = 256;

function tileToLngLatBounds(x: number, y: number, z: number): [[number, number], [number, number]] {
  const n = Math.pow(2, z);
  const lonLeft = (x / n) * 360 - 180;
  const lonRight = ((x + 1) / n) * 360 - 180;
  const latTop = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI;
  const latBottom = (Math.atan(Math.sinh(Math.PI * (1 - (2 * (y + 1)) / n))) * 180) / Math.PI;
  return [[lonLeft, latBottom], [lonRight, latTop]];
}

function detectionToLngLatBounds(det: Detection, tileBounds: [[number, number], [number, number]]): [[number, number], [number, number]] {
  const [sw, ne] = tileBounds;
  const latSpan = ne[1] - sw[1];
  const lngSpan = ne[0] - sw[0];

  const detSWLng = sw[0] + (det.x1 / TILE_SIZE) * lngSpan;
  const detSWLat = ne[1] - (det.y2 / TILE_SIZE) * latSpan;
  const detNELng = sw[0] + (det.x2 / TILE_SIZE) * lngSpan;
  const detNELat = ne[1] - (det.y1 / TILE_SIZE) * latSpan;

  return [[detSWLng, detSWLat], [detNELng, detNELat]];
}

const PHASE_COLORS: Record<TilePhase, string> = {
  loading: '#3b82f6',
  detected: '#f97316',
  done: '#10b981',
  cached: '#10b981',
};

const PHASE_TTL: Record<TilePhase, number> = {
  loading: 60000,
  detected: 3000,
  done: 5000,
  cached: 4000,
};

interface OverlayState {
  visibleEvents: TileEvent[];
}

export default function InpaintingOverlay({ events }: { events: TileEvent[] }) {
  const timeoutsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const [state] = useVisibleEvents(events, timeoutsRef);

  // Build GeoJSON for tile borders
  const borderGeoJSON = useMemo(() => {
    const features = state.visibleEvents.map((event) => {
      const bounds = tileToLngLatBounds(event.tileX, event.tileY, event.zoom);
      const [[swLng, swLat], [neLng, neLat]] = bounds;
      return {
        type: 'Feature' as const,
        properties: {
          phase: event.phase,
          color: PHASE_COLORS[event.phase],
          id: event.id,
        },
        geometry: {
          type: 'Polygon' as const,
          coordinates: [[
            [swLng, swLat],
            [neLng, swLat],
            [neLng, neLat],
            [swLng, neLat],
            [swLng, swLat],
          ]],
        },
      };
    });
    return { type: 'FeatureCollection' as const, features };
  }, [state.visibleEvents]);

  // Build GeoJSON for detection boxes
  const detectionGeoJSON = useMemo(() => {
    const features: GeoJSON.Feature[] = [];
    for (const event of state.visibleEvents) {
      if (event.detections.length === 0) continue;
      const tileBounds = tileToLngLatBounds(event.tileX, event.tileY, event.zoom);
      for (const det of event.detections) {
        const [[swLng, swLat], [neLng, neLat]] = detectionToLngLatBounds(det, tileBounds);
        features.push({
          type: 'Feature',
          properties: {
            confidence: Math.round(det.confidence * 100),
            color: event.phase === 'detected' ? '#ef4444' : '#f97316',
          },
          geometry: {
            type: 'Polygon',
            coordinates: [[
              [swLng, swLat],
              [neLng, swLat],
              [neLng, neLat],
              [swLng, neLat],
              [swLng, swLat],
            ]],
          },
        });
      }
    }
    return { type: 'FeatureCollection' as const, features };
  }, [state.visibleEvents]);

  // Badge markers for done/cached tiles
  const badges = useMemo(() => {
    return state.visibleEvents
      .filter((e) => e.phase === 'done' || e.phase === 'cached')
      .map((event) => {
        const bounds = tileToLngLatBounds(event.tileX, event.tileY, event.zoom);
        const centerLng = (bounds[0][0] + bounds[1][0]) / 2;
        const centerLat = (bounds[0][1] + bounds[1][1]) / 2;
        const label = event.cacheStatus === 'HIT'
          ? `CACHE HIT ${event.zoom}/${event.tileX}/${event.tileY}`
          : `${event.aircraftCount} aircraft · ${event.processingMs ?? '?'}ms · ${event.zoom}/${event.tileX}/${event.tileY}`;
        return { key: event.id, lng: centerLng, lat: centerLat, label, isHit: event.cacheStatus === 'HIT' };
      });
  }, [state.visibleEvents]);

  return (
    <>
      {/* Tile borders */}
      {borderGeoJSON.features.length > 0 && (
        <Source id="inpainting-borders" type="geojson" data={borderGeoJSON}>
          <Layer
            id="inpainting-borders-line"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 2,
            }}
          />
        </Source>
      )}

      {/* Detection boxes */}
      {detectionGeoJSON.features.length > 0 && (
        <Source id="inpainting-detections" type="geojson" data={detectionGeoJSON}>
          <Layer
            id="inpainting-detections-fill"
            type="fill"
            paint={{
              'fill-color': ['get', 'color'],
              'fill-opacity': 0.15,
            }}
          />
          <Layer
            id="inpainting-detections-line"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 2,
            }}
          />
        </Source>
      )}

      {/* Info badges */}
      {badges.map((b) => (
        <Marker key={b.key} longitude={b.lng} latitude={b.lat} anchor="center">
          <span className={`inpainting-badge-inner ${b.isHit ? 'cache-hit' : 'cache-miss'}`}>
            {b.label}
          </span>
        </Marker>
      ))}
    </>
  );
}

function useVisibleEvents(events: TileEvent[], timeoutsRef: React.MutableRefObject<Map<string, ReturnType<typeof setTimeout>>>): [OverlayState, React.Dispatch<React.SetStateAction<OverlayState>>] {
  const [state, setState] = useState<OverlayState>({ visibleEvents: [] });

  useEffect(() => {
    const timeouts = timeoutsRef.current;

    setState((prev) => {
      const eventMap = new Map(prev.visibleEvents.map((e) => [e.id, e]));

      for (const event of events) {
        // Clear old timeout for this tile
        const oldTimeout = timeouts.get(event.id);
        if (oldTimeout) clearTimeout(oldTimeout);

        eventMap.set(event.id, event);

        // Set removal timeout
        const ttl = PHASE_TTL[event.phase];
        const timeout = setTimeout(() => {
          setState((s) => ({
            visibleEvents: s.visibleEvents.filter((e) => e.id !== event.id),
          }));
          timeouts.delete(event.id);
        }, ttl);
        timeouts.set(event.id, timeout);
      }

      return { visibleEvents: Array.from(eventMap.values()) };
    });

    return () => {
      timeouts.forEach((t) => clearTimeout(t));
      timeouts.clear();
    };
  }, [events, timeoutsRef]);

  return [state, setState];
}
