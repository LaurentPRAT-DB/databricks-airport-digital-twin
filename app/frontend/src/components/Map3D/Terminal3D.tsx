/**
 * Terminal3D Component
 *
 * Renders OSM terminal buildings in 3D using either polygon geometry
 * (if available) or a simple box fallback based on dimensions.
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import { OSMTerminal } from '../../types/airportFormats';

interface Terminal3DProps {
  terminal: OSMTerminal;
}

/**
 * Terminal3D Component
 *
 * Renders a terminal building from OSM data. If polygon points are available,
 * creates an extruded shape. Otherwise, renders a simple box.
 */
export function Terminal3D({ terminal }: Terminal3DProps) {
  const { position, dimensions, polygon, color } = terminal;

  // Create geometry from polygon points or fall back to box
  const geometry = useMemo(() => {
    if (polygon && polygon.length >= 3) {
      // Create a shape from the polygon points
      const shape = new THREE.Shape();
      const firstPoint = polygon[0];
      shape.moveTo(firstPoint.x - position.x, firstPoint.z - position.z);

      for (let i = 1; i < polygon.length; i++) {
        const pt = polygon[i];
        shape.lineTo(pt.x - position.x, pt.z - position.z);
      }
      shape.closePath();

      // Extrude to create 3D building
      const extrudeSettings = {
        steps: 1,
        depth: dimensions.height,
        bevelEnabled: false,
      };

      return new THREE.ExtrudeGeometry(shape, extrudeSettings);
    }

    // Fallback to simple box
    return new THREE.BoxGeometry(dimensions.width, dimensions.height, dimensions.depth);
  }, [polygon, position, dimensions]);

  // Rotation for extruded geometry (needs to be rotated to lie flat then stand up)
  const rotation = useMemo(() => {
    if (polygon && polygon.length >= 3) {
      // Extruded geometry needs rotation: -90 deg on X to stand up
      return [-Math.PI / 2, 0, 0] as [number, number, number];
    }
    return [0, 0, 0] as [number, number, number];
  }, [polygon]);

  // Position adjustment for extruded geometry
  const adjustedPosition = useMemo(() => {
    if (polygon && polygon.length >= 3) {
      return [position.x, 0, position.z] as [number, number, number];
    }
    // Box geometry: position at center, y offset by half height
    return [position.x, dimensions.height / 2, position.z] as [number, number, number];
  }, [polygon, position, dimensions.height]);

  return (
    <mesh
      position={adjustedPosition}
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
}

/**
 * TerminalGroup Component
 *
 * Renders a collection of OSM terminals.
 */
export function TerminalGroup({ terminals }: TerminalGroupProps) {
  if (!terminals || terminals.length === 0) {
    return null;
  }

  return (
    <group name="osm-terminals">
      {terminals.map((terminal) => (
        <Terminal3D key={terminal.id} terminal={terminal} />
      ))}
    </group>
  );
}
