import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';

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

function tileToLatLngBounds(x: number, y: number, z: number): L.LatLngBounds {
  const n = Math.pow(2, z);
  const lonLeft = (x / n) * 360 - 180;
  const lonRight = ((x + 1) / n) * 360 - 180;
  const latTop = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI;
  const latBottom = (Math.atan(Math.sinh(Math.PI * (1 - (2 * (y + 1)) / n))) * 180) / Math.PI;
  return L.latLngBounds([latBottom, lonLeft], [latTop, lonRight]);
}

function detectionToLatLngBounds(det: Detection, tileBounds: L.LatLngBounds): L.LatLngBounds {
  const sw = tileBounds.getSouthWest();
  const ne = tileBounds.getNorthEast();
  const latSpan = ne.lat - sw.lat;
  const lngSpan = ne.lng - sw.lng;

  // Pixel coords: (0,0) is top-left of tile
  const detSWLat = ne.lat - (det.y2 / TILE_SIZE) * latSpan;
  const detSWLng = sw.lng + (det.x1 / TILE_SIZE) * lngSpan;
  const detNELat = ne.lat - (det.y1 / TILE_SIZE) * latSpan;
  const detNELng = sw.lng + (det.x2 / TILE_SIZE) * lngSpan;

  return L.latLngBounds([detSWLat, detSWLng], [detNELat, detNELng]);
}

interface OverlayEntry {
  event: TileEvent;
  layers: L.Layer[];
  timeout?: ReturnType<typeof setTimeout>;
}

const PHASE_COLORS = {
  loading: '#3b82f6',   // blue-500
  detected: '#f97316',  // orange-500
  done: '#10b981',      // emerald-500
  cached: '#10b981',    // emerald-500
};

const PHASE_TTL = {
  loading: 60000,  // removed when phase advances, fallback 60s
  detected: 3000,
  done: 5000,
  cached: 4000,
};

export default function InpaintingOverlay({ events }: { events: TileEvent[] }) {
  const map = useMap();
  const entriesRef = useRef<Map<string, OverlayEntry>>(new Map());

  useEffect(() => {
    const entries = entriesRef.current;

    for (const event of events) {
      const existing = entries.get(event.id);

      // Remove old layers for this tile
      if (existing) {
        existing.layers.forEach((l) => map.removeLayer(l));
        if (existing.timeout) clearTimeout(existing.timeout);
        entries.delete(event.id);
      }

      const layers: L.Layer[] = [];
      const bounds = tileToLatLngBounds(event.tileX, event.tileY, event.zoom);
      const color = PHASE_COLORS[event.phase];

      if (event.phase === 'loading') {
        // Pulsing border
        const rect = L.rectangle(bounds, {
          color,
          weight: 2,
          fill: false,
          dashArray: '6 4',
          className: 'inpainting-tile-loading',
        });
        rect.addTo(map);
        layers.push(rect);
      } else if (event.phase === 'detected' && event.detections.length > 0) {
        // Tile border
        const rect = L.rectangle(bounds, {
          color,
          weight: 2,
          fill: false,
        });
        rect.addTo(map);
        layers.push(rect);

        // Detection bounding boxes
        for (const det of event.detections) {
          const detBounds = detectionToLatLngBounds(det, bounds);
          const box = L.rectangle(detBounds, {
            color: '#ef4444', // red-500
            weight: 2,
            fillColor: '#ef4444',
            fillOpacity: 0.15,
          });
          box.bindTooltip(
            `Aircraft ${Math.round(det.confidence * 100)}%`,
            { permanent: true, direction: 'top', className: 'inpainting-det-tooltip' }
          );
          box.addTo(map);
          layers.push(box);
        }
      } else if (event.phase === 'done' || event.phase === 'cached') {
        // Brief green border
        const rect = L.rectangle(bounds, {
          color,
          weight: 2,
          fill: true,
          fillColor: color,
          fillOpacity: 0.08,
        });
        rect.addTo(map);
        layers.push(rect);

        // Show detection boxes on cached/done tiles too
        if (event.detections.length > 0) {
          for (const det of event.detections) {
            const detBounds = detectionToLatLngBounds(det, bounds);
            const box = L.rectangle(detBounds, {
              color: '#f97316', // orange-500
              weight: 2,
              fillColor: '#f97316',
              fillOpacity: 0.12,
              dashArray: '4 3',
            });
            box.bindTooltip(
              `${Math.round(det.confidence * 100)}%`,
              { permanent: true, direction: 'top', className: 'inpainting-det-tooltip' }
            );
            box.addTo(map);
            layers.push(box);
          }
        }

        // Info badge at tile center
        const center = bounds.getCenter();
        const label = event.cacheStatus === 'HIT'
          ? `CACHE HIT ${event.zoom}/${event.tileX}/${event.tileY}`
          : `${event.aircraftCount} aircraft · ${event.processingMs ?? '?'}ms · ${event.zoom}/${event.tileX}/${event.tileY}`;

        const marker = L.marker(center, {
          icon: L.divIcon({
            className: 'inpainting-badge',
            html: `<span class="inpainting-badge-inner ${event.cacheStatus === 'HIT' ? 'cache-hit' : 'cache-miss'}">${label}</span>`,
            iconSize: [0, 0],
            iconAnchor: [0, 0],
          }),
          interactive: false,
        });
        marker.addTo(map);
        layers.push(marker);
      }

      // Auto-remove after TTL
      const ttl = PHASE_TTL[event.phase];
      const timeout = setTimeout(() => {
        const entry = entries.get(event.id);
        if (entry && entry.event.timestamp === event.timestamp) {
          entry.layers.forEach((l) => map.removeLayer(l));
          entries.delete(event.id);
        }
      }, ttl);

      entries.set(event.id, { event, layers, timeout });
    }

    // Cleanup on unmount
    return () => {
      entries.forEach((entry) => {
        entry.layers.forEach((l) => map.removeLayer(l));
        if (entry.timeout) clearTimeout(entry.timeout);
      });
      entries.clear();
    };
  }, [events, map]);

  return null;
}
