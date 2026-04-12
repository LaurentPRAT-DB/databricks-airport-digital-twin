import { useMemo } from 'react';
import * as THREE from 'three';
import { AIRPORT_3D_CONFIG } from '../../constants/airport3D';
import { Flight } from '../../types/flight';
import { OSMTerminal, OSMTaxiway, OSMApron, OSMRunway } from '../../types/airportFormats';
import { Aircraft3D } from './Aircraft3D';
import { Trajectory3D } from './Trajectory3D';
import { TerminalGroup } from './Terminal3D';
import { latLonTo3D, METERS_TO_SCENE_UNITS, DEFAULT_COORDINATE_SCALE } from '../../utils/map3d-calculations';
import { SatelliteGround, TileLoadingProgress } from './SatelliteGround';

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
  /** Whether to show satellite imagery as ground plane */
  satellite?: boolean;
  /** Route satellite tiles through the inpainting proxy */
  inpainting?: boolean;
  /** Airport ICAO code for inpainting cache tagging */
  airportIcao?: string;
  /** Satellite tile loading progress callback */
  onTileLoadingProgress?: (progress: TileLoadingProgress | null) => void;
}

/**
 * AirportScene Component
 *
 * Renders the 3D airport environment including:
 * - Ground plane (grass or satellite imagery)
 * - OSM-sourced runways, taxiways, aprons, terminal buildings
 * - Aircraft at their current positions
 *
 * All airport geometry comes from OpenStreetMap via the Overpass API.
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
  satellite = false,
  inpainting = false,
  airportIcao,
  onTileLoadingProgress,
}: AirportSceneProps) {
  const { ground } = AIRPORT_3D_CONFIG;

  return (
    <group>
      {/* Ground plane: satellite imagery or flat color */}
      {satellite && airportCenter ? (
        <SatelliteGround
          size={ground.size}
          centerLat={airportCenter.lat}
          centerLon={airportCenter.lon}
          scale={DEFAULT_COORDINATE_SCALE}
          inpainting={inpainting}
          airportIcao={airportIcao}
          onLoadingProgress={onTileLoadingProgress}
        />
      ) : (
        <Ground size={ground.size} color={ground.color} />
      )}

      {/* OSM Terminal Buildings */}
      <TerminalGroup terminals={terminals} airportCenter={airportCenter} />

      {/* OSM Runways */}
      {osmRunways.length > 0 && (
        <OSMRunwayGroup runways={osmRunways} airportCenter={airportCenter} />
      )}

      {/* OSM Taxiways */}
      {osmTaxiways.length > 0 && (
        <OSMTaxiwayGroup taxiways={osmTaxiways} airportCenter={airportCenter} />
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
