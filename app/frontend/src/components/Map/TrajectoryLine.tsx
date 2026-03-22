import { useMemo } from 'react';
import { Polyline, CircleMarker, Tooltip } from 'react-leaflet';
import { useFlightContext } from '../../context/FlightContext';
import { useTrajectory } from '../../hooks/useTrajectory';

/** Squared distance between two lat/lon points (cheap, no sqrt needed). */
function distSq(lat1: number, lon1: number, lat2: number, lon2: number) {
  return (lat1 - lat2) ** 2 + (lon1 - lon2) ** 2;
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
  const isSimulation = dataSource === 'simulation';
  const { data: apiTrajectory } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory && !isSimulation
  );

  // Simulation-based trajectory (from frames)
  const simPoints = useMemo(() => {
    if (!isSimulation || !simTrajectoryProvider || !selectedFlight?.icao24) return null;
    return simTrajectoryProvider(selectedFlight.icao24);
  }, [isSimulation, simTrajectoryProvider, selectedFlight?.icao24]);

  // Normalize to common point format
  const validPoints: NormalizedPoint[] = useMemo(() => {
    if (isSimulation && simPoints) {
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
  }, [isSimulation, simPoints, apiTrajectory]);

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

  if (!showTrajectory || (traveledPositions.length < 2 && remainingPositions.length < 2)) {
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
      {/* Traveled trajectory — dashed line (─ ─ ─) */}
      {traveledPositions.length >= 2 && (
        <Polyline
          positions={traveledPositions}
          pathOptions={{
            color: '#3b82f6',
            weight: 3,
            opacity: 0.8,
            dashArray: '10, 5',
          }}
        />
      )}

      {/* Remaining trajectory — animated marching-ants dotted line */}
      {remainingPositions.length >= 2 && (
        <Polyline
          positions={remainingPositions}
          pathOptions={{
            color: '#1e293b',
            weight: 3,
            opacity: 0.7,
            dashArray: '4, 8',
            className: 'trajectory-remaining',
          }}
        />
      )}

      {/* Historical position markers (show every Nth point) */}
      {validPoints
        .filter((_, i) => i % Math.max(1, Math.floor(validPoints.length / 20)) === 0)
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
