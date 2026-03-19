import { useMemo, Suspense, Component, ReactNode } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { AircraftModelConfig, AirlineConfig, AIRCRAFT_MODELS } from '../../config/aircraftModels';

// Draco decoder path - drei's useGLTF automatically uses this when models are Draco-compressed
// The decoder is loaded on-demand when a Draco-compressed model is detected
const DRACO_DECODER_PATH = 'https://www.gstatic.com/draco/versioned/decoders/1.5.6/';

type FlightPhase = 'ground' | 'climbing' | 'descending' | 'cruising';

// Phase-based emissive tints to distinguish flight state in 3D
const PHASE_EMISSIVE: Record<FlightPhase, number> = {
  ground: 0x003300,     // Green tint
  descending: 0x332200, // Orange tint
  climbing: 0x001133,   // Blue tint
  cruising: 0x111111,   // Subtle white
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
