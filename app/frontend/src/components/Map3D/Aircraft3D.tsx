import { useRef, useState, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { Flight } from '../../types/flight';
import { GLTFAircraft } from './GLTFAircraft';
import {
  getAirlineFromCallsign,
  getModelForAircraftType,
} from '../../config/aircraftModels';

interface Aircraft3DProps {
  flight: Flight;
  selected?: boolean;
  onClick?: () => void;
}

// Center coordinates for the airport (must match synthetic data and 2D layout)
const CENTER_LAT = 37.5;
const CENTER_LON = -122.0;

// Scale factor to map lat/lon to 3D scene units
// 3D scene: runways at z=±100, terminal at z=0
// 2D layout: runways at lat ~37.498-37.502, terminal at lat ~37.504
// Scale chosen so that lat 37.504 (gates) maps to z≈-40 (near terminal)
const COORDINATE_SCALE = 10000;

/**
 * Convert lat/lon to 3D scene coordinates
 *
 * Maps real-world lat/lon coordinates to the 3D airport scene.
 * The scene is centered at AIRPORT_CENTER (37.5, -122.0) with:
 * - X axis: East-West (positive = East)
 * - Z axis: North-South (negative = North)
 * - Y axis: Altitude
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
  scale: number = COORDINATE_SCALE
): { x: number; y: number; z: number } {
  // Convert lat/lon offset to scene coordinates
  // Longitude → X axis (scaled by cos(lat) for projection)
  const x = (lon - centerLon) * scale * Math.cos(centerLat * Math.PI / 180);
  // Latitude → Z axis (negative because Z points south in scene)
  const z = -(lat - centerLat) * scale;

  // Convert altitude from feet to scene units
  // Ground-level flights get y=5 to stay above ground plane
  const altitudeMeters = (altitude || 0) * 0.3048;
  const y = altitudeMeters * 0.05 + 5; // Scale altitude for visibility

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
  // Store current interpolated values to animate toward targets
  const currentPosition = useRef(new THREE.Vector3(targetPosition.x, targetPosition.y, targetPosition.z));
  const currentRotation = useRef(targetRotation);

  /**
   * Smooth Animation Loop
   *
   * Uses linear interpolation (lerp) to smoothly animate aircraft
   * from their current position/rotation toward the target values
   * derived from flight data. This creates fluid motion rather than
   * jumping when new data arrives.
   *
   * Lerp factor of 0.1 means the object moves 10% of the remaining
   * distance toward the target each frame, creating smooth deceleration.
   */
  useFrame((_, delta) => {
    if (!groupRef.current) return;

    // Adjust lerp factor based on frame time for consistent animation speed
    // Base factor of 0.1 at 60fps, scaled by delta time
    const baseLerpFactor = 0.1;
    const lerpFactor = Math.min(baseLerpFactor * delta * 60, 1);

    // Lerp position toward target (x, y, z)
    currentPosition.current.lerp(
      new THREE.Vector3(targetPosition.x, targetPosition.y, targetPosition.z),
      lerpFactor
    );

    // Lerp rotation toward target with angle wrapping
    // Handle the case where rotation crosses the -PI/+PI boundary
    const rotDiff = targetRotation - currentRotation.current;
    let adjustedDiff = rotDiff;
    if (Math.abs(rotDiff) > Math.PI) {
      // Wrap around to take the shorter rotation path
      adjustedDiff = rotDiff > 0 ? rotDiff - 2 * Math.PI : rotDiff + 2 * Math.PI;
    }
    currentRotation.current += adjustedDiff * lerpFactor;

    // Apply interpolated values to the group transform
    groupRef.current.position.copy(currentPosition.current);
    groupRef.current.rotation.y = currentRotation.current;
  });

  // Get airline configuration from callsign
  const airline = useMemo(() => getAirlineFromCallsign(flight.callsign), [flight.callsign]);

  // Extract airline code from callsign for model lookup
  const airlineCode = useMemo(() => {
    if (!flight.callsign || flight.callsign.length < 3) return undefined;
    return flight.callsign.substring(0, 3).toUpperCase();
  }, [flight.callsign]);

  // Get model configuration based on aircraft type and airline (for airline-specific liveries)
  const modelConfig = useMemo(
    () => getModelForAircraftType(flight.aircraft_type, airlineCode),
    [flight.aircraft_type, airlineCode]
  );

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
      {/* Aircraft model - Use GLTF model with Suspense fallback */}
      <GLTFAircraft
        modelConfig={modelConfig}
        airline={airline}
        selected={selected}
      />

      {/* Selection ring - visible indicator when aircraft is selected */}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -3, 0]}>
          <ringGeometry args={[18, 22, 32]} />
          <meshBasicMaterial color={0x00ff00} transparent opacity={0.8} side={THREE.DoubleSide} />
        </mesh>
      )}

      {/* Pulsing selection indicator */}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -2, 0]}>
          <ringGeometry args={[24, 26, 32]} />
          <meshBasicMaterial color={0x00ff00} transparent opacity={0.4} side={THREE.DoubleSide} />
        </mesh>
      )}

      {/* Label - shows on hover OR when selected */}
      {(hovered || selected) && (
        <Html
          position={[0, 25, 0]}
          center
          style={{
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
          }}
        >
          <div style={{
            background: selected ? 'rgba(0, 100, 0, 0.9)' : 'rgba(0, 0, 0, 0.8)',
            color: 'white',
            padding: '6px 12px',
            borderRadius: '4px',
            fontSize: '14px',
            fontFamily: 'sans-serif',
            border: selected ? '2px solid #00ff00' : 'none',
            boxShadow: selected ? '0 0 10px rgba(0, 255, 0, 0.5)' : 'none',
          }}>
            <strong>{flight.callsign || flight.icao24}</strong>
            {flight.altitude != null && <span> | {Math.round(flight.altitude)} ft</span>}
            {flight.velocity != null && <span> | {Math.round(flight.velocity)} kts</span>}
          </div>
        </Html>
      )}
    </group>
  );
}
