import { useMemo, Suspense, Component, ReactNode } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { AircraftModelConfig, AirlineConfig, AIRCRAFT_MODELS } from '../../config/aircraftModels';

// Draco decoder path - drei's useGLTF automatically uses this when models are Draco-compressed
// The decoder is loaded on-demand when a Draco-compressed model is detected
const DRACO_DECODER_PATH = 'https://www.gstatic.com/draco/versioned/decoders/1.5.6/';

type FlightPhase = string;

// Phase-based emissive tints to distinguish flight state in 3D
const PHASE_EMISSIVE: Record<string, number> = {
  // Ground phases (green tint)
  parked: 0x003300,
  pushback: 0x003300,
  taxi_out: 0x003300,
  taxi_in: 0x003300,
  // Departure phases (blue tint)
  takeoff: 0x001133,
  departing: 0x001133,
  // Arrival phases (orange tint)
  approaching: 0x332200,
  landing: 0x332200,
  // Cruise
  enroute: 0x111111,
  // Legacy
  ground: 0x003300,
  climbing: 0x001133,
  descending: 0x332200,
  cruising: 0x111111,
};

interface GLTFAircraftProps {
  modelConfig: AircraftModelConfig;
  airline: AirlineConfig;
  selected?: boolean;
  flightPhase?: FlightPhase;
}

/**
 * Error Boundary for catching GLTF loading errors
 */
interface ErrorBoundaryState {
  hasError: boolean;
}

class GLTFErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: ReactNode; fallback: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

/**
 * GLTF Aircraft Model Loader
 *
 * Loads external GLB/GLTF aircraft models with airline livery colors.
 * Clones the scene to allow multiple instances with different materials.
 * Supports Draco-compressed models for faster loading.
 */
function GLTFAircraftInner({ modelConfig, airline, selected = false, flightPhase }: GLTFAircraftProps) {
  // useGLTF with Draco decoder path - drei handles Draco decompression automatically
  const { scene } = useGLTF(modelConfig.url, DRACO_DECODER_PATH);

  // Clone scene for unique materials per instance
  const clonedScene = useMemo(() => {
    const clone = scene.clone(true);

    // If nodePrefix is set, hide non-matching top-level nodes and auto-center
    if (modelConfig.nodePrefix) {
      const box = new THREE.Box3();
      clone.traverse((child) => {
        // Find the GLTF_SceneRootNode level — its children are the individual models
        if (child.children && child.children.length > 5) {
          for (const grandchild of child.children) {
            if (grandchild.name && !grandchild.name.startsWith(modelConfig.nodePrefix!)) {
              grandchild.visible = false;
            }
          }
        }
      });
      // Compute bounding box of visible geometry and re-center
      clone.traverse((child) => {
        if (child instanceof THREE.Mesh && child.visible && child.geometry) {
          // Walk parents to check visibility
          let node: THREE.Object3D | null = child;
          let allVisible = true;
          while (node) {
            if (!node.visible) { allVisible = false; break; }
            node = node.parent;
          }
          if (allVisible) {
            child.geometry.computeBoundingBox();
            if (child.geometry.boundingBox) {
              box.expandByObject(child);
            }
          }
        }
      });
      if (!box.isEmpty()) {
        const center = new THREE.Vector3();
        box.getCenter(center);
        // Offset all visible geometry so the jet is centered at origin
        clone.traverse((child) => {
          if (child.children && child.children.length > 5) {
            for (const grandchild of child.children) {
              if (grandchild.visible) {
                grandchild.position.x -= center.x;
                grandchild.position.y -= center.y;
                grandchild.position.z -= center.z;
              }
            }
          }
        });
      }
    }

    // Apply airline colors to materials
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        // Clone material to avoid affecting other instances
        const material = (child.material as THREE.MeshStandardMaterial).clone();

        // Determine which color to apply based on mesh name
        const meshName = child.name.toLowerCase();

        // Set reasonable PBR defaults for all meshes
        material.roughness = 0.5;
        material.metalness = 0.2;

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
          material.roughness = 0.1;
        } else {
          // Default to primary color — ensure minimum brightness
          const color = new THREE.Color(airline.primaryColor);
          const luminance = 0.299 * color.r + 0.587 * color.g + 0.114 * color.b;
          if (luminance < 0.15) {
            // Brighten very dark colors to stay visible
            color.lerp(new THREE.Color(0xffffff), 0.3);
          }
          material.color.copy(color);
        }

        // Add selection glow or phase-based emissive tint
        if (selected) {
          material.emissive = new THREE.Color(0x002200);
          material.emissiveIntensity = 0.3;
        } else if (flightPhase && PHASE_EMISSIVE[flightPhase]) {
          material.emissive = new THREE.Color(PHASE_EMISSIVE[flightPhase]);
          material.emissiveIntensity = 0.4;
        }

        child.material = material;
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });

    return clone;
  }, [scene, airline, selected, flightPhase]);

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
 * Fallback aircraft using generic-jet.glb when primary model fails to load
 */
function FallbackAircraft({ airline, selected = false, flightPhase }: Omit<GLTFAircraftProps, 'modelConfig'>) {
  const defaultConfig = AIRCRAFT_MODELS['DEFAULT'];
  return (
    <GLTFAircraftInner
      modelConfig={defaultConfig}
      airline={airline}
      selected={selected}
      flightPhase={flightPhase}
    />
  );
}

/**
 * Simple loading placeholder (minimal geometry while model loads)
 */
function LoadingPlaceholder() {
  return (
    <mesh>
      <boxGeometry args={[0.9, 0.3, 1.35]} />
      <meshBasicMaterial color={0x666666} transparent opacity={0.3} />
    </mesh>
  );
}

/**
 * Wrapper with Suspense and ErrorBoundary for graceful fallback
 * Uses generic-jet.glb as fallback instead of procedural geometry
 */
export function GLTFAircraft(props: GLTFAircraftProps) {
  // Check if we're already using the DEFAULT model to avoid infinite recursion
  const isDefaultModel = props.modelConfig.url === AIRCRAFT_MODELS['DEFAULT'].url;

  // If already using default model, use simple placeholder as final fallback
  if (isDefaultModel) {
    return (
      <Suspense fallback={<LoadingPlaceholder />}>
        <GLTFAircraftInner {...props} />
      </Suspense>
    );
  }

  // For non-default models, use generic-jet.glb as fallback
  const fallbackAircraft = (
    <Suspense fallback={<LoadingPlaceholder />}>
      <FallbackAircraft airline={props.airline} selected={props.selected} flightPhase={props.flightPhase} />
    </Suspense>
  );

  return (
    <GLTFErrorBoundary fallback={fallbackAircraft}>
      <Suspense fallback={<LoadingPlaceholder />}>
        <GLTFAircraftInner {...props} />
      </Suspense>
    </GLTFErrorBoundary>
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
