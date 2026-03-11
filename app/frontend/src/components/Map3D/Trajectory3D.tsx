import { useMemo } from 'react';
import { Line } from '@react-three/drei';
import * as THREE from 'three';
import { useFlightContext } from '../../context/FlightContext';
import { useTrajectory } from '../../hooks/useTrajectory';
import { latLonTo3D, METERS_TO_SCENE_UNITS } from '../../utils/map3d-calculations';

/** Squared distance between two lat/lon points (cheap, no sqrt needed). */
function distSq(lat1: number, lon1: number, lat2: number, lon2: number) {
  return (lat1 - lat2) ** 2 + (lon1 - lon2) ** 2;
}

interface Trajectory3DProps {
  airportCenter?: { lat: number; lon: number };
}

export function Trajectory3D({ airportCenter }: Trajectory3DProps) {
  const { selectedFlight, showTrajectory } = useFlightContext();
  const { data: trajectory } = useTrajectory(
    selectedFlight?.icao24 ?? null,
    showTrajectory
  );

  const cLat = airportCenter?.lat;
  const cLon = airportCenter?.lon;

  // All trajectory points with valid coordinates
  const validPoints = useMemo(() => {
    if (!trajectory) return [];
    return trajectory.points.filter(
      (p) => p.latitude !== null && p.longitude !== null
    );
  }, [trajectory]);

  // Split into traveled / remaining at aircraft's current position
  const { traveledPts, remainingPts } = useMemo(() => {
    if (validPoints.length < 2 || !selectedFlight?.latitude || !selectedFlight?.longitude) {
      const all = validPoints.map((p) => {
        const pos = latLonTo3D(p.latitude!, p.longitude!, p.altitude, cLat, cLon);
        return new THREE.Vector3(pos.x, pos.y, pos.z);
      });
      return { traveledPts: all, remainingPts: [] as THREE.Vector3[] };
    }

    const curLat = selectedFlight.latitude;
    const curLon = selectedFlight.longitude;

    // Find closest trajectory point to aircraft
    let bestIdx = 0;
    let bestDist = Infinity;
    for (let i = 0; i < validPoints.length; i++) {
      const d = distSq(validPoints[i].latitude!, validPoints[i].longitude!, curLat, curLon);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    }

    const curPos3D = (() => {
      const pos = latLonTo3D(curLat, curLon, selectedFlight.altitude, cLat, cLon);
      return new THREE.Vector3(pos.x, pos.y, pos.z);
    })();

    const toVec = (i: number) => {
      const p = validPoints[i];
      const pos = latLonTo3D(p.latitude!, p.longitude!, p.altitude, cLat, cLon);
      return new THREE.Vector3(pos.x, pos.y, pos.z);
    };

    const traveled: THREE.Vector3[] = [];
    for (let i = 0; i <= bestIdx; i++) traveled.push(toVec(i));
    traveled.push(curPos3D);

    const remaining: THREE.Vector3[] = [curPos3D];
    for (let i = bestIdx + 1; i < validPoints.length; i++) remaining.push(toVec(i));

    return { traveledPts: traveled, remainingPts: remaining };
  }, [validPoints, selectedFlight?.latitude, selectedFlight?.longitude, selectedFlight?.altitude, cLat, cLon]);

  if (!showTrajectory || (traveledPts.length < 2 && remainingPts.length < 2)) {
    return null;
  }

  return (
    <group>
      {/* Traveled trajectory — dashed line (─ ─ ─) */}
      {traveledPts.length >= 2 && (
        <Line
          points={traveledPts}
          color="#3b82f6"
          lineWidth={3}
          dashed={true}
          dashSize={5 * METERS_TO_SCENE_UNITS}
          gapSize={3 * METERS_TO_SCENE_UNITS}
        />
      )}

      {/* Remaining trajectory — dotted line (· · ·), dark for visibility */}
      {remainingPts.length >= 2 && (
        <Line
          points={remainingPts}
          color="#1e293b"
          lineWidth={3}
          dashed={true}
          dashSize={1.5 * METERS_TO_SCENE_UNITS}
          gapSize={4 * METERS_TO_SCENE_UNITS}
        />
      )}

      {/* Trajectory points (spheres at intervals) — traveled portion only */}
      {traveledPts
        .filter((_, i) => i % Math.max(1, Math.floor(traveledPts.length / 15)) === 0)
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
      {traveledPts.length > 0 && (
        <mesh position={traveledPts[0]}>
          <sphereGeometry args={[4 * METERS_TO_SCENE_UNITS, 12, 12]} />
          <meshStandardMaterial
            color="#10b981"
            emissive="#059669"
            emissiveIntensity={0.5}
          />
        </mesh>
      )}

      {/* Vertical lines from trajectory to ground (helps visualize altitude) */}
      {traveledPts
        .filter((_, i) => i % Math.max(1, Math.floor(traveledPts.length / 10)) === 0)
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
