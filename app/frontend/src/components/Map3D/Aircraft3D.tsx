import { useRef, useState, useMemo, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { Flight } from '../../types/flight';
import { AIRPORT_3D_CONFIG, COLORS } from '../../constants/airport3D';
import { ProceduralAircraft } from './ProceduralAircraft';
import { GLTFAircraft } from './GLTFAircraft';
import {
  getAirlineFromCallsign,
  getModelForAircraftType,
  modelExists,
} from '../../config/aircraftModels';

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

  // Get model configuration - could be enhanced with aircraft type from API
  const modelConfig = useMemo(() => getModelForAircraftType(), []);

  // Track if GLTF model is available
  const [useGLTF, setUseGLTF] = useState(false);

  // Check if model exists on mount
  useEffect(() => {
    modelExists(modelConfig.url).then(setUseGLTF);
  }, [modelConfig.url]);

  // Determine color based on selection and flight phase
  // Use airline colors when available, fall back to phase-based
  const color = useMemo(() => {
    if (selected) return COLORS.aircraftSelected;
    // Use airline primary color if recognized
    if (airline.name !== 'Unknown Airline') return airline.primaryColor;
    // Fall back to phase-based colors
    if (flight.flight_phase === 'descending') return COLORS.aircraftArriving;
    if (flight.flight_phase === 'climbing') return COLORS.aircraftDeparting;
    return COLORS.aircraftDefault;
  }, [selected, flight.flight_phase, airline]);

  // Secondary color for livery details
  const secondaryColor = useMemo(() => {
    if (airline.name !== 'Unknown Airline') return airline.secondaryColor;
    return 0x555555;
  }, [airline]);

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
      {/* Aircraft model - GLTF if available, procedural fallback */}
      {useGLTF ? (
        <GLTFAircraft
          modelConfig={modelConfig}
          airline={airline}
          selected={selected}
        />
      ) : (
        <ProceduralAircraft
          color={color}
          secondaryColor={secondaryColor}
        />
      )}

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
