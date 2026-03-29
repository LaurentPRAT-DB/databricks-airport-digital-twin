import { useMemo, useEffect, useState, useCallback, useRef } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import * as THREE from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { AirportScene } from './AirportScene';
import { NavigationControls3D } from './NavigationControls3D';
import { AIRPORT_3D_CONFIG } from '../../constants/airport3D';
import { Flight } from '../../types/flight';
import { useAirportConfigContext } from '../../context/AirportConfigContext';
import { latLonTo3D, position3DToLatLon } from '../../utils/map3d-calculations';
import { SharedViewport } from '../../hooks/useViewportState';
import { isGroundPhase } from '../../utils/phaseUtils';

interface Map3DProps {
  className?: string;
  flights?: Flight[];
  selectedFlight?: string | null;
  onSelectFlight?: (icao24: string) => void;
  sharedViewport?: SharedViewport | null;
  onViewportChange?: (vp: SharedViewport) => void;
  airportCenter?: { lat: number; lon: number };
  satellite?: boolean;
}

// ============================================================================
// Viewport conversion: Leaflet zoom ↔ 3D camera distance
// ============================================================================

/** Convert Leaflet zoom level to 3D camera distance from target */
function zoomToCameraDistance(zoom: number, extent: number): number {
  // zoom 13 ≈ extent distance; each zoom level halves the distance
  return extent * Math.pow(2, 13 - zoom);
}

/** Convert 3D camera distance to Leaflet zoom level */
function cameraDistanceToZoom(distance: number, extent: number): number {
  if (distance <= 0 || extent <= 0) return 13;
  const zoom = 13 - Math.log2(distance / extent);
  // Clamp to valid Leaflet zoom range
  return Math.max(1, Math.min(20, zoom));
}

/**
 * Inner component that syncs 3D camera with shared viewport.
 * Must live inside <Canvas> to access useThree().
 */
function CameraViewportSync({
  onViewportChange,
  airportCenter,
  extent,
}: {
  onViewportChange?: (vp: SharedViewport) => void;
  airportCenter: { lat: number; lon: number };
  extent: number;
}) {
  const { camera } = useThree();
  // Save camera state on unmount
  useEffect(() => {
    return () => {
      if (!onViewportChange) return;
      // Camera distance from the point it's looking at
      const target = new THREE.Vector3(0, 0, 0);
      // Try to get OrbitControls target from DOM (stored on the controls)
      const controlsEl = document.querySelector('canvas')?.parentElement;
      if (controlsEl) {
        // Use camera direction to estimate the target at y=0
        const dir = new THREE.Vector3();
        camera.getWorldDirection(dir);
        if (dir.y !== 0) {
          const t = -camera.position.y / dir.y;
          target.copy(camera.position).add(dir.multiplyScalar(t));
        }
      }

      // Convert 3D target position back to lat/lon
      const geo = position3DToLatLon(
        { x: target.x, y: 0, z: target.z },
        airportCenter.lat,
        airportCenter.lon
      );

      // Camera distance to target
      const distance = camera.position.distanceTo(target);
      const zoom = cameraDistanceToZoom(distance, extent);

      // Bearing from camera azimuth angle
      const dx = camera.position.x - target.x;
      const dz = camera.position.z - target.z;
      const bearing = (Math.atan2(dx, dz) * 180) / Math.PI;

      onViewportChange({
        center: { lat: geo.lat, lon: geo.lon },
        zoom,
        bearing,
      });
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onViewportChange, airportCenter.lat, airportCenter.lon, extent]);

  return null;
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
  sharedViewport,
  onViewportChange,
  airportCenter: airportCenterProp,
  satellite = false,
}: Map3DProps) {
  const { lighting } = AIRPORT_3D_CONFIG;
  const { isLoading, switchProgress, getTerminals, getAirportCenter, getTaxiways: getOSMTaxiwaysHook, getAprons, getOSMRunways } = useAirportConfigContext();
  const terminals = getTerminals();
  const airportCenter = airportCenterProp ?? getAirportCenter();
  const osmTaxiways = getOSMTaxiwaysHook();
  const osmAprons = getAprons();
  const osmRunways = getOSMRunways();

  // Find the selected flight object (for camera framing on 2D→3D switch)
  const selectedFlightObj = useMemo(
    () => selectedFlight ? flights.find(f => f.icao24 === selectedFlight) : undefined,
    [selectedFlight, flights]
  );

  // Compute camera position to frame the airport infrastructure.
  // Priority: selected flight > shared viewport > default airport view
  const { cameraPosition, cameraTarget, farPlane, computedExtent } = useMemo(() => {
    // First, compute the airport bounding box extent (needed for zoom conversion)
    const allGeoPoints: { lat: number; lon: number }[] = [];
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

    let extent = 100; // default minimum

    if (allGeoPoints.length > 0) {
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
      const width = maxX - minX;
      const depth = maxZ - minZ;
      extent = Math.max(width, depth, 100);
    }

    // ── Priority 1: Frame the selected flight ──
    if (selectedFlightObj) {
      const pos3D = latLonTo3D(
        selectedFlightObj.latitude,
        selectedFlightObj.longitude,
        selectedFlightObj.altitude,
        airportCenter?.lat,
        airportCenter?.lon
      );
      const isGround = isGroundPhase(selectedFlightObj.flight_phase);
      // Heading in degrees — position camera behind the aircraft
      const headingDeg = selectedFlightObj.heading ?? 0;
      const headingRad = (headingDeg * Math.PI) / 180;

      if (isGround) {
        // Close "ramp view": 40m back, 25m up, looking at the aircraft
        const camDist = 40;
        const camHeight = 25;
        // Camera behind the aircraft (opposite to heading direction)
        // Heading direction in scene: (+sin(h), 0, -cos(h)), so behind = (-sin(h), 0, +cos(h))
        const camX = pos3D.x - Math.sin(headingRad) * camDist;
        const camZ = pos3D.z + Math.cos(headingRad) * camDist;
        return {
          cameraPosition: [camX, pos3D.y + camHeight, camZ] as [number, number, number],
          cameraTarget: [pos3D.x, pos3D.y, pos3D.z] as [number, number, number],
          farPlane: Math.max(extent * 10, 5000),
          computedExtent: extent,
        };
      } else {
        // Airborne: farther back (150m), slightly above, to see trajectory
        const camDist = 150;
        const camHeight = 60;
        const camX = pos3D.x - Math.sin(headingRad) * camDist;
        const camZ = pos3D.z + Math.cos(headingRad) * camDist;
        return {
          cameraPosition: [camX, pos3D.y + camHeight, camZ] as [number, number, number],
          cameraTarget: [pos3D.x, pos3D.y, pos3D.z] as [number, number, number],
          farPlane: Math.max(extent * 10, 5000),
          computedExtent: extent,
        };
      }
    }

    // ── Priority 2: Shared viewport from 2D ──
    if (sharedViewport) {
      const target3D = latLonTo3D(
        sharedViewport.center.lat,
        sharedViewport.center.lon,
        0,
        airportCenter?.lat,
        airportCenter?.lon
      );
      const distance = zoomToCameraDistance(sharedViewport.zoom, extent);

      // Position camera above and south of target (aerial perspective)
      const bearingRad = (sharedViewport.bearing * Math.PI) / 180;
      const camY = distance * 0.6; // 60% of distance as height
      const horizontalDist = distance * 0.4; // 40% horizontal offset
      const camX = target3D.x + Math.sin(bearingRad) * horizontalDist;
      const camZ = target3D.z + Math.cos(bearingRad) * horizontalDist;

      return {
        cameraPosition: [camX, camY, camZ] as [number, number, number],
        cameraTarget: [target3D.x, 0, target3D.z] as [number, number, number],
        farPlane: Math.max(distance * 10, 5000),
        computedExtent: extent,
      };
    }

    // ── Priority 3: Default airport overview ──
    if (allGeoPoints.length === 0) {
      return {
        cameraPosition: [0, 300, 200] as [number, number, number],
        cameraTarget: [0, 0, 0] as [number, number, number],
        farPlane: 5000,
        computedExtent: extent,
      };
    }

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
    const camY = extent * 0.8;
    const camZ = cz + extent * 0.5;

    return {
      cameraPosition: [cx, camY, camZ] as [number, number, number],
      cameraTarget: [cx, 0, cz] as [number, number, number],
      farPlane: Math.max(extent * 10, 5000),
      computedExtent: extent,
    };
  }, [terminals, osmRunways, osmTaxiways, osmAprons, airportCenter?.lat, airportCenter?.lon, sharedViewport, selectedFlightObj]);

  // Ref to OrbitControls for programmatic camera manipulation
  const orbitControlsRef = useRef<OrbitControlsImpl | null>(null);

  // Navigation controls hint — auto-hides after 5s, reappears on hover
  const [hintVisible, setHintVisible] = useState(true);
  const hintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startHintTimer = useCallback(() => {
    if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
    hintTimerRef.current = setTimeout(() => setHintVisible(false), 5000);
  }, []);

  // Start the initial 5s timer on mount
  useEffect(() => {
    startHintTimer();
    return () => {
      if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
    };
  }, [startHintTimer]);

  const handleHintMouseEnter = useCallback(() => {
    setHintVisible(true);
    startHintTimer();
  }, [startHintTimer]);

  return (
    <div className={`relative ${className || ''}`} style={{ width: '100%', height: '100%' }}>
      <Canvas
        shadows={{ type: THREE.PCFShadowMap }}
        gl={{ antialias: true, preserveDrawingBuffer: true }}
      >
        {/* Camera auto-positioned to frame the airport infrastructure */}
        <PerspectiveCamera
          makeDefault
          position={cameraPosition}
          fov={60}
          near={0.5}
          far={farPlane}
        />

        {/* Sync viewport on unmount for 2D↔3D continuity */}
        <CameraViewportSync
          onViewportChange={onViewportChange}
          airportCenter={airportCenter}
          extent={computedExtent}
        />

        {/* Ambient light for base illumination */}
        <ambientLight intensity={lighting.ambient.intensity} />

        {/* Hemisphere light for natural sky/ground color blending */}
        <hemisphereLight args={[0x87ceeb, 0x228b22, 0.3]} />

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
          satellite={satellite}
        />

        {/* Orbit controls for user interaction */}
        <OrbitControls
          ref={orbitControlsRef}
          enablePan={true}
          enableZoom={true}
          enableRotate={true}
          maxPolarAngle={Math.PI / 2.1} // Prevent camera from going below ground
          minDistance={10}
          maxDistance={3000}
          target={cameraTarget}
        />
      </Canvas>

      {/* 3D navigation buttons */}
      <NavigationControls3D controlsRef={orbitControlsRef} />

      {/* Navigation controls hint */}
      <div
        className={`absolute bottom-3 left-3 bg-black/50 text-white/80 text-xs rounded px-3 py-2 pointer-events-auto transition-opacity duration-700 ${hintVisible ? 'opacity-100' : 'opacity-0'}`}
        onMouseEnter={handleHintMouseEnter}
      >
        Left-click drag: Rotate | Right-click drag: Pan | Scroll: Zoom
      </div>

      {/* Loading overlay during airport switch */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-10">
          <div className="flex flex-col items-center gap-3 bg-slate-800/90 rounded-xl px-8 py-6 shadow-2xl">
            <div className="w-10 h-10 rounded-full border-4 border-blue-400 border-t-transparent animate-spin" />
            <span className="text-white text-sm font-medium">
              {switchProgress?.message || 'Loading airport...'}
            </span>
            {switchProgress && !switchProgress.done && (
              <div className="w-48 h-1.5 bg-slate-600 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-400 rounded-full transition-all duration-300"
                  style={{ width: `${(switchProgress.step / switchProgress.total) * 100}%` }}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
