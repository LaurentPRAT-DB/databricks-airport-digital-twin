import { useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import * as THREE from 'three';
import { AirportScene } from './AirportScene';
import { AIRPORT_3D_CONFIG } from '../../constants/airport3D';
import { Flight } from '../../types/flight';
import { useAirportConfig } from '../../hooks/useAirportConfig';
import { latLonTo3D } from '../../utils/map3d-calculations';

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
  const { getTerminals, getAirportCenter, getTaxiways: getOSMTaxiwaysHook, getAprons, getOSMRunways } = useAirportConfig();
  const terminals = getTerminals();
  const airportCenter = getAirportCenter();
  const osmTaxiways = getOSMTaxiwaysHook();
  const osmAprons = getAprons();
  const osmRunways = getOSMRunways();

  // Compute camera position to frame the airport infrastructure
  // Uses OSM element geo-centers to find the bounding box, then positions
  // the camera for an aerial overview.
  const { cameraPosition, cameraTarget, farPlane } = useMemo(() => {
    const allGeoPoints: { lat: number; lon: number }[] = [];

    // Collect geo-centers from all OSM elements
    terminals?.forEach(t => {
      if (t.geo) allGeoPoints.push({ lat: t.geo.latitude, lon: t.geo.longitude });
    });
    osmRunways?.forEach(r => {
      r.geoPoints?.forEach(p => allGeoPoints.push({ lat: p.latitude, lon: p.longitude }));
    });
    osmTaxiways?.forEach(t => {
      t.geoPoints?.forEach(p => allGeoPoints.push({ lat: p.latitude, lon: p.longitude }));
    });
    osmAprons?.forEach(a => {
      if (a.geo) allGeoPoints.push({ lat: a.geo.latitude, lon: a.geo.longitude });
    });

    if (allGeoPoints.length === 0) {
      // No OSM data — use default camera for hardcoded scene
      return {
        cameraPosition: [0, 300, 200] as [number, number, number],
        cameraTarget: [0, 0, 0] as [number, number, number],
        farPlane: 5000,
      };
    }

    // Convert all geo points to 3D and find bounds
    const points3D = allGeoPoints.map(p =>
      latLonTo3D(p.lat, p.lon, 0, airportCenter?.lat, airportCenter?.lon)
    );

    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
    for (const p of points3D) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.z < minZ) minZ = p.z;
      if (p.z > maxZ) maxZ = p.z;
    }

    const cx = (minX + maxX) / 2;
    const cz = (minZ + maxZ) / 2;
    const width = maxX - minX;
    const depth = maxZ - minZ;
    const extent = Math.max(width, depth, 100); // minimum 100 units

    // Position camera for aerial overview: high enough to see entire airport,
    // offset slightly south (positive Z) for perspective depth
    const camY = extent * 0.8;
    const camZ = cz + extent * 0.5;

    return {
      cameraPosition: [cx, camY, camZ] as [number, number, number],
      cameraTarget: [cx, 0, cz] as [number, number, number],
      farPlane: Math.max(extent * 10, 5000),
    };
  }, [terminals, osmRunways, osmTaxiways, osmAprons, airportCenter?.lat, airportCenter?.lon]);

  return (
    <div className={className} style={{ width: '100%', height: '100%' }}>
      <Canvas
        shadows={{ type: THREE.PCFShadowMap }}
        gl={{ antialias: true }}
      >
        {/* Camera auto-positioned to frame the airport infrastructure */}
        <PerspectiveCamera
          makeDefault
          position={cameraPosition}
          fov={60}
          near={0.5}
          far={farPlane}
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
          airportCenter={airportCenter}
          osmTaxiways={osmTaxiways}
          osmAprons={osmAprons}
          osmRunways={osmRunways}
        />

        {/* Orbit controls for user interaction */}
        <OrbitControls
          enablePan={true}
          enableZoom={true}
          enableRotate={true}
          maxPolarAngle={Math.PI / 2.1} // Prevent camera from going below ground
          minDistance={10}
          maxDistance={3000}
          target={cameraTarget}
        />
      </Canvas>
    </div>
  );
}
