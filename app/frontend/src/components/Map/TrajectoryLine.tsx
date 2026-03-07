import { Polyline, CircleMarker, Tooltip } from 'react-leaflet';
import { useFlightContext } from '../../context/FlightContext';
import { useTrajectory } from '../../hooks/useTrajectory';

export default function TrajectoryLine() {
  const { selectedFlight, showTrajectory } = useFlightContext();
  const { data: trajectory } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory
  );

  if (!showTrajectory || !trajectory || trajectory.points.length === 0) {
    return null;
  }

  // Filter out points with null coordinates
  const validPoints = trajectory.points.filter(
    (p) => p.latitude !== null && p.longitude !== null
  );

  if (validPoints.length < 2) {
    return null;
  }

  // Create polyline coordinates
  const positions: [number, number][] = validPoints.map((p) => [
    p.latitude!,
    p.longitude!,
  ]);

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
      {/* Main trajectory line */}
      <Polyline
        positions={positions}
        pathOptions={{
          color: '#3b82f6',
          weight: 3,
          opacity: 0.8,
          dashArray: '10, 5',
        }}
      />

      {/* Historical position markers (show every Nth point) */}
      {validPoints
        .filter((_, i) => i % Math.max(1, Math.floor(validPoints.length / 20)) === 0)
        .map((point, index) => (
          <CircleMarker
            key={`trajectory-point-${index}`}
            center={[point.latitude!, point.longitude!]}
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
        center={[validPoints[0].latitude!, validPoints[0].longitude!]}
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
