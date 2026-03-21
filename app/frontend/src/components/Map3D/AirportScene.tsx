import { useMemo } from 'react';
import * as THREE from 'three';
import { AIRPORT_3D_CONFIG, RUNWAY_MARKING_COLOR } from '../../constants/airport3D';
import { Flight } from '../../types/flight';
import { OSMTerminal, OSMTaxiway, OSMApron, OSMRunway } from '../../types/airportFormats';
import { Aircraft3D } from './Aircraft3D';
import { Trajectory3D } from './Trajectory3D';
import { Building3D } from './Building3D';
import { TerminalGroup } from './Terminal3D';
import { latLonTo3D, METERS_TO_SCENE_UNITS, DEFAULT_COORDINATE_SCALE } from '../../utils/map3d-calculations';
import { SatelliteGround } from './SatelliteGround';

const SCENE_COLORS = {
  runway: 0x555555,   // Dark asphalt
  taxiway: 0x777777,  // Medium asphalt
  apron: 0x999999,    // Light concrete
};

interface AirportSceneProps {
  flights?: Flight[];
  selectedFlight?: string | null;
  onSelectFlight?: (icao24: string) => void;
  /** OSM terminal buildings to render */
  terminals?: OSMTerminal[];
  /** Airport center for 3D coordinate conversion */
  airportCenter?: { lat: number; lon: number };
  /** OSM taxiways */
  osmTaxiways?: OSMTaxiway[];
  /** OSM aprons */
  osmAprons?: OSMApron[];
  /** OSM runways */
  osmRunways?: OSMRunway[];
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
  airportCenter,
  osmTaxiways = [],
  osmAprons = [],
  osmRunways = [],
}: AirportSceneProps) {
  const { runways, taxiways, buildings, ground } = AIRPORT_3D_CONFIG;

  // Hide all hardcoded elements when ANY OSM data is present for this airport
  const hasOSMData = (terminals?.length ?? 0) > 0 || (osmRunways?.length ?? 0) > 0 ||
                     (osmTaxiways?.length ?? 0) > 0 || (osmAprons?.length ?? 0) > 0;

  return (
    <group>
      {/* Satellite imagery ground plane */}
      {airportCenter ? (
        <SatelliteGround
          size={ground.size}
          centerLat={airportCenter.lat}
          centerLon={airportCenter.lon}
          scale={DEFAULT_COORDINATE_SCALE}
        />
      ) : (
        <Ground size={ground.size} color={ground.color} />
      )}

      {/* Default buildings (only if no OSM data) */}
      {!hasOSMData && buildings.map((building) => (
        <Building3D key={building.id} placement={building} />
      ))}

      {/* OSM Terminal Buildings (imported from OpenStreetMap) */}
      <TerminalGroup terminals={terminals} airportCenter={airportCenter} />

      {/* Runways: OSM if available, otherwise hardcoded */}
      {hasOSMData && osmRunways.length > 0 ? (
        <OSMRunwayGroup runways={osmRunways} airportCenter={airportCenter} />
      ) : !hasOSMData && (
        runways.map((runway) => (
          <Runway key={runway.id} config={runway} />
        ))
      )}

      {/* Taxiways: OSM if available, otherwise hardcoded */}
      {hasOSMData && osmTaxiways.length > 0 ? (
        <OSMTaxiwayGroup taxiways={osmTaxiways} airportCenter={airportCenter} />
      ) : !hasOSMData && (
        taxiways.map((taxiway) => (
          <Taxiway key={taxiway.id} config={taxiway} />
        ))
      )}

      {/* OSM Aprons */}
      {osmAprons.length > 0 && (
        <OSMApronGroup aprons={osmAprons} airportCenter={airportCenter} />
      )}

      {/* Trajectory (render before aircraft so it appears behind) */}
      <Trajectory3D airportCenter={airportCenter} />

      {/* Aircraft */}
      {flights.map((flight) => (
        <Aircraft3D
          key={flight.icao24}
          flight={flight}
          selected={selectedFlight === flight.icao24}
          onClick={() => onSelectFlight?.(flight.icao24)}
          airportCenter={airportCenter}
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

// ============================================================================
// OSM-based 3D Components (use geoPoints + latLonTo3D)
// ============================================================================

/**
 * Renders OSM runways using geoPoints converted via latLonTo3D
 */
function OSMRunwayGroup({ runways, airportCenter }: { runways: OSMRunway[]; airportCenter?: { lat: number; lon: number } }) {
  return (
    <group name="osm-runways">
      {runways.map((runway) => (
        <OSMRunway3D key={runway.id} runway={runway} airportCenter={airportCenter} />
      ))}
    </group>
  );
}

function OSMRunway3D({ runway, airportCenter }: { runway: OSMRunway; airportCenter?: { lat: number; lon: number } }) {
  const segments = useMemo(() => {
    const geoPoints = runway.geoPoints;
    if (!geoPoints || geoPoints.length < 2) return null;

    const points3D = geoPoints.map(pt =>
      latLonTo3D(pt.latitude, pt.longitude, 0, airportCenter?.lat, airportCenter?.lon)
    );

    const result: JSX.Element[] = [];
    for (let i = 0; i < points3D.length - 1; i++) {
      const start = points3D[i];
      const end = points3D[i + 1];
      const length = Math.sqrt(Math.pow(end.x - start.x, 2) + Math.pow(end.z - start.z, 2));
      const cx = (start.x + end.x) / 2;
      const cz = (start.z + end.z) / 2;
      const angle = Math.atan2(end.z - start.z, end.x - start.x);

      result.push(
        <mesh
          key={`osm-rwy-seg-${i}`}
          position={[cx, 0.1, cz]}
          rotation={[-Math.PI / 2, 0, -angle]}
          receiveShadow
        >
          <planeGeometry args={[length, runway.width * METERS_TO_SCENE_UNITS]} />
          <meshStandardMaterial color={SCENE_COLORS.runway} />
        </mesh>
      );
    }
    return result;
  }, [runway, airportCenter?.lat, airportCenter?.lon]);

  if (!segments) return null;
  return <group>{segments}</group>;
}

/**
 * Renders OSM taxiways using geoPoints converted via latLonTo3D
 */
function OSMTaxiwayGroup({ taxiways, airportCenter }: { taxiways: OSMTaxiway[]; airportCenter?: { lat: number; lon: number } }) {
  return (
    <group name="osm-taxiways">
      {taxiways.map((taxiway) => (
        <OSMTaxiway3D key={taxiway.id} taxiway={taxiway} airportCenter={airportCenter} />
      ))}
    </group>
  );
}

function OSMTaxiway3D({ taxiway, airportCenter }: { taxiway: OSMTaxiway; airportCenter?: { lat: number; lon: number } }) {
  const segments = useMemo(() => {
    const geoPoints = taxiway.geoPoints;
    if (!geoPoints || geoPoints.length < 2) return null;

    const points3D = geoPoints.map(pt =>
      latLonTo3D(pt.latitude, pt.longitude, 0, airportCenter?.lat, airportCenter?.lon)
    );

    const result: JSX.Element[] = [];
    for (let i = 0; i < points3D.length - 1; i++) {
      const start = points3D[i];
      const end = points3D[i + 1];
      const length = Math.sqrt(Math.pow(end.x - start.x, 2) + Math.pow(end.z - start.z, 2));
      const cx = (start.x + end.x) / 2;
      const cz = (start.z + end.z) / 2;
      const angle = Math.atan2(end.z - start.z, end.x - start.x);

      result.push(
        <mesh
          key={`osm-twy-seg-${i}`}
          position={[cx, 0.05, cz]}
          rotation={[-Math.PI / 2, 0, -angle]}
          receiveShadow
        >
          <planeGeometry args={[length, taxiway.width * METERS_TO_SCENE_UNITS]} />
          <meshStandardMaterial color={SCENE_COLORS.taxiway} />
        </mesh>
      );
    }
    return result;
  }, [taxiway, airportCenter?.lat, airportCenter?.lon]);

  if (!segments) return null;
  return <group>{segments}</group>;
}

/**
 * Renders OSM aprons as ground polygons using geoPolygon converted via latLonTo3D
 */
function OSMApronGroup({ aprons, airportCenter }: { aprons: OSMApron[]; airportCenter?: { lat: number; lon: number } }) {
  return (
    <group name="osm-aprons">
      {aprons.map((apron) => (
        <OSMApron3D key={apron.id} apron={apron} airportCenter={airportCenter} />
      ))}
    </group>
  );
}

function OSMApron3D({ apron, airportCenter }: { apron: OSMApron; airportCenter?: { lat: number; lon: number } }) {
  const geometry = useMemo(() => {
    const geoPolygon = apron.geoPolygon;
    if (!geoPolygon || geoPolygon.length < 3) return null;

    const center3D = latLonTo3D(apron.geo.latitude, apron.geo.longitude, 0, airportCenter?.lat, airportCenter?.lon);
    const points3D = geoPolygon.map(pt =>
      latLonTo3D(pt.latitude, pt.longitude, 0, airportCenter?.lat, airportCenter?.lon)
    );

    const shape = new THREE.Shape();
    shape.moveTo(points3D[0].x - center3D.x, points3D[0].z - center3D.z);
    for (let i = 1; i < points3D.length; i++) {
      shape.lineTo(points3D[i].x - center3D.x, points3D[i].z - center3D.z);
    }
    shape.closePath();

    return {
      geo: new THREE.ShapeGeometry(shape),
      center: center3D,
    };
  }, [apron, airportCenter?.lat, airportCenter?.lon]);

  if (!geometry) return null;

  return (
    <mesh
      position={[geometry.center.x, 0.02, geometry.center.z]}
      rotation={[-Math.PI / 2, 0, 0]}
      receiveShadow
    >
      <primitive object={geometry.geo} />
      <meshStandardMaterial color={SCENE_COLORS.apron} side={THREE.DoubleSide} />
    </mesh>
  );
}
