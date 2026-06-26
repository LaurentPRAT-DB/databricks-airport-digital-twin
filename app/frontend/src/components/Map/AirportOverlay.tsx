import { useState, useEffect, useMemo } from 'react';
import { Source, Layer, useMap } from 'react-map-gl/maplibre';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { GeoPosition } from '../../types/airportFormats';
import { useCongestion } from '../../hooks/usePredictions';
import { useCongestionFilter } from '../../context/CongestionFilterContext';
import { CongestionArea } from '../../types/flight';

export const GATE_LABEL_ZOOM = 17;
const GATE_DOT_RADIUS_BY_ZOOM: Record<number, number> = {
  12: 2, 13: 2, 14: 3, 15: 4, 16: 5, 17: 6, 18: 7,
};

export function getGateDotRadius(zoom: number): number {
  if (zoom <= 12) return 2;
  if (zoom >= 18) return 7;
  return GATE_DOT_RADIUS_BY_ZOOM[zoom] ?? 3;
}

function geoToGeoJSONCoords(geoPoints: GeoPosition[] | undefined): [number, number][] {
  if (!geoPoints) return [];
  return geoPoints.map((p) => [Number(p.longitude), Number(p.latitude)]);
}

const CONGESTION_FILL: Record<string, { fill: string; border: string }> = {
  low:      { fill: '#22c55e', border: '#16a34a' },
  moderate: { fill: '#eab308', border: '#ca8a04' },
  high:     { fill: '#f97316', border: '#ea580c' },
  critical: { fill: '#ef4444', border: '#dc2626' },
};

const FILL_PAINT = {
  'fill-color': ['get', 'fillColor'] as ['get', string],
  'fill-opacity': ['get', 'fillOpacity'] as ['get', string],
};

const STROKE_PAINT = {
  'line-color': ['get', 'strokeColor'] as ['get', string],
  'line-width': ['get', 'strokeWidth'] as ['get', string],
};

const RUNWAY_PAINT = {
  'line-color': '#4b5563',
  'line-width': 8,
  'line-opacity': 0.9,
};

const TAXIWAY_PAINT = {
  'line-color': '#fbbf24',
  'line-width': 3,
  'line-opacity': 0.7,
};

const GATE_LABEL_PAINT = {
  'text-color': '#065f46',
  'text-halo-color': '#ffffff',
  'text-halo-width': 1,
};

const GATE_LABEL_LAYOUT = {
  'text-field': ['get', 'label'] as ['get', string],
  'text-size': 10,
  'text-offset': [0, -1.2] as [number, number],
  'text-anchor': 'bottom' as const,
} as const;

function findCongestion(name: string | undefined, areas: CongestionArea[], areaType?: string): CongestionArea | undefined {
  if (!name || areas.length === 0) return undefined;
  const norm = name.toLowerCase().replace(/\s+/g, '_').replace(/-/g, '_');
  const typed = areaType ? areas.filter((c) => c.area_type === areaType) : [];
  const candidates = typed.length > 0 ? typed : areas;
  return candidates.find((c) => c.area_id.toLowerCase() === norm)
    || candidates.find((c) => c.area_id.toLowerCase() === `${norm}_apron`)
    || candidates.find((c) => {
      const cNorm = c.area_id.toLowerCase();
      return cNorm.includes(norm) || norm.includes(cNorm);
    });
}


export default function AirportOverlay() {
  const { getGates, getTerminals, getTaxiways, getAprons, getOSMRunways } = useAirportConfigContext();
  const { congestion } = useCongestion();
  const { activeLevel } = useCongestionFilter();
  const [zoom, setZoom] = useState(14);
  const { current: map } = useMap();

  useEffect(() => {
    if (!map) return;
    const handler = () => setZoom(map.getZoom());
    map.on('zoomend', handler);
    map.on('zoom', handler);
    return () => {
      map.off('zoomend', handler);
      map.off('zoom', handler);
    };
  }, [map]);

  const showGateLabels = zoom >= GATE_LABEL_ZOOM;
  const gateDotRadius = getGateDotRadius(zoom);

  const osmGates = getGates();
  const osmTerminals = getTerminals();
  const osmTaxiways = getTaxiways();
  const osmAprons = getAprons();
  const osmRunways = getOSMRunways();

  const isFilterActive = activeLevel !== null;

  const gateCirclePaint = useMemo(() => ({
    'circle-radius': gateDotRadius,
    'circle-color': '#10b981',
    'circle-opacity': 0.9,
    'circle-stroke-color': '#059669',
    'circle-stroke-width': 1,
  }), [gateDotRadius]);

  // Build GeoJSON for runways
  const runwayGeoJSON = useMemo(() => {
    const features = osmRunways
      .filter((r) => {
        const coords = geoToGeoJSONCoords(r.geoPoints);
        return coords.length >= 2;
      })
      .map((runway) => ({
        type: 'Feature' as const,
        properties: { name: runway.name || '' },
        geometry: {
          type: 'LineString' as const,
          coordinates: geoToGeoJSONCoords(runway.geoPoints),
        },
      }));
    return { type: 'FeatureCollection' as const, features };
  }, [osmRunways]);

  // Build GeoJSON for taxiways
  const taxiwayGeoJSON = useMemo(() => {
    const features = osmTaxiways
      .filter((t) => {
        const coords = geoToGeoJSONCoords(t.geoPoints);
        return coords.length >= 2;
      })
      .map((taxiway) => ({
        type: 'Feature' as const,
        properties: { name: taxiway.name || '' },
        geometry: {
          type: 'LineString' as const,
          coordinates: geoToGeoJSONCoords(taxiway.geoPoints),
        },
      }));
    return { type: 'FeatureCollection' as const, features };
  }, [osmTaxiways]);

  // Build GeoJSON for gates (point features)
  const gateGeoJSON = useMemo(() => {
    const features = osmGates
      .filter((gate) => gate.geo)
      .map((gate) => ({
        type: 'Feature' as const,
        properties: {
          label: gate.ref || gate.name || gate.id,
        },
        geometry: {
          type: 'Point' as const,
          coordinates: [Number(gate.geo.longitude), Number(gate.geo.latitude)],
        },
      }));
    return { type: 'FeatureCollection' as const, features };
  }, [osmGates]);

  // Build GeoJSON for terminals (polygons)
  const terminalGeoJSON = useMemo(() => {
    const features = osmTerminals
      .filter((t) => {
        const coords = geoToGeoJSONCoords(t.geoPolygon);
        return coords.length >= 3;
      })
      .map((terminal) => {
        const coords = geoToGeoJSONCoords(terminal.geoPolygon);
        if (coords.length > 0 && (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1])) {
          coords.push(coords[0]);
        }
        const cong = findCongestion(terminal.name, congestion, 'terminal');
        const colors = cong ? CONGESTION_FILL[cong.level] : undefined;
        const matches = isFilterActive && cong?.level === activeLevel;
        const dimmed = isFilterActive && !matches;
        return {
          type: 'Feature' as const,
          properties: {
            name: terminal.name || 'Terminal',
            fillColor: matches ? (colors?.fill || '#ef4444') : dimmed ? '#d1d5db' : colors?.fill || '#3b82f6',
            fillOpacity: dimmed ? 0.05 : matches ? 0.85 : 0.6,
            strokeColor: matches ? '#ffffff' : dimmed ? '#d1d5db' : colors?.border || '#1d4ed8',
            strokeWidth: matches ? 5 : dimmed ? 0.5 : 2,
          },
          geometry: {
            type: 'Polygon' as const,
            coordinates: [coords],
          },
        };
      });
    return { type: 'FeatureCollection' as const, features };
  }, [osmTerminals, congestion, activeLevel, isFilterActive]);

  // Build GeoJSON for aprons (polygons)
  const apronGeoJSON = useMemo(() => {
    const features = osmAprons
      .filter((a) => {
        const coords = geoToGeoJSONCoords(a.geoPolygon);
        return coords.length >= 3;
      })
      .map((apron) => {
        const coords = geoToGeoJSONCoords(apron.geoPolygon);
        if (coords.length > 0 && (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1])) {
          coords.push(coords[0]);
        }
        const cong = findCongestion(apron.name, congestion, 'apron');
        const colors = cong ? CONGESTION_FILL[cong.level] : undefined;
        const matches = isFilterActive && cong?.level === activeLevel;
        const dimmed = isFilterActive && !matches;
        return {
          type: 'Feature' as const,
          properties: {
            name: apron.name || 'Apron',
            fillColor: matches ? (colors?.fill || '#ef4444') : dimmed ? '#d1d5db' : colors?.fill || '#6b7280',
            fillOpacity: dimmed ? 0.03 : matches ? 0.85 : cong ? 0.45 : 0.3,
            strokeColor: matches ? '#ffffff' : dimmed ? '#d1d5db' : colors?.border || '#4b5563',
            strokeWidth: matches ? 5 : dimmed ? 0.5 : cong ? 2 : 1,
          },
          geometry: {
            type: 'Polygon' as const,
            coordinates: [coords],
          },
        };
      });
    return { type: 'FeatureCollection' as const, features };
  }, [osmAprons, congestion, activeLevel, isFilterActive]);

  return (
    <>
      {/* Aprons */}
      {apronGeoJSON.features.length > 0 && (
        <Source id="aprons" type="geojson" data={apronGeoJSON}>
          <Layer id="aprons-fill" type="fill" paint={FILL_PAINT} />
          <Layer id="aprons-stroke" type="line" paint={STROKE_PAINT} />
        </Source>
      )}

      {/* Terminals */}
      {terminalGeoJSON.features.length > 0 && (
        <Source id="terminals" type="geojson" data={terminalGeoJSON}>
          <Layer id="terminals-fill" type="fill" paint={FILL_PAINT} />
          <Layer id="terminals-stroke" type="line" paint={STROKE_PAINT} />
        </Source>
      )}

      {/* Runways */}
      {runwayGeoJSON.features.length > 0 && (
        <Source id="runways" type="geojson" data={runwayGeoJSON}>
          <Layer id="runways-line" type="line" paint={RUNWAY_PAINT} />
        </Source>
      )}

      {/* Taxiways */}
      {taxiwayGeoJSON.features.length > 0 && (
        <Source id="taxiways" type="geojson" data={taxiwayGeoJSON}>
          <Layer id="taxiways-line" type="line" paint={TAXIWAY_PAINT} />
        </Source>
      )}

      {/* Gates as circles */}
      {gateGeoJSON.features.length > 0 && (
        <Source id="gates" type="geojson" data={gateGeoJSON}>
          <Layer id="gates-circle" type="circle" paint={gateCirclePaint} />
          {showGateLabels && (
            <Layer
              id="gates-labels"
              type="symbol"
              layout={GATE_LABEL_LAYOUT}
              paint={GATE_LABEL_PAINT}
            />
          )}
        </Source>
      )}
    </>
  );
}
