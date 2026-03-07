interface ProceduralAircraftProps {
  color: number;
  secondaryColor?: number;
  scale?: number;
}

/**
 * Procedural Aircraft Geometry
 *
 * Fallback 3D aircraft model built from basic Three.js primitives.
 * Used when GLTF models are not available.
 *
 * Base geometry is ~28 units wingspan, ~22 units length.
 * Default scale of 0.15 gives ~4 unit wingspan (realistic for scene).
 * Scene scale: terminal ~200 units wide, gates ~64 units apart.
 */
export function ProceduralAircraft({
  color,
  secondaryColor = 0x555555,
  scale = 0.15,
}: ProceduralAircraftProps) {
  return (
    <group scale={[scale, scale, scale]}>
      {/* Aircraft fuselage - elongated cylinder */}
      <mesh castShadow rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[2, 2, 18, 12]} />
        <meshStandardMaterial
          color={color}
          metalness={0.3}
          roughness={0.7}
        />
      </mesh>

      {/* Nose cone */}
      <mesh castShadow position={[0, 0, -10]} rotation={[Math.PI / 2, 0, 0]}>
        <coneGeometry args={[2, 4, 12]} />
        <meshStandardMaterial color={color} metalness={0.3} roughness={0.7} />
      </mesh>

      {/* Tail cone */}
      <mesh castShadow position={[0, 0.5, 8]} rotation={[-Math.PI / 2, 0, 0]}>
        <coneGeometry args={[2, 5, 12]} />
        <meshStandardMaterial color={color} metalness={0.3} roughness={0.7} />
      </mesh>

      {/* Main wings - swept back */}
      <mesh position={[0, -0.5, 1]} castShadow>
        <boxGeometry args={[28, 0.5, 5]} />
        <meshStandardMaterial color={color} metalness={0.3} roughness={0.7} />
      </mesh>

      {/* Wing tips - angled up (winglets) */}
      <mesh position={[14.5, 1, 1]} rotation={[0, 0, Math.PI / 6]} castShadow>
        <boxGeometry args={[0.3, 3, 2]} />
        <meshStandardMaterial color={color} metalness={0.3} roughness={0.7} />
      </mesh>
      <mesh position={[-14.5, 1, 1]} rotation={[0, 0, -Math.PI / 6]} castShadow>
        <boxGeometry args={[0.3, 3, 2]} />
        <meshStandardMaterial color={color} metalness={0.3} roughness={0.7} />
      </mesh>

      {/* Horizontal stabilizer (tail wings) */}
      <mesh position={[0, 0.5, 9]} castShadow>
        <boxGeometry args={[10, 0.3, 3]} />
        <meshStandardMaterial color={color} metalness={0.3} roughness={0.7} />
      </mesh>

      {/* Vertical stabilizer (tail fin) - secondary color for livery */}
      <mesh position={[0, 4, 8]} castShadow>
        <boxGeometry args={[0.3, 7, 4]} />
        <meshStandardMaterial color={secondaryColor} metalness={0.3} roughness={0.7} />
      </mesh>

      {/* Engines - left */}
      <mesh position={[-6, -2, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow>
        <cylinderGeometry args={[1.2, 1.5, 4, 8]} />
        <meshStandardMaterial color={0x555555} metalness={0.5} roughness={0.5} />
      </mesh>

      {/* Engines - right */}
      <mesh position={[6, -2, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow>
        <cylinderGeometry args={[1.2, 1.5, 4, 8]} />
        <meshStandardMaterial color={0x555555} metalness={0.5} roughness={0.5} />
      </mesh>

      {/* Cockpit windows - dark glass effect */}
      <mesh position={[0, 1, -8]} rotation={[Math.PI / 4, 0, 0]}>
        <planeGeometry args={[2.5, 1.5]} />
        <meshStandardMaterial color={0x111122} metalness={0.8} roughness={0.2} />
      </mesh>
    </group>
  );
}
