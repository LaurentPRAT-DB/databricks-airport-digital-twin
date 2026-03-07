import { useMemo } from 'react';
import { Line } from '@react-three/drei';
import * as THREE from 'three';
import { useFlightContext } from '../../context/FlightContext';
import { useTrajectory } from '../../hooks/useTrajectory';
import { latLonTo3D } from './Aircraft3D';

export function Trajectory3D() {
  const { selectedFlight, showTrajectory } = useFlightContext();
  const { data: trajectory } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory
  );

  const linePoints = useMemo(() => {
    if (!trajectory || trajectory.points.length < 2) return null;

    // Filter out points with null coordinates
    const validPoints = trajectory.points.filter(
      (p) => p.latitude !== null && p.longitude !== null
    );

    if (validPoints.length < 2) return null;

    // Convert lat/lon to 3D coordinates
    return validPoints.map((p) => {
      const pos = latLonTo3D(p.latitude!, p.longitude!, p.altitude);
      return new THREE.Vector3(pos.x, pos.y, pos.z);
    });
  }, [trajectory]);

  const colors = useMemo(() => {
    if (!trajectory || trajectory.points.length < 2) return null;

    // Create color gradient based on time (older = more transparent blue, newer = bright blue)
    const validPoints = trajectory.points.filter(
      (p) => p.latitude !== null && p.longitude !== null
    );

    return validPoints.map((_, index) => {
      const t = index / (validPoints.length - 1);
      // Gradient from light blue (old) to bright blue (new)
      const r = 0.2 + t * 0.1;
      const g = 0.4 + t * 0.2;
      const b = 0.8 + t * 0.2;
      return new THREE.Color(r, g, b);
    });
  }, [trajectory]);

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
        dashSize={5}
        gapSize={3}
        vertexColors={colors || undefined}
      />

      {/* Trajectory points (spheres at intervals) */}
      {linePoints
        .filter((_, i) => i % Math.max(1, Math.floor(linePoints.length / 15)) === 0)
        .map((point, index) => (
          <mesh key={`traj-point-${index}`} position={point}>
            <sphereGeometry args={[2, 8, 8]} />
            <meshStandardMaterial
              color={index === 0 ? '#10b981' : '#3b82f6'}
              emissive={index === 0 ? '#059669' : '#1e40af'}
              emissiveIntensity={0.3}
            />
          </mesh>
        ))}

      {/* Start point (larger, green) */}
      <mesh position={linePoints[0]}>
        <sphereGeometry args={[4, 12, 12]} />
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
