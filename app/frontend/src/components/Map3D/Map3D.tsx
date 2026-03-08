import { Canvas } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import * as THREE from 'three';
import { AirportScene } from './AirportScene';
import { AIRPORT_3D_CONFIG } from '../../constants/airport3D';
import { Flight } from '../../types/flight';
import { useAirportConfig } from '../../hooks/useAirportConfig';

interface Map3DProps {
  className?: string;
  flights?: Flight[];
  selectedFlight?: string | null;
  onSelectFlight?: (icao24: string) => void;
}

/**
 * Map3D Component
 *
 * Main 3D visualization container that renders the airport scene
 * using React Three Fiber. Provides:
 * - Camera with perspective view of the airport
 * - Orbit controls for pan, zoom, and rotate
 * - Ambient and directional lighting
 * - The complete airport scene (terminal, runways, taxiways)
 */
export function Map3D({
  className,
  flights = [],
  selectedFlight = null,
  onSelectFlight,
}: Map3DProps) {
  const { lighting } = AIRPORT_3D_CONFIG;
  const { getTerminals } = useAirportConfig();
  const terminals = getTerminals();

  return (
    <div className={className} style={{ width: '100%', height: '100%' }}>
      <Canvas
        shadows={{ type: THREE.PCFShadowMap }}
        gl={{ antialias: true }}
      >
        {/* Camera positioned above and behind the airport for overview */}
        <PerspectiveCamera
          makeDefault
          position={[0, 300, 500]}
          fov={60}
          near={1}
          far={5000}
        />

        {/* Ambient light for base illumination */}
        <ambientLight intensity={lighting.ambient.intensity} />

        {/* Directional light for shadows and depth */}
        <directionalLight
          position={[
            lighting.directional.position.x,
            lighting.directional.position.y,
            lighting.directional.position.z,
          ]}
          intensity={lighting.directional.intensity}
          castShadow
          shadow-mapSize-width={2048}
          shadow-mapSize-height={2048}
          shadow-camera-far={1000}
          shadow-camera-left={-500}
          shadow-camera-right={500}
          shadow-camera-top={500}
          shadow-camera-bottom={-500}
        />

        {/* Airport scene with all 3D elements */}
        <AirportScene
          flights={flights}
          selectedFlight={selectedFlight}
          onSelectFlight={onSelectFlight}
          terminals={terminals}
        />

        {/* Orbit controls for user interaction */}
        <OrbitControls
          enablePan={true}
          enableZoom={true}
          enableRotate={true}
          maxPolarAngle={Math.PI / 2.1} // Prevent camera from going below ground
          minDistance={50}
          maxDistance={1500}
          target={[0, 0, 0]} // Look at the center of the scene
        />
      </Canvas>
    </div>
  );
}
