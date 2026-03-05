import { useRef, useState, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { Flight } from '../../types/flight';
import { AIRPORT_3D_CONFIG, COLORS } from '../../constants/airport3D';

interface Aircraft3DProps {
  flight: Flight;
  selected?: boolean;
  onClick?: () => void;
}

// Center coordinates for the airport (SFO area for demo)
const CENTER_LAT = 37.62;
const CENTER_LON = -122.38;

/**
 * Convert lat/lon to 3D scene coordinates
 *
 * @param lat - Latitude in degrees
 * @param lon - Longitude in degrees
 * @param altitude - Altitude in feet (optional)
 * @returns Position in 3D scene coordinates
 */
export function latLonTo3D(
  lat: number,
  lon: number,
  altitude: number | null = 0,
  centerLat: number = CENTER_LAT,
  centerLon: number = CENTER_LON,
  scale: number = AIRPORT_3D_CONFIG.scale
): { x: number; y: number; z: number } {
  // Meters per degree (approximate at this latitude)
  const metersPerDegree = 111000;

  // Convert lat/lon offset to scene coordinates
  const x = (lon - centerLon) * metersPerDegree * scale * Math.cos(centerLat * Math.PI / 180);
  const z = -(lat - centerLat) * metersPerDegree * scale; // Negative because Z is inverted in scene

  // Convert altitude from feet to scene units
  const y = ((altitude || 0) * 0.3048 * scale) + 5; // Add 5 to keep above ground

  return { x, y, z };
}

/**
 * Aircraft3D Component
 *
 * Renders a 3D aircraft model at the correct position based on flight data.
 * Features:
 * - Position based on lat/lon coordinates
 * - Rotation based on heading
 * - Color changes when selected
 * - Hover label showing callsign
 * - Smooth position/rotation animation
 */
export function Aircraft3D({ flight, selected = false, onClick }: Aircraft3DProps) {
  const groupRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);

  // Calculate target position from flight data
  const targetPosition = useMemo(() =>
    latLonTo3D(flight.latitude, flight.longitude, flight.altitude),
    [flight.latitude, flight.longitude, flight.altitude]
  );

  // Calculate target rotation from heading
  const targetRotation = useMemo(() => {
    // Heading is in degrees clockwise from north
    // Convert to radians, and adjust for scene orientation (Z is forward)
    const headingRad = ((flight.heading || 0) - 90) * Math.PI / 180;
    return headingRad;
  }, [flight.heading]);

  // Animation refs for smooth interpolation
  const currentPosition = useRef(new THREE.Vector3(targetPosition.x, targetPosition.y, targetPosition.z));
  const currentRotation = useRef(targetRotation);

  // Animate position and rotation smoothly
  useFrame(() => {
    if (!groupRef.current) return;

    // Lerp position toward target
    const lerpFactor = 0.1;
    currentPosition.current.lerp(
      new THREE.Vector3(targetPosition.x, targetPosition.y, targetPosition.z),
      lerpFactor
    );

    // Lerp rotation toward target
    const rotDiff = targetRotation - currentRotation.current;
    // Handle wrapping around 2*PI
    let adjustedDiff = rotDiff;
    if (Math.abs(rotDiff) > Math.PI) {
      adjustedDiff = rotDiff > 0 ? rotDiff - 2 * Math.PI : rotDiff + 2 * Math.PI;
    }
    currentRotation.current += adjustedDiff * lerpFactor;

    // Apply to group
    groupRef.current.position.copy(currentPosition.current);
    groupRef.current.rotation.y = currentRotation.current;
  });

  // Determine color based on selection and flight phase
  const color = useMemo(() => {
    if (selected) return COLORS.aircraftSelected;
    if (flight.flight_phase === 'descending') return COLORS.aircraftArriving;
    if (flight.flight_phase === 'climbing') return COLORS.aircraftDeparting;
    return COLORS.aircraftDefault;
  }, [selected, flight.flight_phase]);

  return (
    <group
      ref={groupRef}
      position={[targetPosition.x, targetPosition.y, targetPosition.z]}
      rotation={[0, targetRotation, 0]}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      onPointerOver={(e) => {
        e.stopPropagation();
        setHovered(true);
        document.body.style.cursor = 'pointer';
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = 'auto';
      }}
    >
      {/* Aircraft body - cone pointing forward */}
      <mesh castShadow>
        <coneGeometry args={[3, 10, 8]} />
        <meshStandardMaterial
          color={color}
          emissive={selected ? 0x002200 : 0x000000}
          emissiveIntensity={0.3}
        />
      </mesh>

      {/* Wings - flat box */}
      <mesh position={[0, 0, 2]} castShadow>
        <boxGeometry args={[20, 1, 3]} />
        <meshStandardMaterial color={color} />
      </mesh>

      {/* Tail fin */}
      <mesh position={[0, 3, 4]} castShadow>
        <boxGeometry args={[0.5, 6, 2]} />
        <meshStandardMaterial color={color} />
      </mesh>

      {/* Hover label with callsign */}
      {hovered && (
        <Html
          position={[0, 15, 0]}
          center
          style={{
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
          }}
        >
          <div style={{
            background: 'rgba(0, 0, 0, 0.8)',
            color: 'white',
            padding: '4px 8px',
            borderRadius: '4px',
            fontSize: '12px',
            fontFamily: 'sans-serif',
          }}>
            <strong>{flight.callsign || flight.icao24}</strong>
            {flight.altitude && <span> | {Math.round(flight.altitude)} ft</span>}
          </div>
        </Html>
      )}
    </group>
  );
}
