import { FeatureCollection, Feature, Polygon, LineString, Point } from 'geojson';

// Airport center coordinates (fictional airport near San Francisco Bay Area)
export const AIRPORT_CENTER: [number, number] = [37.5, -122.0];

// Zoom level for initial view
export const DEFAULT_ZOOM = 14;

// GeoJSON FeatureCollection for airport layout
export const airportLayout: FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    // Runway 10L/28R (main runway)
    {
      type: 'Feature',
      properties: {
        type: 'runway',
        name: '10L/28R',
        length: 3000,
        width: 45,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-122.015, 37.502],
          [-121.985, 37.502],
          [-121.985, 37.5015],
          [-122.015, 37.5015],
          [-122.015, 37.502],
        ]],
      },
    } as Feature<Polygon>,

    // Runway 10R/28L (parallel runway)
    {
      type: 'Feature',
      properties: {
        type: 'runway',
        name: '10R/28L',
        length: 2800,
        width: 45,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-122.012, 37.498],
          [-121.988, 37.498],
          [-121.988, 37.4975],
          [-122.012, 37.4975],
          [-122.012, 37.498],
        ]],
      },
    } as Feature<Polygon>,

    // Terminal building
    {
      type: 'Feature',
      properties: {
        type: 'terminal',
        name: 'Main Terminal',
      },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-122.005, 37.505],
          [-121.995, 37.505],
          [-121.995, 37.503],
          [-122.005, 37.503],
          [-122.005, 37.505],
        ]],
      },
    } as Feature<Polygon>,

    // Taxiway Alpha
    {
      type: 'Feature',
      properties: {
        type: 'taxiway',
        name: 'Alpha',
      },
      geometry: {
        type: 'LineString',
        coordinates: [
          [-122.005, 37.503],
          [-122.005, 37.502],
          [-122.010, 37.502],
        ],
      },
    } as Feature<LineString>,

    // Taxiway Bravo
    {
      type: 'Feature',
      properties: {
        type: 'taxiway',
        name: 'Bravo',
      },
      geometry: {
        type: 'LineString',
        coordinates: [
          [-121.995, 37.503],
          [-121.995, 37.502],
          [-121.990, 37.502],
        ],
      },
    } as Feature<LineString>,

    // Taxiway Charlie (connecting runways)
    {
      type: 'Feature',
      properties: {
        type: 'taxiway',
        name: 'Charlie',
      },
      geometry: {
        type: 'LineString',
        coordinates: [
          [-122.000, 37.502],
          [-122.000, 37.498],
        ],
      },
    } as Feature<LineString>,

    // Gate A1-A10 (North terminal)
    ...Array.from({ length: 10 }, (_, i): Feature<Point> => ({
      type: 'Feature',
      properties: {
        type: 'gate',
        name: `A${i + 1}`,
        terminal: 'A',
      },
      geometry: {
        type: 'Point',
        coordinates: [-122.004 + i * 0.001, 37.5045],
      },
    })),

    // Gate B1-B10 (South terminal)
    ...Array.from({ length: 10 }, (_, i): Feature<Point> => ({
      type: 'Feature',
      properties: {
        type: 'gate',
        name: `B${i + 1}`,
        terminal: 'B',
      },
      geometry: {
        type: 'Point',
        coordinates: [-122.004 + i * 0.001, 37.5035],
      },
    })),
  ],
};

// Helper function to get features by type
export function getFeaturesByType(type: string): Feature[] {
  return airportLayout.features.filter(
    (feature) => feature.properties?.type === type
  );
}
