import { GeoJSON, CircleMarker, Tooltip } from 'react-leaflet';
import { PathOptions } from 'leaflet';
import { Feature, Geometry } from 'geojson';
import { airportLayout, getFeaturesByType } from '../../constants/airportLayout';
import useAirportConfig from '../../hooks/useAirportConfig';

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

export default function AirportOverlay() {
  const { getGates } = useAirportConfig();
  const osmGates = getGates();

  // Fall back to hardcoded gates only if no OSM gates available
  const hardcodedGates = getFeaturesByType('gate');
  const useOsmGates = osmGates.length > 0;

  return (
    <>
      {/* Render polygons and lines */}
      <GeoJSON
        data={nonGateFeatures}
        style={getFeatureStyle}
        onEachFeature={onEachFeature}
      />

      {/* Render OSM gates as circle markers (preferred) */}
      {useOsmGates && osmGates.map((gate) => (
        <CircleMarker
          key={gate.id}
          center={[gate.geo.latitude, gate.geo.longitude]}
          radius={6}
          pathOptions={{
            fillColor: '#10b981', // emerald-500
            fillOpacity: 0.8,
            color: '#059669', // emerald-600
            weight: 2,
          }}
        >
          <Tooltip direction="top" offset={[0, -5]}>
            Gate {gate.ref || gate.name || gate.id}
          </Tooltip>
        </CircleMarker>
      ))}

      {/* Fallback: Render hardcoded gates as circle markers */}
      {!useOsmGates && hardcodedGates.map((gate) => {
        const coords = (gate.geometry as GeoJSON.Point).coordinates;
        return (
          <CircleMarker
            key={gate.properties?.name}
            center={[coords[1], coords[0]]}
            radius={6}
            pathOptions={{
              fillColor: '#10b981', // emerald-500
              fillOpacity: 0.8,
              color: '#059669', // emerald-600
              weight: 2,
            }}
          >
            <Tooltip direction="top" offset={[0, -5]}>
              Gate {gate.properties?.name}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </>
  );
}
