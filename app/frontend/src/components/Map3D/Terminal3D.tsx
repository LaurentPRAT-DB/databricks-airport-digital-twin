/**
 * Terminal3D Component
 *
 * Renders OSM terminal buildings in 3D using geoPolygon coordinates
 * converted via latLonTo3D for correct alignment with aircraft positions.
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import { OSMTerminal } from '../../types/airportFormats';
import { latLonTo3D } from '../../utils/map3d-calculations';

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
  const { dimensions, color } = terminal;

  // Convert geo coordinates to 3D scene coordinates
  const { geometry, centerPos } = useMemo(() => {
    const geoPolygon = terminal.geoPolygon;
    const geo = terminal.geo;

    if (geoPolygon && geoPolygon.length >= 3 && geo) {
      // Use geo coordinates converted through latLonTo3D for consistent positioning
      const center3D = latLonTo3D(geo.latitude, geo.longitude, 0, airportCenter?.lat, airportCenter?.lon);
      const points3D = geoPolygon.map(pt =>
        latLonTo3D(pt.latitude, pt.longitude, 0, airportCenter?.lat, airportCenter?.lon)
      );

      const shape = new THREE.Shape();
      shape.moveTo(points3D[0].x - center3D.x, points3D[0].z - center3D.z);
      for (let i = 1; i < points3D.length; i++) {
        shape.lineTo(points3D[i].x - center3D.x, points3D[i].z - center3D.z);
      }
      shape.closePath();

      const extrudeSettings = {
        steps: 1,
        depth: dimensions.height,
        bevelEnabled: false,
      };

      return {
        geometry: new THREE.ExtrudeGeometry(shape, extrudeSettings),
        centerPos: [center3D.x, 0, center3D.z] as [number, number, number],
      };
    }

    // Fallback: use backend-computed polygon coordinates
    const { position, polygon } = terminal;
    if (polygon && polygon.length >= 3) {
      const shape = new THREE.Shape();
      shape.moveTo(polygon[0].x - position.x, polygon[0].z - position.z);
      for (let i = 1; i < polygon.length; i++) {
        shape.lineTo(polygon[i].x - position.x, polygon[i].z - position.z);
      }
      shape.closePath();

      const extrudeSettings = {
        steps: 1,
        depth: dimensions.height,
        bevelEnabled: false,
      };

      return {
        geometry: new THREE.ExtrudeGeometry(shape, extrudeSettings),
        centerPos: [position.x, 0, position.z] as [number, number, number],
      };
    }

    // Last fallback: simple box
    return {
      geometry: new THREE.BoxGeometry(dimensions.width, dimensions.height, dimensions.depth),
      centerPos: [terminal.position.x, dimensions.height / 2, terminal.position.z] as [number, number, number],
    };
  }, [terminal, dimensions, airportCenter?.lat, airportCenter?.lon]);

  // Determine if this is extruded (needs rotation) or a box
  const isExtruded = (terminal.geoPolygon && terminal.geoPolygon.length >= 3) ||
    (terminal.polygon && terminal.polygon.length >= 3);

  const rotation: [number, number, number] = isExtruded
    ? [-Math.PI / 2, 0, 0]
    : [0, 0, 0];

  return (
    <mesh
      position={centerPos}
      rotation={rotation}
      castShadow
      receiveShadow
    >
      <primitive object={geometry} />
      <meshStandardMaterial
        color={color}
        side={THREE.DoubleSide}
        flatShading
      />
    </mesh>
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
