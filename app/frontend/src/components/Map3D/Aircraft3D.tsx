import { useRef, useState, useMemo, useCallback } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { Flight } from '../../types/flight';
import { GLTFAircraft } from './GLTFAircraft';
import {
  getAirlineFromCallsign,
  getModelForAircraftType,
} from '../../config/aircraftModels';
import {
  latLonTo3D,
  headingToRotation,
  calculateLerpFactor,
  normalizeRotationDiff,
  extractAirlineCode,
} from '../../utils/map3d-calculations';

// Re-export for backwards compatibility
export { latLonTo3D };

// Reusable Vector3 for lerp calculations (avoids GC pressure)
const _targetVec3 = new THREE.Vector3();

interface Aircraft3DProps {
  flight: Flight;
  selected?: boolean;
  onClick?: () => void;
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
  const targetRotation = useMemo(() => headingToRotation(flight.heading), [flight.heading]);

  // Animation refs for smooth interpolation
  // Store current interpolated values to animate toward targets
  const currentPosition = useRef(new THREE.Vector3(targetPosition.x, targetPosition.y, targetPosition.z));
  const currentRotation = useRef(targetRotation);

  /**
   * Smooth Animation Loop (Optimized)
   *
   * Uses linear interpolation (lerp) to smoothly animate aircraft.
   * Optimizations:
   * - Reuses Vector3 to avoid GC pressure
   * - Batches position/rotation updates
   * - Uses requestAnimationFrame timing
   */
  useFrame((_, delta) => {
    if (!groupRef.current) return;

    // Adjust lerp factor based on frame time for consistent animation speed
    const lerpFactor = calculateLerpFactor(delta);

    // Reuse target vector to avoid allocations
    _targetVec3.set(targetPosition.x, targetPosition.y, targetPosition.z);

    // Lerp position toward target
    currentPosition.current.lerp(_targetVec3, lerpFactor);

    // Lerp rotation toward target with angle wrapping
    const adjustedDiff = normalizeRotationDiff(currentRotation.current, targetRotation);
    currentRotation.current += adjustedDiff * lerpFactor;

    // Batch DOM writes - only update if changed significantly
    const posChanged = groupRef.current.position.distanceToSquared(currentPosition.current) > 0.0001;
    const rotChanged = Math.abs(groupRef.current.rotation.y - currentRotation.current) > 0.0001;

    if (posChanged || rotChanged) {
      groupRef.current.position.copy(currentPosition.current);
      groupRef.current.rotation.y = currentRotation.current;
    }
  });

  // Get airline configuration from callsign
  const airline = useMemo(() => getAirlineFromCallsign(flight.callsign), [flight.callsign]);

  // Memoized pointer handlers to avoid reflows from cursor style changes
  const handlePointerOver = useCallback((e: { stopPropagation: () => void }) => {
    e.stopPropagation();
    setHovered(true);
    // Use CSS class toggle instead of direct style manipulation to avoid reflow
    document.body.classList.add('cursor-pointer');
  }, []);

  const handlePointerOut = useCallback(() => {
    setHovered(false);
    document.body.classList.remove('cursor-pointer');
  }, []);

  // Extract airline code from callsign for model lookup
  const airlineCode = useMemo(
    () => extractAirlineCode(flight.callsign) ?? undefined,
    [flight.callsign]
  );

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
      onPointerOver={handlePointerOver}
      onPointerOut={handlePointerOut}
    >
      {/* Aircraft model - Use GLTF model with Suspense fallback */}
      <GLTFAircraft
        modelConfig={modelConfig}
        airline={airline}
        selected={selected}
      />

      {/* Selection ring - visible indicator when aircraft is selected */}
      {/* Ring sized for ~35m wingspan aircraft (inner 20, outer 25) */}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.5, 0]}>
          <ringGeometry args={[20, 25, 32]} />
          <meshBasicMaterial color={0x00ff00} transparent opacity={0.8} side={THREE.DoubleSide} />
        </mesh>
      )}

      {/* Pulsing selection indicator - outer ring */}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.3, 0]}>
          <ringGeometry args={[28, 30, 32]} />
          <meshBasicMaterial color={0x00ff00} transparent opacity={0.4} side={THREE.DoubleSide} />
        </mesh>
      )}

      {/* Label - shows on hover OR when selected */}
      {/* Position above aircraft (~15m height for narrow body) */}
      {(hovered || selected) && (
        <Html
          position={[0, 20, 0]}
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
