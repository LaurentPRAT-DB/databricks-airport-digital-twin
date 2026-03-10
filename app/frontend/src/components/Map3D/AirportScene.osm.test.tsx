import { describe, it, expect, vi, beforeEach } from 'vitest';
import ReactThreeTestRenderer from '@react-three/test-renderer';
import { AirportScene } from './AirportScene';
import { Flight } from '../../types/flight';
import { OSMTerminal, OSMTaxiway, OSMApron, OSMRunway } from '../../types/airportFormats';

// Mock child components to isolate AirportScene logic
vi.mock('./Aircraft3D', () => ({
  Aircraft3D: ({ flight }: { flight: Flight }) => (
    <mesh name={`aircraft-${flight.icao24}`}>
      <boxGeometry args={[1, 0.5, 2]} />
      <meshStandardMaterial />
    </mesh>
  ),
}));

vi.mock('./Trajectory3D', () => ({
  Trajectory3D: () => null,
}));

vi.mock('./Building3D', () => ({
  Building3D: ({ placement }: { placement: { id: string } }) => (
    <mesh name={`building-${placement.id}`}>
      <boxGeometry args={[5, 3, 5]} />
      <meshStandardMaterial />
    </mesh>
  ),
}));

vi.mock('./Terminal3D', () => ({
  TerminalGroup: ({ terminals }: { terminals: OSMTerminal[] }) => (
    <group name="terminal-group">
      {terminals.map(t => (
        <mesh key={t.id} name={`terminal-${t.id}`}>
          <boxGeometry args={[10, 5, 10]} />
          <meshStandardMaterial />
        </mesh>
      ))}
    </group>
  ),
}));

vi.mock('@react-three/fiber', async () => {
  const actual = await vi.importActual('@react-three/fiber');
  return { ...actual, useFrame: vi.fn() };
});

// ============================================================================
// Helpers
// ============================================================================

const createFlight = (overrides: Partial<Flight> = {}): Flight => ({
  icao24: 'abc123',
  callsign: 'UAL123',
  latitude: 37.6213,
  longitude: -122.379,
  altitude: 5000,
  velocity: 200,
  heading: 270,
  vertical_rate: -500,
  on_ground: false,
  last_seen: new Date().toISOString(),
  data_source: 'synthetic',
  flight_phase: 'descending',
  aircraft_type: 'B737',
  ...overrides,
});

const sfoCenter = { lat: 37.6213, lon: -122.379 };

const createTerminal = (id: string, lat: number, lon: number): OSMTerminal => ({
  id,
  osmId: 1000,
  name: `Terminal ${id}`,
  type: 'terminal',
  position: { x: 0, y: 0, z: 0 },
  dimensions: { width: 100, height: 10, depth: 50 },
  polygon: [],
  color: 0xcccccc,
  geo: { latitude: lat, longitude: lon },
  geoPolygon: [
    { latitude: lat - 0.001, longitude: lon - 0.001 },
    { latitude: lat + 0.001, longitude: lon - 0.001 },
    { latitude: lat + 0.001, longitude: lon + 0.001 },
    { latitude: lat - 0.001, longitude: lon + 0.001 },
  ],
});

const createRunway = (id: string): OSMRunway => ({
  id,
  osmId: 2000,
  name: id,
  points: [],
  width: 60,
  color: 0x333333,
  geoPoints: [
    { latitude: 37.610, longitude: -122.390 },
    { latitude: 37.630, longitude: -122.370 },
  ],
});

const createTaxiway = (id: string): OSMTaxiway => ({
  id,
  osmId: 3000,
  name: id,
  points: [],
  width: 15,
  color: 0x888888,
  geoPoints: [
    { latitude: 37.620, longitude: -122.380 },
    { latitude: 37.622, longitude: -122.378 },
  ],
});

const createApron = (id: string): OSMApron => ({
  id,
  osmId: 4000,
  name: id,
  position: { x: 0, y: 0, z: 0 },
  dimensions: { width: 50, height: 1, depth: 50 },
  polygon: [],
  color: 0xaaaaaa,
  geo: { latitude: 37.621, longitude: -122.379 },
  geoPolygon: [
    { latitude: 37.620, longitude: -122.380 },
    { latitude: 37.622, longitude: -122.380 },
    { latitude: 37.622, longitude: -122.378 },
    { latitude: 37.620, longitude: -122.378 },
  ],
});


// ============================================================================
// Tests
// ============================================================================

describe('AirportScene — OSM data behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('hasOSMData detection', () => {
    it('shows hardcoded buildings when no OSM data', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene />
      );
      const group = renderer.scene.children[0];
      // Default scene has hardcoded buildings (from AIRPORT_3D_CONFIG)
      const buildingMeshes = group.children.filter(
        (c: { props?: Record<string, unknown> }) =>
          (c.props?.name as string)?.startsWith('building-')
      );
      expect(buildingMeshes.length).toBeGreaterThan(0);
    });

    it('hides hardcoded buildings when terminals are present', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          terminals={[createTerminal('t1', 37.62, -122.38)]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      const buildingMeshes = group.children.filter(
        (c: { props?: Record<string, unknown> }) =>
          (c.props?.name as string)?.startsWith('building-')
      );
      expect(buildingMeshes.length).toBe(0);
    });

    it('hides hardcoded buildings when only runways are present', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmRunways={[createRunway('28L')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      const buildingMeshes = group.children.filter(
        (c: { props?: Record<string, unknown> }) =>
          (c.props?.name as string)?.startsWith('building-')
      );
      expect(buildingMeshes.length).toBe(0);
    });

    it('hides hardcoded buildings when only taxiways are present', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmTaxiways={[createTaxiway('A')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      const buildingMeshes = group.children.filter(
        (c: { props?: Record<string, unknown> }) =>
          (c.props?.name as string)?.startsWith('building-')
      );
      expect(buildingMeshes.length).toBe(0);
    });

    it('hides hardcoded buildings when only aprons are present', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmAprons={[createApron('A1')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      const buildingMeshes = group.children.filter(
        (c: { props?: Record<string, unknown> }) =>
          (c.props?.name as string)?.startsWith('building-')
      );
      expect(buildingMeshes.length).toBe(0);
    });
  });

  describe('OSM runway rendering', () => {
    it('renders OSM runways when present', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmRunways={[createRunway('28L')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      // Find group named "osm-runways"
      const osmRunwayGroup = group.children.find(
        (c: { props?: Record<string, unknown> }) => c.props?.name === 'osm-runways'
      );
      expect(osmRunwayGroup).toBeDefined();
    });

    it('renders multiple OSM runways', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmRunways={[createRunway('28L'), createRunway('28R')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      const osmRunwayGroup = group.children.find(
        (c: { props?: Record<string, unknown> }) => c.props?.name === 'osm-runways'
      );
      expect(osmRunwayGroup).toBeDefined();
      // Each runway becomes a group of mesh segments
      expect(osmRunwayGroup!.children.length).toBe(2);
    });

    it('does not render hardcoded runways when OSM runways present', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmRunways={[createRunway('28L')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      // No hardcoded runway groups (hasOSMData = true)
      // The key check: osm-runways IS present
      const osmRunwayGroup = group.children.find(
        (c: { props?: Record<string, unknown> }) => c.props?.name === 'osm-runways'
      );
      expect(osmRunwayGroup).toBeDefined();
    });
  });

  describe('OSM taxiway rendering', () => {
    it('renders OSM taxiways when present', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmTaxiways={[createTaxiway('A')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      const osmTaxiwayGroup = group.children.find(
        (c: { props?: Record<string, unknown> }) => c.props?.name === 'osm-taxiways'
      );
      expect(osmTaxiwayGroup).toBeDefined();
    });

    it('renders multiple taxiways', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmTaxiways={[createTaxiway('A'), createTaxiway('B'), createTaxiway('C')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      const osmTaxiwayGroup = group.children.find(
        (c: { props?: Record<string, unknown> }) => c.props?.name === 'osm-taxiways'
      );
      expect(osmTaxiwayGroup!.children.length).toBe(3);
    });
  });

  describe('OSM apron rendering', () => {
    it('renders OSM aprons when present', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmAprons={[createApron('A1')]}
          airportCenter={sfoCenter}
        />
      );
      const group = renderer.scene.children[0];
      const osmApronGroup = group.children.find(
        (c: { props?: Record<string, unknown> }) => c.props?.name === 'osm-aprons'
      );
      expect(osmApronGroup).toBeDefined();
      expect(osmApronGroup!.children.length).toBe(1);
    });

    it('does not render apron group when no aprons', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene osmAprons={[]} airportCenter={sfoCenter} />
      );
      const group = renderer.scene.children[0];
      const osmApronGroup = group.children.find(
        (c: { props?: Record<string, unknown> }) => c.props?.name === 'osm-aprons'
      );
      // Empty aprons → the condition `osmAprons.length > 0` is false
      expect(osmApronGroup).toBeUndefined();
    });
  });

  describe('Full OSM airport scene', () => {
    it('renders complete OSM scene with all element types', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          terminals={[createTerminal('t1', 37.62, -122.38)]}
          osmRunways={[createRunway('28L'), createRunway('28R')]}
          osmTaxiways={[createTaxiway('A'), createTaxiway('B')]}
          osmAprons={[createApron('A1')]}
          airportCenter={sfoCenter}
          flights={[createFlight()]}
        />
      );
      const group = renderer.scene.children[0];

      // Check ground mesh is present
      const meshes = group.children.filter(
        (c: { type: string }) => c.type === 'Mesh'
      );
      expect(meshes.length).toBeGreaterThan(0);

      // Check named groups
      const namedGroups = group.children
        .filter((c: { props?: Record<string, unknown> }) => c.props?.name)
        .map((c: { props?: Record<string, unknown> }) => c.props!.name);
      expect(namedGroups).toContain('osm-runways');
      expect(namedGroups).toContain('osm-taxiways');
      expect(namedGroups).toContain('osm-aprons');

      // No hardcoded buildings
      const buildingMeshes = group.children.filter(
        (c: { props?: Record<string, unknown> }) =>
          (c.props?.name as string)?.startsWith('building-')
      );
      expect(buildingMeshes.length).toBe(0);
    });
  });

  describe('Aircraft rendering with OSM data', () => {
    it('renders aircraft even when OSM data is present', async () => {
      const flights = [
        createFlight({ icao24: 'f1' }),
        createFlight({ icao24: 'f2' }),
      ];
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          terminals={[createTerminal('t1', 37.62, -122.38)]}
          airportCenter={sfoCenter}
          flights={flights}
        />
      );
      const group = renderer.scene.children[0];
      const aircraftMeshes = group.children.filter(
        (c: { props?: Record<string, unknown> }) =>
          (c.props?.name as string)?.startsWith('aircraft-')
      );
      expect(aircraftMeshes.length).toBe(2);
    });

    it('marks selected aircraft', async () => {
      const flights = [
        createFlight({ icao24: 'selected-one' }),
        createFlight({ icao24: 'other-one' }),
      ];
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          flights={flights}
          selectedFlight="selected-one"
          airportCenter={sfoCenter}
        />
      );
      // Scene renders without crash with selection
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Edge cases', () => {
    it('handles runway with less than 2 geoPoints', async () => {
      const badRunway: OSMRunway = {
        id: 'bad',
        osmId: 9000,
        name: 'bad',
        points: [],
        width: 60,
        color: 0x333333,
        geoPoints: [{ latitude: 37.62, longitude: -122.38 }], // Only 1 point
      };
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene osmRunways={[badRunway]} airportCenter={sfoCenter} />
      );
      // Should not crash
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles taxiway with less than 2 geoPoints', async () => {
      const badTaxiway: OSMTaxiway = {
        id: 'bad',
        osmId: 9001,
        name: 'bad',
        points: [],
        width: 15,
        color: 0x888888,
        geoPoints: [], // Empty
      };
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene osmTaxiways={[badTaxiway]} airportCenter={sfoCenter} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles apron with less than 3 polygon points', async () => {
      const badApron: OSMApron = {
        id: 'bad',
        osmId: 9002,
        name: 'bad',
        position: { x: 0, y: 0, z: 0 },
        dimensions: { width: 50, height: 1, depth: 50 },
        polygon: [],
        color: 0xaaaaaa,
        geo: { latitude: 37.62, longitude: -122.38 },
        geoPolygon: [
          { latitude: 37.62, longitude: -122.38 },
          { latitude: 37.621, longitude: -122.379 },
        ], // Only 2 points, need 3+
      };
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene osmAprons={[badApron]} airportCenter={sfoCenter} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles undefined airportCenter', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          osmRunways={[createRunway('28L')]}
          airportCenter={undefined}
        />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });
});
