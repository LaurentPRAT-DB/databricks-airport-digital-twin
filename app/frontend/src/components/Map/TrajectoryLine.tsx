import { useMemo } from 'react';
import { Source, Layer, Marker } from 'react-map-gl/maplibre';
import { useFlightContext } from '../../context/FlightContext';
import { useTrajectory } from '../../hooks/useTrajectory';

/** Squared distance between two lat/lon points (cheap, no sqrt needed). */
export function distSq(lat1: number, lon1: number, lat2: number, lon2: number) {
  return (lat1 - lat2) ** 2 + (lon1 - lon2) ** 2;
}

const MAX_GAP_SQ = 0.08 * 0.08;

/** Split a polyline into segments wherever consecutive points are far apart. */
export function splitAtGaps(positions: [number, number][]): [number, number][][] {
  if (positions.length < 2) return positions.length === 0 ? [] : [positions];
  const segments: [number, number][][] = [];
  let current: [number, number][] = [positions[0]];
  for (let i = 1; i < positions.length; i++) {
    const prev = positions[i - 1];
    const cur = positions[i];
    if (distSq(prev[0], prev[1], cur[0], cur[1]) > MAX_GAP_SQ) {
      if (current.length >= 2) segments.push(current);
      current = [cur];
    } else {
      current.push(cur);
    }
  }
  if (current.length >= 2) segments.push(current);
  return segments;
}

/** Perpendicular distance from point to line segment (start→end). */
export function perpendicularDist(point: [number, number], start: [number, number], end: [number, number]): number {
  const [px, py] = point;
  const [sx, sy] = start;
  const [ex, ey] = end;
  const dx = ex - sx;
  const dy = ey - sy;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.sqrt((px - sx) ** 2 + (py - sy) ** 2);
  const t = Math.max(0, Math.min(1, ((px - sx) * dx + (py - sy) * dy) / lenSq));
  return Math.sqrt((px - (sx + t * dx)) ** 2 + (py - (sy + t * dy)) ** 2);
}

/** Douglas-Peucker line simplification. */
export function simplify(points: [number, number][], epsilon = 0.0001): [number, number][] {
  if (points.length < 3) return points;
  let maxDist = 0;
  let maxIdx = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const d = perpendicularDist(points[i], points[0], points[points.length - 1]);
    if (d > maxDist) { maxDist = d; maxIdx = i; }
  }
  if (maxDist > epsilon) {
    const left = simplify(points.slice(0, maxIdx + 1), epsilon);
    const right = simplify(points.slice(maxIdx), epsilon);
    return left.slice(0, -1).concat(right);
  }
  return [points[0], points[points.length - 1]];
}

/** Chaikin's corner-cutting smoothing. */
export function chaikinSmooth(points: [number, number][], iterations = 5): [number, number][] {
  if (points.length < 3) return points;
  let result = points;
  for (let iter = 0; iter < iterations; iter++) {
    const smoothed: [number, number][] = [result[0]];
    for (let i = 0; i < result.length - 1; i++) {
      const [lat1, lon1] = result[i];
      const [lat2, lon2] = result[i + 1];
      smoothed.push([lat1 * 0.75 + lat2 * 0.25, lon1 * 0.75 + lon2 * 0.25]);
      smoothed.push([lat1 * 0.25 + lat2 * 0.75, lon1 * 0.25 + lon2 * 0.75]);
    }
    smoothed.push(result[result.length - 1]);
    result = smoothed;
  }
  return result;
}

interface NormalizedPoint {
  latitude: number;
  longitude: number;
  altitude: number | null;
  velocity: number | null;
  timestamp: number;
}

function segmentsToGeoJSON(segments: [number, number][][]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: segments.map((seg, i) => ({
      type: 'Feature' as const,
      properties: { index: i },
      geometry: {
        type: 'LineString' as const,
        coordinates: seg.map(([lat, lng]) => [lng, lat]),
      },
    })),
  };
}

export default function TrajectoryLine() {
  const { selectedFlight, showTrajectory, dataSource, simTrajectoryProvider } = useFlightContext();

  const usesReplayTrajectory = dataSource === 'simulation' || dataSource === 'opensky_recorded' || dataSource === 'opensky';
  const { data: apiTrajectory } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory && !usesReplayTrajectory
  );

  const simPoints = useMemo(() => {
    if (!usesReplayTrajectory || !simTrajectoryProvider || !selectedFlight?.icao24) return null;
    return simTrajectoryProvider(selectedFlight.icao24);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usesReplayTrajectory, simTrajectoryProvider, selectedFlight?.icao24, selectedFlight?.latitude, selectedFlight?.longitude]);

  const validPoints: NormalizedPoint[] = useMemo(() => {
    if (usesReplayTrajectory && simPoints) {
      return simPoints
        .filter(p => p.latitude != null && p.longitude != null)
        .map(p => ({
          latitude: p.latitude,
          longitude: p.longitude,
          altitude: p.altitude,
          velocity: p.velocity,
          timestamp: p.timestamp,
        }));
    }
    if (apiTrajectory) {
      return apiTrajectory.points
        .filter(p => p.latitude !== null && p.longitude !== null)
        .map(p => ({
          latitude: p.latitude!,
          longitude: p.longitude!,
          altitude: p.altitude,
          velocity: p.velocity,
          timestamp: p.timestamp,
        }));
    }
    return [];
  }, [usesReplayTrajectory, simPoints, apiTrajectory]);

  const isOnGround = selectedFlight?.on_ground === true || (selectedFlight?.altitude != null && selectedFlight.altitude < 50);
  const displayPoints = useMemo(() => {
    if (!isOnGround) return validPoints;
    const groundPoints = validPoints.filter(p => p.altitude === null || p.altitude < 200);
    return groundPoints.length >= 2 ? groundPoints : validPoints;
  }, [validPoints, isOnGround]);

  const { traveledPositions, remainingPositions } = useMemo(() => {
    if (displayPoints.length < 2 || !selectedFlight?.latitude || !selectedFlight?.longitude) {
      const all: [number, number][] = displayPoints.map((p) => [p.latitude, p.longitude]);
      return { traveledPositions: all, remainingPositions: [] as [number, number][] };
    }

    const curLat = selectedFlight.latitude;
    const curLon = selectedFlight.longitude;

    let bestIdx = displayPoints.length - 1;
    let bestDist = Infinity;
    for (let i = displayPoints.length - 1; i >= 0; i--) {
      const d = distSq(displayPoints[i].latitude, displayPoints[i].longitude, curLat, curLon);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
      if (d < 1e-10) break;
    }

    const currentPos: [number, number] = [curLat, curLon];

    const traveled: [number, number][] = displayPoints
      .slice(0, bestIdx + 1)
      .map((p) => [p.latitude, p.longitude]);
    traveled.push(currentPos);

    const remaining: [number, number][] = [currentPos];
    for (let i = bestIdx + 1; i < displayPoints.length; i++) {
      remaining.push([displayPoints[i].latitude, displayPoints[i].longitude]);
    }

    return { traveledPositions: traveled, remainingPositions: remaining };
  }, [displayPoints, selectedFlight?.latitude, selectedFlight?.longitude]);

  const avgAltitude = useMemo(() => {
    if (displayPoints.length === 0) return 0;
    const sum = displayPoints.reduce((acc, p) => acc + (p.altitude ?? 0), 0);
    return sum / displayPoints.length;
  }, [displayPoints]);
  const isGroundTrajectory = avgAltitude < 200;

  const traveledSegments = useMemo(() => splitAtGaps(traveledPositions).map(s => isGroundTrajectory ? s : chaikinSmooth(simplify(s))), [traveledPositions, isGroundTrajectory]);
  const remainingSegments = useMemo(() => splitAtGaps(remainingPositions).map(s => isGroundTrajectory ? s : chaikinSmooth(simplify(s))), [remainingPositions, isGroundTrajectory]);

  if (!showTrajectory || (traveledSegments.length === 0 && remainingSegments.length === 0)) {
    return null;
  }

  const traveledGeoJSON = segmentsToGeoJSON(traveledSegments);
  const remainingGeoJSON = segmentsToGeoJSON(remainingSegments);

  // Waypoints (every Nth point)
  const waypointGeoJSON: GeoJSON.FeatureCollection = {
    type: 'FeatureCollection',
    features: validPoints
      .filter((_, i) => i % Math.max(1, Math.floor(validPoints.length / 10)) === 0)
      .map((point) => ({
        type: 'Feature' as const,
        properties: {
          altitude: point.altitude,
          velocity: point.velocity,
          time: new Date(point.timestamp * 1000).toLocaleTimeString(),
        },
        geometry: {
          type: 'Point' as const,
          coordinates: [point.longitude, point.latitude],
        },
      })),
  };

  return (
    <>
      {/* Traveled trajectory — green dashed */}
      {traveledGeoJSON.features.length > 0 && (
        <Source id="trajectory-traveled" type="geojson" data={traveledGeoJSON}>
          <Layer
            id="trajectory-traveled-line"
            type="line"
            paint={{
              'line-color': '#22c55e',
              'line-width': 3,
              'line-opacity': 0.8,
              'line-dasharray': [2, 1],
            }}
          />
        </Source>
      )}

      {/* Remaining trajectory — blue dotted */}
      {remainingGeoJSON.features.length > 0 && (
        <Source id="trajectory-remaining" type="geojson" data={remainingGeoJSON}>
          <Layer
            id="trajectory-remaining-line"
            type="line"
            paint={{
              'line-color': '#3b82f6',
              'line-width': 3,
              'line-opacity': 0.7,
              'line-dasharray': [1, 2],
            }}
          />
        </Source>
      )}

      {/* Waypoint markers */}
      {waypointGeoJSON.features.length > 0 && (
        <Source id="trajectory-waypoints" type="geojson" data={waypointGeoJSON}>
          <Layer
            id="trajectory-waypoints-circle"
            type="circle"
            paint={{
              'circle-radius': 4,
              'circle-color': '#22c55e',
              'circle-stroke-color': '#166534',
              'circle-stroke-width': 1,
              'circle-opacity': 0.8,
            }}
          />
        </Source>
      )}

      {/* Start point marker */}
      {validPoints.length > 0 && (
        <Marker
          longitude={validPoints[0].longitude}
          latitude={validPoints[0].latitude}
          anchor="center"
        >
          <div
            className="flex items-center justify-center"
            style={{
              width: 16,
              height: 16,
              borderRadius: '50%',
              backgroundColor: '#10b981',
              border: '2px solid #059669',
            }}
          />
        </Marker>
      )}
    </>
  );
}
