import { useState } from 'react';
import { CircleMarker, Tooltip, Polygon, Polyline, useMapEvents } from 'react-leaflet';
import L, { LatLngExpression } from 'leaflet';
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
function findCongestion(name: string | undefined, areas: CongestionArea[], areaType?: string): CongestionArea | undefined {
  if (!name || areas.length === 0) return undefined;
  const norm = name.toLowerCase().replace(/\s+/g, '_').replace(/-/g, '_');

  // If area type is specified, prefer matching areas of that type first
  const typed = areaType ? areas.filter((c) => c.area_type === areaType) : [];
  const candidates = typed.length > 0 ? typed : areas;

  // Try exact match first, then prefix match, then substring as fallback
  return candidates.find((c) => c.area_id.toLowerCase() === norm)
    || candidates.find((c) => c.area_id.toLowerCase() === `${norm}_apron`)
    || candidates.find((c) => {
      const cNorm = c.area_id.toLowerCase();
      return cNorm.includes(norm) || norm.includes(cNorm);
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
  const { activeLevel, selectedArea, setSelectedArea } = useCongestionFilter();
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

  // When a congestion filter is active, check if an area matches
  const isFilterActive = activeLevel !== null;

  return (
    <>
      {/* Render OSM aprons (parking areas) - bottom layer, tinted by congestion */}
      {osmAprons.length > 0 && osmAprons.map((apron) => {
        const positions = geoToLatLng(apron.geoPolygon);
        if (positions.length < 3) return null;
        const cong = findCongestion(apron.name, congestion, 'apron');
        const colors = cong ? CONGESTION_FILL[cong.level] : undefined;
        const matches = isFilterActive && cong?.level === activeLevel;
        const dimmed = isFilterActive && !matches;
        const isSelected = selectedArea && cong && selectedArea.area_id === cong.area_id;
        return (
          <Polygon
            key={apron.id}
            positions={positions}
            pathOptions={{
              fillColor: matches ? (colors?.fill || '#ef4444') : dimmed ? '#d1d5db' : colors?.fill || '#6b7280',
              fillOpacity: dimmed ? 0.03 : matches ? 0.85 : cong ? 0.45 : 0.3,
              color: isSelected ? '#3b82f6' : matches ? '#ffffff' : dimmed ? '#d1d5db' : colors?.border || '#4b5563',
              weight: isSelected ? 4 : matches ? 5 : dimmed ? 0.5 : cong ? 2 : 1,
              opacity: dimmed ? 0.2 : 1,
            }}
            eventHandlers={cong ? {
              click: (e) => {
                L.DomEvent.stopPropagation(e);
                setSelectedArea(isSelected ? null : cong);
              },
            } : undefined}
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
      {osmTerminals.length > 0 && osmTerminals.map((terminal) => {
        const positions = geoToLatLng(terminal.geoPolygon);
        if (positions.length < 3) return null;
        const cong = findCongestion(terminal.name, congestion, 'terminal');
        const colors = cong ? CONGESTION_FILL[cong.level] : undefined;
        const matches = isFilterActive && cong?.level === activeLevel;
        const dimmed = isFilterActive && !matches;
        const isSelected = selectedArea && cong && selectedArea.area_id === cong.area_id;
        return (
          <Polygon
            key={terminal.id}
            positions={positions}
            pathOptions={{
              fillColor: matches ? (colors?.fill || '#ef4444') : dimmed ? '#d1d5db' : colors?.fill || '#3b82f6',
              fillOpacity: dimmed ? 0.05 : matches ? 0.85 : 0.6,
              color: isSelected ? '#3b82f6' : matches ? '#ffffff' : dimmed ? '#d1d5db' : colors?.border || '#1d4ed8',
              weight: isSelected ? 4 : matches ? 5 : dimmed ? 0.5 : 2,
              opacity: dimmed ? 0.2 : 1,
            }}
            eventHandlers={cong ? {
              click: (e) => {
                L.DomEvent.stopPropagation(e);
                setSelectedArea(isSelected ? null : cong);
              },
            } : undefined}
          >
            <Tooltip direction="center" permanent={matches}>
              {cong
                ? congestionTooltipText(terminal.name, cong)
                : terminal.name}
            </Tooltip>
          </Polygon>
        );
      })}

      {/* Render OSM runways as polylines */}
      {osmRunways.length > 0 && osmRunways.map((runway) => {
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
      {osmTaxiways.length > 0 && osmTaxiways.map((taxiway) => {
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

      {/* Render OSM gates as circle markers - top layer so labels are visible */}
      {osmGates.filter((gate) => gate.geo).map((gate, index) => {
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

    </>
  );
}
