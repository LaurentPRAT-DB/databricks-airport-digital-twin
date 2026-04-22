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

  // API-based trajectory (for live flights)
  const usesReplayTrajectory = dataSource === 'simulation' || dataSource === 'opensky_recorded';
  const { data: apiTrajectory } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory && !usesReplayTrajectory
  );

  // Replay-based trajectory (from frames — simulation and recorded data)
  const simPoints = useMemo(() => {
    if (!usesReplayTrajectory || !simTrajectoryProvider || !selectedFlight?.icao24) return null;
    return simTrajectoryProvider(selectedFlight.icao24);
  }, [usesReplayTrajectory, simTrajectoryProvider, selectedFlight?.icao24]);

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

  // Split polylines at large gaps (e.g. go-around enroute segments that are
  // excluded from the trajectory, causing unrealistic straight-line jumps)
  const traveledSegments = useMemo(() => splitAtGaps(traveledPositions), [traveledPositions]);
  const remainingSegments = useMemo(() => splitAtGaps(remainingPositions), [remainingPositions]);

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
