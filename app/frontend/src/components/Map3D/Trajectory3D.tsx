import { useMemo } from 'react';
import { Line } from '@react-three/drei';
import * as THREE from 'three';
import { useFlightContext } from '../../context/FlightContext';
import { useTrajectory, TrajectoryPoint } from '../../hooks/useTrajectory';
import { latLonTo3D, METERS_TO_SCENE_UNITS } from '../../utils/map3d-calculations';

interface Trajectory3DProps {
  airportCenter?: { lat: number; lon: number };
}

export function Trajectory3D({ airportCenter }: Trajectory3DProps) {
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

  const linePoints = useMemo(() => {
    if (validPoints.length < 2) return null;

    // Convert lat/lon to 3D coordinates
    return validPoints.map((p) => {
      const pos = latLonTo3D(p.latitude!, p.longitude!, p.altitude, airportCenter?.lat, airportCenter?.lon);
      return new THREE.Vector3(pos.x, pos.y, pos.z);
    });
  }, [validPoints, airportCenter?.lat, airportCenter?.lon]);

  const colors = useMemo(() => {
    if (validPoints.length < 2) return null;

    return validPoints.map((_, index) => {
      const t = index / (validPoints.length - 1);
      // Gradient from light blue (old) to bright blue (new)
      const r = 0.2 + t * 0.1;
      const g = 0.4 + t * 0.2;
      const b = 0.8 + t * 0.2;
      return new THREE.Color(r, g, b);
    });
  }, [validPoints]);

  if (!showTrajectory || !linePoints || linePoints.length < 2) {
    return null;
  }

  return (
    <group>
      {/* Main trajectory line */}
      <Line
        points={linePoints}
        color="#3b82f6"
        lineWidth={3}
        dashed={true}
        dashSize={5 * METERS_TO_SCENE_UNITS}
        gapSize={3 * METERS_TO_SCENE_UNITS}
        vertexColors={colors || undefined}
      />

      {/* Trajectory points (spheres at intervals) */}
      {linePoints
        .filter((_, i) => i % Math.max(1, Math.floor(linePoints.length / 15)) === 0)
        .map((point, index) => (
          <mesh key={`traj-point-${index}`} position={point}>
            <sphereGeometry args={[2 * METERS_TO_SCENE_UNITS, 8, 8]} />
            <meshStandardMaterial
              color={index === 0 ? '#10b981' : '#3b82f6'}
              emissive={index === 0 ? '#059669' : '#1e40af'}
              emissiveIntensity={0.3}
            />
          </mesh>
        ))}

      {/* Start point (larger, green) */}
      <mesh position={linePoints[0]}>
        <sphereGeometry args={[4 * METERS_TO_SCENE_UNITS, 12, 12]} />
        <meshStandardMaterial
          color="#10b981"
          emissive="#059669"
          emissiveIntensity={0.5}
        />
      </mesh>

      {/* Vertical lines from trajectory to ground (helps visualize altitude) */}
      {linePoints
        .filter((_, i) => i % Math.max(1, Math.floor(linePoints.length / 10)) === 0)
        .map((point, index) => {
          const groundPoint = new THREE.Vector3(point.x, 0.5, point.z);
          return (
            <Line
              key={`vertical-${index}`}
              points={[point, groundPoint]}
              color="#94a3b8"
              lineWidth={1}
              opacity={0.3}
              transparent
            />
          );
        })}
    </group>
  );
}
