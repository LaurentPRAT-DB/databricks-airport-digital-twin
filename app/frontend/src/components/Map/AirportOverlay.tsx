import { useState } from 'react';
import { GeoJSON, CircleMarker, Tooltip, Polygon, Polyline, useMapEvents } from 'react-leaflet';
import { PathOptions, LatLngExpression } from 'leaflet';
import { Feature, Geometry } from 'geojson';
import { airportLayout, getFeaturesByType } from '../../constants/airportLayout';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { GeoPosition } from '../../types/airportFormats';
import { useCongestion } from '../../hooks/usePredictions';
import { useCongestionFilter } from '../../context/CongestionFilterContext';
import { CongestionArea } from '../../types/flight';

// Zoom thresholds for gate rendering (exported for testing)
export const GATE_LABEL_ZOOM = 17; // Show permanent text labels at this zoom and above (17 avoids overlap at medium zoom)
const GATE_DOT_RADIUS_BY_ZOOM: Record<number, number> = {
  12: 2,
  13: 2,
  14: 3,
  15: 4,
  16: 5,
  17: 6,
  18: 7,
};

export function getGateDotRadius(zoom: number): number {
  if (zoom <= 12) return 2;
  if (zoom >= 18) return 7;
  return GATE_DOT_RADIUS_BY_ZOOM[zoom] ?? 3;
}

// Style function for different feature types
function getFeatureStyle(feature: Feature<Geometry> | undefined): PathOptions {
  if (!feature?.properties) return {};

  const { type } = feature.properties;

  switch (type) {
    case 'runway':
      return {
        fillColor: '#4b5563', // gray-600
        fillOpacity: 0.8,
        color: '#1f2937', // gray-800
        weight: 2,
      };
    case 'taxiway':
      return {
        color: '#fbbf24', // amber-400
        weight: 4,
        opacity: 0.8,
      };
    case 'terminal':
      return {
        fillColor: '#3b82f6', // blue-500
        fillOpacity: 0.6,
        color: '#1d4ed8', // blue-700
        weight: 2,
      };
    default:
      return {
        fillColor: '#9ca3af',
        fillOpacity: 0.5,
        color: '#6b7280',
        weight: 1,
      };
  }
}

// Tooltip content for features
function onEachFeature(feature: Feature<Geometry>, layer: L.Layer) {
  if (feature.properties?.name) {
    layer.bindTooltip(feature.properties.name, {
      permanent: false,
      direction: 'top',
    });
  }
}

// Filter out gate points (we'll render them separately)
const nonGateFeatures = {
  ...airportLayout,
  features: airportLayout.features.filter(
    (f) => f.properties?.type !== 'gate'
  ),
};

// Helper to convert GeoPosition array to LatLngExpression array
function geoToLatLng(geoPoints: GeoPosition[] | undefined): LatLngExpression[] {
  if (!geoPoints) return [];
  return geoPoints.map((p) => [Number(p.latitude), Number(p.longitude)] as LatLngExpression);
}

// Congestion level → polygon fill/border colors
const CONGESTION_FILL: Record<string, { fill: string; border: string }> = {
  low:      { fill: '#22c55e', border: '#16a34a' },   // green-500/600
  moderate: { fill: '#eab308', border: '#ca8a04' },   // yellow-500/600
  high:     { fill: '#f97316', border: '#ea580c' },    // orange-500/600
  critical: { fill: '#ef4444', border: '#dc2626' },    // red-500/600
};

const CONGESTION_EMOJI: Record<string, string> = {
  low: '\u{1f7e2}', moderate: '\u{1f7e1}', high: '\u{1f7e0}', critical: '\u{1f534}',
};

// Match a terminal/apron name to a CongestionArea by normalized name
function findCongestion(name: string | undefined, areas: CongestionArea[]): CongestionArea | undefined {
  if (!name || areas.length === 0) return undefined;
  const norm = name.toLowerCase().replace(/\s+/g, '_');
  return areas.find((c) => {
    const cNorm = c.area_id.toLowerCase();
    return cNorm === norm || cNorm === `${norm}_apron` || cNorm.includes(norm);
  });
}

// Build tooltip text for a congested area
function congestionTooltipText(name: string, cong: CongestionArea): string {
  const emoji = CONGESTION_EMOJI[cong.level] || '';
  const label = cong.level.charAt(0).toUpperCase() + cong.level.slice(1);
  const wait = cong.wait_minutes > 0 ? `, ~${cong.wait_minutes} min wait` : '';
  return `${name}\n${emoji} ${label} \u2014 ${cong.flight_count} flights${wait}`;
}

export default function AirportOverlay() {
  const { getGates, getTerminals, getTaxiways, getAprons, getOSMRunways } = useAirportConfigContext();
  const { congestion } = useCongestion();
  const { activeLevel } = useCongestionFilter();
  const [zoom, setZoom] = useState(14);
  useMapEvents({
    zoomend: (e) => setZoom(e.target.getZoom()),
    zoom: (e) => setZoom(e.target.getZoom()),
  });
  const showGateLabels = zoom >= GATE_LABEL_ZOOM;
  const gateDotRadius = getGateDotRadius(zoom);

  const osmGates = getGates();
  const osmTerminals = getTerminals();
  const osmTaxiways = getTaxiways();
  const osmAprons = getAprons();
  const osmRunways = getOSMRunways();

  // Fall back to hardcoded gates only if no OSM gates available
  const hardcodedGates = getFeaturesByType('gate');
  const useOsmGates = osmGates.length > 0;
  const useOsmTerminals = osmTerminals.length > 0;
  const useOsmTaxiways = osmTaxiways.length > 0;
  const useOsmAprons = osmAprons.length > 0;
  const useOsmRunways = osmRunways.length > 0;

  // When a congestion filter is active, check if an area matches
  const isFilterActive = activeLevel !== null;

  // Hide all hardcoded elements when ANY OSM data is present (matches 3D behavior)
  const hasOSMData = useOsmTerminals || useOsmRunways || useOsmTaxiways || useOsmAprons;

  return (
    <>
      {/* Render hardcoded GeoJSON features only when no OSM data (fallback for SFO) */}
      {!hasOSMData && (
        <GeoJSON
          data={nonGateFeatures}
          style={getFeatureStyle}
          onEachFeature={onEachFeature}
        />
      )}

      {/* Render OSM aprons (parking areas) - bottom layer, tinted by congestion */}
      {useOsmAprons && osmAprons.map((apron) => {
        const positions = geoToLatLng(apron.geoPolygon);
        if (positions.length < 3) return null;
        const cong = findCongestion(apron.name, congestion);
        const colors = cong ? CONGESTION_FILL[cong.level] : undefined;
        const matches = isFilterActive && cong?.level === activeLevel;
        const dimmed = isFilterActive && !matches;
        return (
          <Polygon
            key={apron.id}
            positions={positions}
            pathOptions={{
              fillColor: colors?.fill || '#6b7280',
              fillOpacity: dimmed ? 0.08 : matches ? 0.7 : cong ? 0.45 : 0.3,
              color: matches ? '#2563eb' : dimmed ? '#94a3b8' : colors?.border || '#4b5563',
              weight: matches ? 4 : dimmed ? 1 : cong ? 2 : 1,
              dashArray: matches ? '6 3' : undefined,
            }}
          >
            <Tooltip direction="center">
              {cong && apron.name
                ? congestionTooltipText(apron.name, cong)
                : apron.name || 'Apron'}
            </Tooltip>
          </Polygon>
        );
      })}

      {/* Render OSM terminals - below runways, taxiways, and gates, tinted by congestion */}
      {useOsmTerminals && osmTerminals.map((terminal) => {
        const positions = geoToLatLng(terminal.geoPolygon);
        if (positions.length < 3) return null;
        const cong = findCongestion(terminal.name, congestion);
        const colors = cong ? CONGESTION_FILL[cong.level] : undefined;
        const matches = isFilterActive && cong?.level === activeLevel;
        const dimmed = isFilterActive && !matches;
        return (
          <Polygon
            key={terminal.id}
            positions={positions}
            pathOptions={{
              fillColor: dimmed ? '#94a3b8' : colors?.fill || '#3b82f6',
              fillOpacity: dimmed ? 0.1 : matches ? 0.8 : 0.6,
              color: matches ? '#2563eb' : dimmed ? '#94a3b8' : colors?.border || '#1d4ed8',
              weight: matches ? 4 : dimmed ? 1 : 2,
              dashArray: matches ? '6 3' : undefined,
            }}
          >
            <Tooltip direction="center">
              {cong
                ? congestionTooltipText(terminal.name, cong)
                : terminal.name}
            </Tooltip>
          </Polygon>
        );
      })}

      {/* Render OSM runways as polylines */}
      {useOsmRunways && osmRunways.map((runway) => {
        const positions = geoToLatLng(runway.geoPoints);
        if (positions.length < 2) return null;
        return (
          <Polyline
            key={runway.id}
            positions={positions}
            pathOptions={{
              color: '#4b5563', // gray-600
              weight: 8,
              opacity: 0.9,
            }}
          >
            {runway.name && (
              <Tooltip direction="center">
                RWY {runway.name}
              </Tooltip>
            )}
          </Polyline>
        );
      })}

      {/* Render OSM taxiways */}
      {useOsmTaxiways && osmTaxiways.map((taxiway) => {
        const positions = geoToLatLng(taxiway.geoPoints);
        if (positions.length < 2) return null;
        return (
          <Polyline
            key={taxiway.id}
            positions={positions}
            pathOptions={{
              color: '#fbbf24', // amber-400
              weight: 3,
              opacity: 0.7,
            }}
          >
            {taxiway.name && (
              <Tooltip direction="center">
                TWY {taxiway.name}
              </Tooltip>
            )}
          </Polyline>
        );
      })}

      {/* Render OSM gates as circle markers (preferred) - top layer so labels are visible */}
      {useOsmGates && osmGates.filter((gate) => gate.geo).map((gate, index) => {
        const label = gate.ref || gate.name || gate.id;
        return (
          <CircleMarker
            key={`osm-${index}-${gate.id}-${showGateLabels}`}
            center={[Number(gate.geo.latitude), Number(gate.geo.longitude)]}
            radius={gateDotRadius}
            pathOptions={{
              fillColor: '#10b981', // emerald-500
              fillOpacity: 0.9,
              color: '#059669', // emerald-600
              weight: 1,
            }}
          >
            {showGateLabels ? (
              <Tooltip permanent direction="top" offset={[0, -4]}
                className="gate-label"
              >
                {label}
              </Tooltip>
            ) : (
              <Tooltip direction="top" offset={[0, -4]}>
                Gate {label}
              </Tooltip>
            )}
          </CircleMarker>
        );
      })}

      {/* Fallback: Render hardcoded gates as circle markers */}
      {!useOsmGates && hardcodedGates.map((gate, index) => {
        const coords = (gate.geometry as GeoJSON.Point).coordinates;
        const label = gate.properties?.name;
        return (
          <CircleMarker
            key={`hardcoded-${index}-${label}-${showGateLabels}`}
            center={[coords[1], coords[0]]}
            radius={gateDotRadius}
            pathOptions={{
              fillColor: '#10b981', // emerald-500
              fillOpacity: 0.9,
              color: '#059669', // emerald-600
              weight: 1,
            }}
          >
            {showGateLabels ? (
              <Tooltip permanent direction="top" offset={[0, -4]}
                className="gate-label"
              >
                {label}
              </Tooltip>
            ) : (
              <Tooltip direction="top" offset={[0, -4]}>
                Gate {label}
              </Tooltip>
            )}
          </CircleMarker>
        );
      })}
    </>
  );
}
