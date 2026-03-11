import { useState } from 'react';
import { GeoJSON, CircleMarker, Tooltip, Polygon, Polyline, useMapEvents } from 'react-leaflet';
import { PathOptions, LatLngExpression } from 'leaflet';
import { Feature, Geometry } from 'geojson';
import { airportLayout, getFeaturesByType } from '../../constants/airportLayout';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { GeoPosition } from '../../types/airportFormats';

// Zoom thresholds for gate rendering (exported for testing)
export const GATE_LABEL_ZOOM = 16; // Show permanent text labels at this zoom and above
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

export default function AirportOverlay() {
  const { getGates, getTerminals, getTaxiways, getAprons, getOSMRunways } = useAirportConfigContext();
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

      {/* Render OSM aprons (parking areas) - bottom layer */}
      {useOsmAprons && osmAprons.map((apron) => {
        const positions = geoToLatLng(apron.geoPolygon);
        if (positions.length < 3) return null;
        return (
          <Polygon
            key={apron.id}
            positions={positions}
            pathOptions={{
              fillColor: '#6b7280', // gray-500
              fillOpacity: 0.3,
              color: '#4b5563', // gray-600
              weight: 1,
            }}
          >
            {apron.name && (
              <Tooltip direction="center">
                {apron.name}
              </Tooltip>
            )}
          </Polygon>
        );
      })}

      {/* Render OSM terminals - below runways, taxiways, and gates */}
      {useOsmTerminals && osmTerminals.map((terminal) => {
        const positions = geoToLatLng(terminal.geoPolygon);
        if (positions.length < 3) return null;
        return (
          <Polygon
            key={terminal.id}
            positions={positions}
            pathOptions={{
              fillColor: '#3b82f6', // blue-500
              fillOpacity: 0.6,
              color: '#1d4ed8', // blue-700
              weight: 2,
            }}
          >
            <Tooltip direction="center">
              {terminal.name}
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
      {useOsmGates && osmGates.map((gate) => {
        const label = gate.ref || gate.name || gate.id;
        return (
          <CircleMarker
            key={gate.id}
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
      {!useOsmGates && hardcodedGates.map((gate) => {
        const coords = (gate.geometry as GeoJSON.Point).coordinates;
        const label = gate.properties?.name;
        return (
          <CircleMarker
            key={label}
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
