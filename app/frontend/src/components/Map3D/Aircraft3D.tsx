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
  calculatePitch,
  calculateBank,
  normalizeAngleDiffDeg,
} from '../../utils/map3d-calculations';
import { isGroundPhase as isGroundPhaseFn } from '../../utils/phaseUtils';

// Re-export for backwards compatibility
export { latLonTo3D };

// Reusable Vector3 for lerp calculations (avoids GC pressure)
const _targetVec3 = new THREE.Vector3();

interface Aircraft3DProps {
  flight: Flight;
  selected?: boolean;
  onClick?: () => void;
  airportCenter?: { lat: number; lon: number };
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
export function Aircraft3D({ flight, selected = false, onClick, airportCenter }: Aircraft3DProps) {
  const groupRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);

  // Calculate target position from flight data
  // Ground-phase aircraft (taxi, parked, pushback) must stay at ground level —
  // their altitude field may contain airport elevation which would make them float.
  const isGroundPhase = isGroundPhaseFn(flight.flight_phase);
  const effectiveAltitude = isGroundPhase ? 0 : (flight.altitude ?? 0);
  const targetPosition = useMemo(() =>
    latLonTo3D(flight.latitude, flight.longitude, effectiveAltitude, airportCenter?.lat, airportCenter?.lon),
    [flight.latitude, flight.longitude, effectiveAltitude, airportCenter?.lat, airportCenter?.lon]
  );

  // Calculate target rotation from heading
  const targetRotation = useMemo(() => headingToRotation(flight.heading), [flight.heading]);

  // Animation refs for smooth interpolation
  // Store current interpolated values to animate toward targets
  const currentPosition = useRef(new THREE.Vector3(targetPosition.x, targetPosition.y, targetPosition.z));
  const currentRotation = useRef(targetRotation);
  const currentPitch = useRef(0);
  const currentBank = useRef(0);
  const prevHeadingRef = useRef(flight.heading || 0);
  const turnRateRef = useRef(0);

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

    // Lerp yaw toward target with angle wrapping
    const adjustedDiff = normalizeRotationDiff(currentRotation.current, targetRotation);
    currentRotation.current += adjustedDiff * lerpFactor;

    // Compute turn rate from heading changes (smoothed)
    const headingDeg = flight.heading || 0;
    if (delta > 0) {
      const headingDelta = normalizeAngleDiffDeg(headingDeg - prevHeadingRef.current);
      const instantTurnRate = headingDelta / delta;
      // Smooth turn rate to avoid spikes from noisy data
      turnRateRef.current += (instantTurnRate - turnRateRef.current) * Math.min(lerpFactor, 0.3);
    }
    prevHeadingRef.current = headingDeg;

    // Derive pitch and bank (zero for ground phases)
    let targetPitch = 0;
    let targetBank = 0;
    if (!isGroundPhase) {
      targetPitch = calculatePitch(flight.vertical_rate, flight.velocity);
      targetBank = calculateBank(turnRateRef.current, flight.velocity);
    }

    // Lerp pitch and bank
    currentPitch.current += (targetPitch - currentPitch.current) * lerpFactor;
    currentBank.current += (targetBank - currentBank.current) * lerpFactor;

    // Apply position and full rotation (YXZ: yaw first, then pitch, then roll)
    groupRef.current.position.copy(currentPosition.current);
    groupRef.current.rotation.order = 'YXZ';
    groupRef.current.rotation.set(currentPitch.current, currentRotation.current, currentBank.current);
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
      renderOrder={10}
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
        flightPhase={flight.flight_phase}
      />

      {/* Selection ring - scaled to match aircraft in scene coordinates */}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]} renderOrder={10}>
          <ringGeometry args={[1.8, 2.2, 32]} />
          <meshBasicMaterial color={0x00ff00} transparent opacity={0.8} side={THREE.DoubleSide} depthTest={false} />
        </mesh>
      )}

      {/* Pulsing selection indicator - outer ring */}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]} renderOrder={10}>
          <ringGeometry args={[2.5, 2.7, 32]} />
          <meshBasicMaterial color={0x00ff00} transparent opacity={0.4} side={THREE.DoubleSide} depthTest={false} />
        </mesh>
      )}

      {/* Label - shows on hover OR when selected, offset by altitude for separation */}
      {(hovered || selected) && (
        <Html
          position={[0, 2 + Math.min(effectiveAltitude * 0.0001, 3), 0]}
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
