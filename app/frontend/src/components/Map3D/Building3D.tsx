import { useMemo, Suspense } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import {
  BuildingPlacement,
  BuildingType,
  BUILDING_MODELS,
  BUILDING_COLORS,
  BUILDING_DIMENSIONS,
} from '../../config/buildingModels';

interface Building3DProps {
  placement: BuildingPlacement;
}

/**
 * Building3D Component
 *
 * Renders a 3D building at the specified position.
 * Uses procedural geometry by default, can load GLTF models when available.
 */
export function Building3D({ placement }: Building3DProps) {
  // Use procedural buildings for now (set to true when GLTF models are added)
  const useGLTFModels = false;

  if (useGLTFModels) {
    return (
      <Suspense fallback={<ProceduralBuilding placement={placement} />}>
        <GLTFBuildingInner placement={placement} />
      </Suspense>
    );
  }

  return <ProceduralBuilding placement={placement} />;
}

/**
 * GLTF Building Model Loader
 */
function GLTFBuildingInner({
  placement,
}: {
  placement: BuildingPlacement;
}) {
  const modelConfig = BUILDING_MODELS[placement.type];
  const { scene } = useGLTF(modelConfig.url);

  // Clone scene for unique materials per instance
  const clonedScene = useMemo(() => {
    const clone = scene.clone(true);

    // Apply materials
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const material = (child.material as THREE.MeshStandardMaterial).clone();
        child.material = material;
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });

    return clone;
  }, [scene]);

  const scale = placement.scale ?? modelConfig.scale;
  const { rotationOffset } = modelConfig;

  return (
    <group
      position={[placement.position.x, placement.position.y, placement.position.z]}
      rotation={[0, placement.rotation, 0]}
    >
      <primitive
        object={clonedScene}
        scale={scale}
        rotation={[rotationOffset.x, rotationOffset.y, rotationOffset.z]}
      />
    </group>
  );
}

/**
 * Procedural Building Fallback
 *
 * Generates simple 3D geometry when GLTF model is not available.
 */
function ProceduralBuilding({ placement }: { placement: BuildingPlacement }) {
  const dimensions = BUILDING_DIMENSIONS[placement.type];
  const color = placement.color ?? BUILDING_COLORS[placement.type];

  const position: [number, number, number] = [
    placement.position.x,
    placement.position.y + dimensions.height / 2,
    placement.position.z,
  ];

  // Render different shapes based on building type
  switch (placement.type) {
    case 'control-tower':
      return <ControlTowerProcedural placement={placement} />;
    case 'hangar':
      return <HangarProcedural placement={placement} />;
    case 'jetbridge':
      return <JetbridgeProcedural placement={placement} />;
    default:
      return (
        <mesh
          position={position}
          rotation={[0, placement.rotation, 0]}
          castShadow
          receiveShadow
        >
          <boxGeometry args={[dimensions.width, dimensions.height, dimensions.depth]} />
          <meshStandardMaterial color={color} />
        </mesh>
      );
  }
}

/**
 * Procedural Control Tower
 * Base + Tower cylinder + Observation deck
 */
function ControlTowerProcedural({ placement }: { placement: BuildingPlacement }) {
  const color = placement.color ?? BUILDING_COLORS['control-tower'];
  const { x, y, z } = placement.position;

  return (
    <group position={[x, y, z]} rotation={[0, placement.rotation, 0]}>
      {/* Base building */}
      <mesh position={[0, 5, 0]} castShadow receiveShadow>
        <boxGeometry args={[20, 10, 20]} />
        <meshStandardMaterial color={0x808080} />
      </mesh>

      {/* Tower shaft */}
      <mesh position={[0, 30, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[5, 6, 40, 16]} />
        <meshStandardMaterial color={color} />
      </mesh>

      {/* Observation deck */}
      <mesh position={[0, 52, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[10, 8, 6, 16]} />
        <meshStandardMaterial color={0x333366} metalness={0.5} />
      </mesh>

      {/* Top dome/antenna */}
      <mesh position={[0, 58, 0]} castShadow>
        <coneGeometry args={[3, 8, 8]} />
        <meshStandardMaterial color={0xff0000} />
      </mesh>
    </group>
  );
}

/**
 * Procedural Hangar
 * Arched roof structure
 */
function HangarProcedural({ placement }: { placement: BuildingPlacement }) {
  const color = placement.color ?? BUILDING_COLORS['hangar'];
  const { x, y, z } = placement.position;
  const dimensions = BUILDING_DIMENSIONS['hangar'];

  return (
    <group position={[x, y, z]} rotation={[0, placement.rotation, 0]}>
      {/* Main structure */}
      <mesh position={[0, dimensions.height / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[dimensions.width, dimensions.height, dimensions.depth]} />
        <meshStandardMaterial color={color} metalness={0.4} />
      </mesh>

      {/* Curved roof (approximated with stretched cylinder) */}
      <mesh
        position={[0, dimensions.height + 5, 0]}
        rotation={[Math.PI / 2, 0, 0]}
        castShadow
        receiveShadow
      >
        <cylinderGeometry args={[dimensions.width / 2, dimensions.width / 2, dimensions.depth, 16, 1, false, 0, Math.PI]} />
        <meshStandardMaterial color={color} side={THREE.DoubleSide} metalness={0.6} />
      </mesh>

      {/* Large door markings */}
      <mesh position={[0, dimensions.height / 2, dimensions.depth / 2 + 0.1]} castShadow>
        <planeGeometry args={[dimensions.width * 0.8, dimensions.height * 0.9]} />
        <meshStandardMaterial color={0x444444} />
      </mesh>
    </group>
  );
}

/**
 * Procedural Jetbridge
 * Accordion-style corridor
 */
function JetbridgeProcedural({ placement }: { placement: BuildingPlacement }) {
  const color = placement.color ?? BUILDING_COLORS['jetbridge'];
  const { x, y, z } = placement.position;

  return (
    <group position={[x, y + 4, z]} rotation={[0, placement.rotation, 0]}>
      {/* Main corridor */}
      <mesh position={[0, 0, 0]} castShadow receiveShadow>
        <boxGeometry args={[4, 3.5, 25]} />
        <meshStandardMaterial color={color} />
      </mesh>

      {/* Accordion joints */}
      {[-8, 0, 8].map((offset, i) => (
        <mesh key={i} position={[0, 0, offset]} castShadow>
          <boxGeometry args={[4.5, 4, 2]} />
          <meshStandardMaterial color={0x404040} />
        </mesh>
      ))}

      {/* Aircraft end (rotunda) */}
      <mesh position={[0, 0, 14]} rotation={[Math.PI / 2, 0, 0]} castShadow>
        <cylinderGeometry args={[2.5, 2.5, 4, 8]} />
        <meshStandardMaterial color={color} />
      </mesh>
    </group>
  );
}

/**
 * Preload building models for better performance
 */
export function preloadBuildingModels(types: BuildingType[]) {
  types.forEach((type) => {
    const config = BUILDING_MODELS[type];
    try {
      useGLTF.preload(config.url);
    } catch {
      // Model doesn't exist, skip preload
    }
  });
}
