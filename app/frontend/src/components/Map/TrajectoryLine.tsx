import { useMemo } from 'react';
import { Polyline, CircleMarker, Tooltip } from 'react-leaflet';
import { useFlightContext } from '../../context/FlightContext';
import { useTrajectory } from '../../hooks/useTrajectory';

/** Squared distance between two lat/lon points (cheap, no sqrt needed). */
function distSq(lat1: number, lon1: number, lat2: number, lon2: number) {
  return (lat1 - lat2) ** 2 + (lon1 - lon2) ** 2;
}

/** Max gap (degrees²) before splitting a polyline — ~0.04° ≈ 2.5 NM.
 *  Normal 30s snapshot spacing at 180 kts is ~0.025° (0.000625 sq),
 *  go-around gaps are 0.08°+ (0.0064 sq). */
const MAX_GAP_SQ = 0.04 * 0.04; // 0.0016

/** Split a polyline into segments wherever consecutive points are far apart. */
function splitAtGaps(positions: [number, number][]): [number, number][][] {
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
function perpendicularDist(point: [number, number], start: [number, number], end: [number, number]): number {
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

/** Douglas-Peucker line simplification: removes noise while preserving shape.
 *  Epsilon in degrees — 0.0001° ≈ 11m, enough to eliminate GPS/sim jitter. */
function simplify(points: [number, number][], epsilon = 0.0001): [number, number][] {
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

/** Chaikin's corner-cutting: smooths sharp turns while preserving straight segments.
 *  Each iteration replaces each edge midpoint pair with two 25%/75% points.
 *  5 iterations gives smooth arcs even for near-180° reversals (go-arounds). */
function chaikinSmooth(points: [number, number][], iterations = 5): [number, number][] {
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

/** Normalize trajectory points from either API or simulation into a common shape. */
interface NormalizedPoint {
  latitude: number;
  longitude: number;
  altitude: number | null;
  velocity: number | null;
  timestamp: number;
}

export default function TrajectoryLine() {
  const { selectedFlight, showTrajectory, dataSource, simTrajectoryProvider } = useFlightContext();

  // Provider-based trajectory (simulation, recorded, and live with accumulated trails)
  const usesReplayTrajectory = dataSource === 'simulation' || dataSource === 'opensky_recorded' || dataSource === 'opensky';
  const { data: apiTrajectory } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory && !usesReplayTrajectory
  );

  // Replay-based trajectory (from frames — simulation, recorded, and live trails)
  const simPoints = useMemo(() => {
    if (!usesReplayTrajectory || !simTrajectoryProvider || !selectedFlight?.icao24) return null;
    return simTrajectoryProvider(selectedFlight.icao24);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usesReplayTrajectory, simTrajectoryProvider, selectedFlight?.icao24, selectedFlight?.latitude, selectedFlight?.longitude]);

  // Normalize to common point format
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

  // Split trajectory into traveled (past) and remaining (future) at the
  // aircraft's current position.  The split index is the closest trajectory
  // point to the live position.
  const { traveledPositions, remainingPositions } = useMemo(() => {
    if (validPoints.length < 2 || !selectedFlight?.latitude || !selectedFlight?.longitude) {
      const all: [number, number][] = validPoints.map((p) => [p.latitude, p.longitude]);
      return { traveledPositions: all, remainingPositions: [] as [number, number][] };
    }

    const curLat = selectedFlight.latitude;
    const curLon = selectedFlight.longitude;

    // Find closest trajectory point to aircraft
    let bestIdx = 0;
    let bestDist = Infinity;
    for (let i = 0; i < validPoints.length; i++) {
      const d = distSq(validPoints[i].latitude, validPoints[i].longitude, curLat, curLon);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    }

    const currentPos: [number, number] = [curLat, curLon];

    // Traveled: start → closest point → current position
    const traveled: [number, number][] = validPoints
      .slice(0, bestIdx + 1)
      .map((p) => [p.latitude, p.longitude]);
    traveled.push(currentPos);

    // Remaining: current position → rest of trajectory
    const remaining: [number, number][] = [currentPos];
    for (let i = bestIdx + 1; i < validPoints.length; i++) {
      remaining.push([validPoints[i].latitude, validPoints[i].longitude]);
    }

    return { traveledPositions: traveled, remainingPositions: remaining };
  }, [validPoints, selectedFlight?.latitude, selectedFlight?.longitude]);

  // Determine if the trajectory is mostly on-ground (taxi) vs airborne.
  // Ground trajectories are NOT smoothed — smoothing pulls lines through buildings.
  const avgAltitude = useMemo(() => {
    if (validPoints.length === 0) return 0;
    const sum = validPoints.reduce((acc, p) => acc + (p.altitude ?? 0), 0);
    return sum / validPoints.length;
  }, [validPoints]);
  const isGroundTrajectory = avgAltitude < 200;

  // Split polylines at large gaps (e.g. go-around enroute segments that are
  // excluded from the trajectory, causing unrealistic straight-line jumps),
  // then smooth each segment for natural-looking curves at turns.
  const traveledSegments = useMemo(() => splitAtGaps(traveledPositions).map(s => isGroundTrajectory ? s : chaikinSmooth(simplify(s))), [traveledPositions, isGroundTrajectory]);
  const remainingSegments = useMemo(() => splitAtGaps(remainingPositions).map(s => isGroundTrajectory ? s : chaikinSmooth(simplify(s))), [remainingPositions, isGroundTrajectory]);

  if (!showTrajectory || (traveledSegments.length === 0 && remainingSegments.length === 0)) {
    return null;
  }

  // Color gradient based on altitude (if available)
  const getAltitudeColor = (altitude: number | null): string => {
    if (altitude === null) return '#3b82f6';
    if (altitude < 1000) return '#22c55e'; // Green - low
    if (altitude < 5000) return '#eab308'; // Yellow - medium
    if (altitude < 15000) return '#f97316'; // Orange - high
    return '#ef4444'; // Red - very high
  };

  return (
    <>
      {/* Traveled trajectory — dashed line (─ ─ ─), split at gaps */}
      {traveledSegments.map((seg, i) => (
        <Polyline
          key={`traveled-${i}`}
          positions={seg}
          pathOptions={{
            color: '#3b82f6',
            weight: 3,
            opacity: 0.8,
            dashArray: '10, 5',
          }}
        />
      ))}

      {/* Remaining trajectory — animated marching-ants dotted line, split at gaps */}
      {remainingSegments.map((seg, i) => (
        <Polyline
          key={`remaining-${i}`}
          positions={seg}
          pathOptions={{
            color: '#1e293b',
            weight: 3,
            opacity: 0.7,
            dashArray: '4, 8',
            className: 'trajectory-remaining',
          }}
        />
      ))}

      {/* Historical position markers (show every Nth point) */}
      {validPoints
        .filter((_, i) => i % Math.max(1, Math.floor(validPoints.length / 10)) === 0)
        .map((point, index) => (
          <CircleMarker
            key={`trajectory-point-${index}`}
            center={[point.latitude, point.longitude]}
            radius={4}
            pathOptions={{
              color: '#1e40af',
              fillColor: getAltitudeColor(point.altitude),
              fillOpacity: 0.8,
              weight: 1,
            }}
          >
            <Tooltip direction="top" offset={[0, -5]}>
              <div className="text-xs">
                <div className="font-semibold">
                  {new Date(point.timestamp * 1000).toLocaleTimeString()}
                </div>
                {point.altitude && (
                  <div>Alt: {Math.round(point.altitude)} ft</div>
                )}
                {point.velocity && (
                  <div>Speed: {Math.round(point.velocity)} kts</div>
                )}
              </div>
            </Tooltip>
          </CircleMarker>
        ))}

      {/* Start point marker */}
      <CircleMarker
        center={[validPoints[0].latitude, validPoints[0].longitude]}
        radius={8}
        pathOptions={{
          color: '#059669',
          fillColor: '#10b981',
          fillOpacity: 1,
          weight: 2,
        }}
      >
        <Tooltip permanent direction="left" offset={[-10, 0]}>
          <span className="text-xs font-medium">Start</span>
        </Tooltip>
      </CircleMarker>
    </>
  );
}
