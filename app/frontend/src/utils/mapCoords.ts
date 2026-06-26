import type { LngLatBoundsLike } from 'maplibre-gl';

export type LngLat = [number, number]; // [lng, lat]

export function toLngLat(lat: number, lng: number): LngLat {
  return [lng, lat];
}

export function toGeoJSONLineString(positions: [number, number][]): GeoJSON.LineString {
  return {
    type: 'LineString',
    coordinates: positions.map(([lat, lng]) => [lng, lat]),
  };
}

export function toGeoJSONPolygon(positions: [number, number][]): GeoJSON.Polygon {
  const coords = positions.map(([lat, lng]) => [lng, lat]);
  if (coords.length > 0 && (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1])) {
    coords.push(coords[0]);
  }
  return {
    type: 'Polygon',
    coordinates: [coords],
  };
}

export function boundsFromLatLngs(points: { lat: number; lng: number }[]): LngLatBoundsLike {
  let minLat = 90, maxLat = -90, minLng = 180, maxLng = -180;
  for (const p of points) {
    minLat = Math.min(minLat, p.lat);
    maxLat = Math.max(maxLat, p.lat);
    minLng = Math.min(minLng, p.lng);
    maxLng = Math.max(maxLng, p.lng);
  }
  return [[minLng, minLat], [maxLng, maxLat]];
}
