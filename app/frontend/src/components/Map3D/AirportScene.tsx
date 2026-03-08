import { useMemo } from 'react';
import * as THREE from 'three';
import { AIRPORT_3D_CONFIG, RUNWAY_MARKING_COLOR } from '../../constants/airport3D';
import { Flight } from '../../types/flight';
import { OSMTerminal } from '../../types/airportFormats';
import { Aircraft3D } from './Aircraft3D';
import { Trajectory3D } from './Trajectory3D';
import { Building3D } from './Building3D';
import { TerminalGroup } from './Terminal3D';

interface AirportSceneProps {
  flights?: Flight[];
  selectedFlight?: string | null;
  onSelectFlight?: (icao24: string) => void;
  /** OSM terminal buildings to render */
  terminals?: OSMTerminal[];
}

/**
 * AirportScene Component
 *
 * Renders the 3D airport environment including:
 * - Ground plane (grass)
 * - Runways with center line markings (real SFO FAA data)
 * - Taxiways connecting runways to gate areas
 * - Buildings (control tower, hangars, etc.)
 * - Aircraft at their current positions
 *
 * Note: Terminal buildings are not rendered as placeholders.
 * Real terminal geometry can be imported via OSM or IFC.
 */
export function AirportScene({
  flights = [],
  selectedFlight = null,
  onSelectFlight,
  terminals = [],
}: AirportSceneProps) {
  const { runways, taxiways, buildings, ground } = AIRPORT_3D_CONFIG;

  // Only show default buildings if no OSM terminals are loaded
  const hasOSMData = terminals && terminals.length > 0;

  return (
    <group>
      {/* Ground plane */}
      <Ground size={ground.size} color={ground.color} />

      {/* Default buildings (only if no OSM data) */}
      {!hasOSMData && buildings.map((building) => (
        <Building3D key={building.id} placement={building} />
      ))}

      {/* OSM Terminal Buildings (imported from OpenStreetMap) */}
      <TerminalGroup terminals={terminals} />

      {/* Runways */}
      {runways.map((runway) => (
        <Runway key={runway.id} config={runway} />
      ))}

      {/* Taxiways */}
      {taxiways.map((taxiway) => (
        <Taxiway key={taxiway.id} config={taxiway} />
      ))}

      {/* Trajectory (render before aircraft so it appears behind) */}
      <Trajectory3D />

      {/* Aircraft */}
      {flights.map((flight) => (
        <Aircraft3D
          key={flight.icao24}
          flight={flight}
          selected={selectedFlight === flight.icao24}
          onClick={() => onSelectFlight?.(flight.icao24)}
        />
      ))}
    </group>
  );
}

/**
 * Ground Component
 * Large flat plane representing the airport grass area
 */
function Ground({ size, color }: { size: number; color: number }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
      <planeGeometry args={[size, size]} />
      <meshStandardMaterial color={color} side={THREE.DoubleSide} />
    </mesh>
  );
}

/**
 * Runway Component
 * Flat box representing a runway with center line markings
 */
function Runway({ config }: { config: typeof AIRPORT_3D_CONFIG.runways[0] }) {
  const { start, end, width, color, id } = config;

  // Calculate runway length and center position
  const length = Math.sqrt(
    Math.pow(end.x - start.x, 2) +
    Math.pow(end.z - start.z, 2)
  );

  const centerX = (start.x + end.x) / 2;
  const centerZ = (start.z + end.z) / 2;
  const y = start.y;

  // Calculate rotation angle for runway orientation
  const angle = Math.atan2(end.z - start.z, end.x - start.x);

  // Create center line markings (dashed pattern)
  const markings = useMemo(() => {
    const segments: JSX.Element[] = [];
    const markingLength = 30;
    const gapLength = 20;
    const markingWidth = 2;
    const totalLength = length - 40; // Leave some space at ends

    let pos = -totalLength / 2;
    let i = 0;

    while (pos < totalLength / 2) {
      segments.push(
        <mesh
          key={`marking-${id}-${i}`}
          position={[pos + markingLength / 2, 0.02, 0]}
          rotation={[0, 0, 0]}
        >
          <boxGeometry args={[markingLength, 0.1, markingWidth]} />
          <meshStandardMaterial color={RUNWAY_MARKING_COLOR} />
        </mesh>
      );
      pos += markingLength + gapLength;
      i++;
    }

    return segments;
  }, [length, id]);

  return (
    <group position={[centerX, y, centerZ]} rotation={[0, -angle, 0]}>
      {/* Runway surface */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[length, width]} />
        <meshStandardMaterial color={color} />
      </mesh>

      {/* Center line markings */}
      {markings}

      {/* Runway threshold markings (simplified) */}
      <RunwayThreshold position={[-length / 2 + 15, 0.02, 0]} width={width} />
      <RunwayThreshold position={[length / 2 - 15, 0.02, 0]} width={width} />
    </group>
  );
}

/**
 * RunwayThreshold Component
 * Simplified threshold markings at runway ends
 */
function RunwayThreshold({ position, width }: { position: [number, number, number]; width: number }) {
  const stripes = useMemo(() => {
    const segments: JSX.Element[] = [];
    const stripeWidth = 3;
    const stripeLength = 20;
    const gap = 3;
    const numStripes = Math.floor((width - 10) / (stripeWidth + gap));
    const startZ = -((numStripes - 1) * (stripeWidth + gap)) / 2;

    for (let i = 0; i < numStripes; i++) {
      segments.push(
        <mesh
          key={`threshold-${i}`}
          position={[0, 0, startZ + i * (stripeWidth + gap)]}
        >
          <boxGeometry args={[stripeLength, 0.1, stripeWidth]} />
          <meshStandardMaterial color={RUNWAY_MARKING_COLOR} />
        </mesh>
      );
    }

    return segments;
  }, [width]);

  return <group position={position}>{stripes}</group>;
}

/**
 * Taxiway Component
 * Flat surface connecting runway to terminal area
 */
function Taxiway({ config }: { config: typeof AIRPORT_3D_CONFIG.taxiways[0] }) {
  const { points, width, color } = config;

  // Create segments between consecutive points
  const segments = useMemo(() => {
    const result: JSX.Element[] = [];

    for (let i = 0; i < points.length - 1; i++) {
      const start = points[i];
      const end = points[i + 1];

      const length = Math.sqrt(
        Math.pow(end.x - start.x, 2) +
        Math.pow(end.z - start.z, 2)
      );

      const centerX = (start.x + end.x) / 2;
      const centerZ = (start.z + end.z) / 2;
      const y = start.y;

      const angle = Math.atan2(end.z - start.z, end.x - start.x);

      result.push(
        <mesh
          key={`segment-${i}`}
          position={[centerX, y, centerZ]}
          rotation={[-Math.PI / 2, 0, -angle]}
          receiveShadow
        >
          <planeGeometry args={[length, width]} />
          <meshStandardMaterial color={color} />
        </mesh>
      );
    }

    return result;
  }, [points, width, color]);

  return <group>{segments}</group>;
}
