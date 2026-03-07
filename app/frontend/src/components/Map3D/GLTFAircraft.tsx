import { useMemo, Suspense } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { AircraftModelConfig, AirlineConfig } from '../../config/aircraftModels';

interface GLTFAircraftProps {
  modelConfig: AircraftModelConfig;
  airline: AirlineConfig;
  selected?: boolean;
}

/**
 * GLTF Aircraft Model Loader
 *
 * Loads external GLB/GLTF aircraft models with airline livery colors.
 * Clones the scene to allow multiple instances with different materials.
 */
function GLTFAircraftInner({ modelConfig, airline, selected = false }: GLTFAircraftProps) {
  const { scene } = useGLTF(modelConfig.url);

  // Clone scene for unique materials per instance
  const clonedScene = useMemo(() => {
    const clone = scene.clone(true);

    // Apply airline colors to materials
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        // Clone material to avoid affecting other instances
        const material = (child.material as THREE.MeshStandardMaterial).clone();

        // Determine which color to apply based on mesh name
        const meshName = child.name.toLowerCase();

        if (meshName.includes('tail') || meshName.includes('fin') || meshName.includes('logo')) {
          // Tail/fin gets secondary color (where logos usually are)
          material.color.setHex(airline.secondaryColor);
        } else if (meshName.includes('fuselage') || meshName.includes('body')) {
          // Main body gets primary color
          material.color.setHex(airline.primaryColor);
        } else if (meshName.includes('engine') || meshName.includes('wheel') || meshName.includes('gear')) {
          // Keep engines/landing gear metallic gray
          material.color.setHex(0x555555);
          material.metalness = 0.6;
        } else if (meshName.includes('window') || meshName.includes('cockpit')) {
          // Windows stay dark
          material.color.setHex(0x111133);
          material.metalness = 0.8;
        } else {
          // Default to primary color
          material.color.setHex(airline.primaryColor);
        }

        // Add selection glow
        if (selected) {
          material.emissive = new THREE.Color(0x002200);
          material.emissiveIntensity = 0.3;
        }

        child.material = material;
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });

    return clone;
  }, [scene, airline, selected]);

  const { scale, rotationOffset } = modelConfig;

  return (
    <primitive
      object={clonedScene}
      scale={scale}
      rotation={[rotationOffset.x, rotationOffset.y, rotationOffset.z]}
    />
  );
}

/**
 * Wrapper with Suspense for loading state
 */
export function GLTFAircraft(props: GLTFAircraftProps) {
  return (
    <Suspense fallback={null}>
      <GLTFAircraftInner {...props} />
    </Suspense>
  );
}

/**
 * Preload models for better performance
 * Call this early in app lifecycle
 */
export function preloadAircraftModels(urls: string[]) {
  urls.forEach((url) => {
    try {
      useGLTF.preload(url);
    } catch {
      // Model doesn't exist, skip preload
    }
  });
}
