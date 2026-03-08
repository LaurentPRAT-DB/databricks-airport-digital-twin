import { useMemo } from 'react';
import { Polyline, CircleMarker, Tooltip } from 'react-leaflet';
import { useFlightContext } from '../../context/FlightContext';
import { useTrajectory, TrajectoryPoint } from '../../hooks/useTrajectory';

export default function TrajectoryLine() {
  const { selectedFlight, showTrajectory } = useFlightContext();
  const { data: trajectory } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory
  );

  // Combine historical trajectory with current position for real-time updates
  const validPoints = useMemo(() => {
    if (!trajectory) return [];

    // Filter out points with null coordinates from historical data
    const historicalPoints = trajectory.points.filter(
      (p) => p.latitude !== null && p.longitude !== null
    );

    // Append current aircraft position if available and different from last point
    if (selectedFlight?.latitude != null && selectedFlight?.longitude != null) {
      const lastPoint = historicalPoints[historicalPoints.length - 1];
      const currentPos = {
        icao24: selectedFlight.icao24,
        callsign: selectedFlight.callsign,
        latitude: selectedFlight.latitude,
        longitude: selectedFlight.longitude,
        altitude: selectedFlight.altitude,
        velocity: selectedFlight.velocity,
        heading: selectedFlight.heading,
        vertical_rate: selectedFlight.vertical_rate,
        on_ground: selectedFlight.on_ground,
        flight_phase: selectedFlight.flight_phase,
        timestamp: Date.now() / 1000,
      } as TrajectoryPoint;

      // Only append if position is different from last historical point
      if (
        !lastPoint ||
        Math.abs(lastPoint.latitude! - currentPos.latitude!) > 0.0001 ||
        Math.abs(lastPoint.longitude! - currentPos.longitude!) > 0.0001
      ) {
        return [...historicalPoints, currentPos];
      }
    }

    return historicalPoints;
  }, [trajectory, selectedFlight]);

  if (!showTrajectory || validPoints.length < 2) {
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
