/**
 * Terminal3D Component
 *
 * Renders OSM terminal buildings in 3D using geoPolygon coordinates
 * converted via latLonTo3D for correct alignment with aircraft positions.
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import { OSMTerminal } from '../../types/airportFormats';
import { latLonTo3D, METERS_TO_SCENE_UNITS } from '../../utils/map3d-calculations';

const TERMINAL_COLOR = 0xC8BEB0; // Warm concrete beige
const GLASS_FLOOR_HEIGHT_M = 5;
const GLASS_COLOR = 0x87CEEB;
const GLASS_OPACITY = 0.15;

interface Terminal3DProps {
  terminal: OSMTerminal;
  airportCenter?: { lat: number; lon: number };
}

/**
 * Terminal3D Component
 *
 * Renders a terminal building from OSM data. Uses geoPolygon (lat/lon)
 * converted via latLonTo3D for correct coordinate alignment.
 * Falls back to backend-computed polygon if geoPolygon is unavailable.
 */
export function Terminal3D({ terminal, airportCenter }: Terminal3DProps) {
  const { dimensions } = terminal;

  // Build shape and center position from geo or fallback polygon
  const { shape, centerPos, isExtruded } = useMemo(() => {
    const geoPolygon = terminal.geoPolygon;
    const geo = terminal.geo;

    if (geoPolygon && geoPolygon.length >= 3 && geo) {
      const center3D = latLonTo3D(geo.latitude, geo.longitude, 0, airportCenter?.lat, airportCenter?.lon);
      const points3D = geoPolygon.map(pt =>
        latLonTo3D(pt.latitude, pt.longitude, 0, airportCenter?.lat, airportCenter?.lon)
      );

      const s = new THREE.Shape();
      s.moveTo(points3D[0].x - center3D.x, points3D[0].z - center3D.z);
      for (let i = 1; i < points3D.length; i++) {
        s.lineTo(points3D[i].x - center3D.x, points3D[i].z - center3D.z);
      }
      s.closePath();

      return {
        shape: s,
        centerPos: [center3D.x, 0, center3D.z] as [number, number, number],
        isExtruded: true,
      };
    }

    const { position, polygon } = terminal;
    if (polygon && polygon.length >= 3) {
      const s = new THREE.Shape();
      s.moveTo(polygon[0].x - position.x, polygon[0].z - position.z);
      for (let i = 1; i < polygon.length; i++) {
        s.lineTo(polygon[i].x - position.x, polygon[i].z - position.z);
      }
      s.closePath();

      return {
        shape: s,
        centerPos: [position.x, 0, position.z] as [number, number, number],
        isExtruded: true,
      };
    }

    return { shape: null, centerPos: [terminal.position.x, 0, terminal.position.z] as [number, number, number], isExtruded: false };
  }, [terminal, dimensions, airportCenter?.lat, airportCenter?.lon]);

  // Split into transparent ground floor + solid upper floors
  const glassHeight = Math.min(GLASS_FLOOR_HEIGHT_M, dimensions.height) * METERS_TO_SCENE_UNITS;
  const solidHeight = Math.max(0, (dimensions.height - GLASS_FLOOR_HEIGHT_M)) * METERS_TO_SCENE_UNITS;

  const rotation: [number, number, number] = isExtruded ? [-Math.PI / 2, 0, 0] : [0, 0, 0];

  if (!shape) {
    // Box fallback for terminals without polygon data
    return (
      <mesh
        position={[centerPos[0], dimensions.height * METERS_TO_SCENE_UNITS / 2, centerPos[2]]}
        castShadow
        receiveShadow
      >
        <boxGeometry args={[
          dimensions.width * METERS_TO_SCENE_UNITS,
          dimensions.height * METERS_TO_SCENE_UNITS,
          dimensions.depth * METERS_TO_SCENE_UNITS,
        ]} />
        <meshStandardMaterial color={TERMINAL_COLOR} side={THREE.DoubleSide} flatShading />
      </mesh>
    );
  }

  return (
    <group>
      {/* Ground floor — transparent glass so aircraft at gates are visible */}
      <mesh position={centerPos} rotation={rotation}>
        <extrudeGeometry args={[shape, { steps: 1, depth: glassHeight, bevelEnabled: false }]} />
        <meshStandardMaterial
          color={GLASS_COLOR}
          transparent
          opacity={GLASS_OPACITY}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      {/* Upper floors — solid opaque */}
      {solidHeight > 0 && (
        <mesh
          position={[centerPos[0], glassHeight, centerPos[2]]}
          rotation={rotation}
          castShadow
          receiveShadow
        >
          <extrudeGeometry args={[shape, { steps: 1, depth: solidHeight, bevelEnabled: false }]} />
          <meshStandardMaterial color={TERMINAL_COLOR} side={THREE.DoubleSide} flatShading />
        </mesh>
      )}
    </group>
  );
}

interface TerminalGroupProps {
  terminals: OSMTerminal[];
  airportCenter?: { lat: number; lon: number };
}

/**
 * TerminalGroup Component
 *
 * Renders a collection of OSM terminals.
 */
export function TerminalGroup({ terminals, airportCenter }: TerminalGroupProps) {
  if (!terminals || terminals.length === 0) {
    return null;
  }

  return (
    <group name="osm-terminals">
      {terminals.map((terminal) => (
        <Terminal3D key={terminal.id} terminal={terminal} airportCenter={airportCenter} />
      ))}
    </group>
  );
}
