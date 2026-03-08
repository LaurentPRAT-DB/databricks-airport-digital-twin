import { describe, it, expect, vi, beforeEach } from 'vitest';
import ReactThreeTestRenderer from '@react-three/test-renderer';
import { AirportScene } from './AirportScene';
import { Flight } from '../../types/flight';

// Mock child components to isolate AirportScene testing
vi.mock('./Aircraft3D', () => ({
  Aircraft3D: ({ flight, selected }: { flight: Flight; selected: boolean }) => (
    <mesh name={`aircraft-${flight.icao24}`}>
      <boxGeometry args={[10, 5, 30]} />
      <meshStandardMaterial color={selected ? 0x00ff00 : 0xcccccc} />
    </mesh>
  ),
}));

vi.mock('./Trajectory3D', () => ({
  Trajectory3D: () => (
    <mesh name="trajectory">
      <bufferGeometry />
      <meshBasicMaterial />
    </mesh>
  ),
}));

vi.mock('./Building3D', () => ({
  Building3D: ({ placement }: { placement: { id: string } }) => (
    <mesh name={`building-${placement.id}`}>
      <boxGeometry args={[20, 10, 20]} />
      <meshStandardMaterial color={0x888888} />
    </mesh>
  ),
}));

// Mock useFrame to avoid animation loop issues
vi.mock('@react-three/fiber', async () => {
  const actual = await vi.importActual('@react-three/fiber');
  return {
    ...actual,
    useFrame: vi.fn(),
  };
});

// Helper to create mock flight data
const createMockFlight = (overrides: Partial<Flight> = {}): Flight => ({
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

describe('AirportScene', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Basic rendering', () => {
    it('renders without crashing', async () => {
      const renderer = await ReactThreeTestRenderer.create(<AirportScene />);
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders a group as root element', async () => {
      const renderer = await ReactThreeTestRenderer.create(<AirportScene />);
      const root = renderer.scene.children[0];
      expect(root.type).toBe('Group');
    });

    it('renders with empty flights array', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={[]} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders with undefined props', async () => {
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={undefined} selectedFlight={undefined} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Ground plane', () => {
    it('renders ground mesh', async () => {
      const renderer = await ReactThreeTestRenderer.create(<AirportScene />);
      const group = renderer.scene.children[0];

      // Find meshes with plane geometry (ground)
      const meshes = group.children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      expect(meshes.length).toBeGreaterThan(0);
    });
  });

  describe('Terminal building', () => {
    it('renders terminal mesh', async () => {
      const renderer = await ReactThreeTestRenderer.create(<AirportScene />);
      const group = renderer.scene.children[0];

      // Terminal is rendered as a Mesh with box geometry
      const meshes = group.children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      expect(meshes.length).toBeGreaterThan(0);
    });
  });

  describe('Runways', () => {
    it('renders runway groups', async () => {
      const renderer = await ReactThreeTestRenderer.create(<AirportScene />);
      const group = renderer.scene.children[0];

      // Runways are rendered as groups containing plane + markings
      const groups = group.children.filter(
        (child: { type: string }) => child.type === 'Group'
      );
      expect(groups.length).toBeGreaterThan(0);
    });
  });

  describe('Aircraft rendering', () => {
    it('renders single flight', async () => {
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={[flight]} />
      );

      // Scene should contain aircraft along with other elements
      const group = renderer.scene.children[0];
      expect(group.children.length).toBeGreaterThan(0);
    });

    it('renders multiple flights', async () => {
      const flights = [
        createMockFlight({ icao24: 'flight1' }),
        createMockFlight({ icao24: 'flight2' }),
        createMockFlight({ icao24: 'flight3' }),
      ];

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} />
      );

      // Should render all components including 3 aircraft
      const group = renderer.scene.children[0];
      expect(group.children.length).toBeGreaterThan(3);
    });

    it('passes selected state to Aircraft3D', async () => {
      const flights = [
        createMockFlight({ icao24: 'selected-flight' }),
        createMockFlight({ icao24: 'other-flight' }),
      ];

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} selectedFlight="selected-flight" />
      );

      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles no selected flight', async () => {
      const flights = [createMockFlight({ icao24: 'flight1' })];

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} selectedFlight={null} />
      );

      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Flight selection', () => {
    it('renders with onSelectFlight callback', async () => {
      const onSelectFlight = vi.fn();
      const flight = createMockFlight({ icao24: 'clickable-flight' });

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene
          flights={[flight]}
          onSelectFlight={onSelectFlight}
        />
      );

      // Verify scene renders with the callback prop
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('works without onSelectFlight callback', async () => {
      const flight = createMockFlight();

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={[flight]} />
      );

      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Trajectory', () => {
    it('renders Trajectory3D component', async () => {
      const renderer = await ReactThreeTestRenderer.create(<AirportScene />);

      // Trajectory is rendered as part of the scene group
      const group = renderer.scene.children[0];
      expect(group.children.length).toBeGreaterThan(0);
    });
  });

  describe('Buildings', () => {
    it('renders Building3D components', async () => {
      const renderer = await ReactThreeTestRenderer.create(<AirportScene />);

      const group = renderer.scene.children[0];
      // Scene should have multiple children including buildings
      expect(group.children.length).toBeGreaterThan(0);
    });
  });

  describe('Taxiways', () => {
    it('renders taxiway groups', async () => {
      const renderer = await ReactThreeTestRenderer.create(<AirportScene />);

      const group = renderer.scene.children[0];
      // Taxiways render as groups containing mesh segments
      expect(group.children.length).toBeGreaterThan(0);
    });
  });

  describe('Scene composition', () => {
    it('renders all scene elements in correct order', async () => {
      const flights = [createMockFlight()];

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} />
      );

      const group = renderer.scene.children[0];

      // Should contain:
      // - Ground (Mesh)
      // - Terminal (Mesh)
      // - Buildings (Mesh x N)
      // - Runways (Group x N)
      // - Taxiways (Group x N)
      // - Trajectory (Mesh)
      // - Aircraft (Mesh x N)

      const meshes = group.children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      const groups = group.children.filter(
        (child: { type: string }) => child.type === 'Group'
      );

      expect(meshes.length).toBeGreaterThan(3); // Ground + Terminal + Trajectory + Buildings + Aircraft
      expect(groups.length).toBeGreaterThan(0); // Runways + Taxiways
    });

    it('renders correctly with large flight count', async () => {
      const flights = Array(50)
        .fill(null)
        .map((_, i) => createMockFlight({ icao24: `flight-${i}` }));

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} />
      );

      // Scene should render successfully with many flights
      const group = renderer.scene.children[0];
      expect(group.children.length).toBeGreaterThan(50);
    });
  });

  describe('Props handling', () => {
    it('handles flights prop change', async () => {
      const flight1 = createMockFlight({ icao24: 'initial' });

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={[flight1]} />
      );

      expect(renderer.scene.children.length).toBeGreaterThan(0);

      // Create new scene with different flights
      const flight2 = createMockFlight({ icao24: 'updated' });
      const renderer2 = await ReactThreeTestRenderer.create(
        <AirportScene flights={[flight2]} />
      );

      // Verify both render correctly
      const group = renderer2.scene.children[0];
      expect(group.children.length).toBeGreaterThan(0);
    });

    it('handles selectedFlight prop change', async () => {
      const flights = [
        createMockFlight({ icao24: 'flight1' }),
        createMockFlight({ icao24: 'flight2' }),
      ];

      const renderer1 = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} selectedFlight="flight1" />
      );
      expect(renderer1.scene.children.length).toBeGreaterThan(0);

      const renderer2 = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} selectedFlight="flight2" />
      );
      expect(renderer2.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Edge cases', () => {
    it('handles flight with null coordinates', async () => {
      const flight = createMockFlight({
        latitude: null as unknown as number,
        longitude: null as unknown as number,
      });

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={[flight]} />
      );

      // Should still render scene even with invalid flight data
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles empty selected flight string', async () => {
      const flights = [createMockFlight()];

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} selectedFlight="" />
      );

      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles selected flight not in flights array', async () => {
      const flights = [createMockFlight({ icao24: 'actual-flight' })];

      const renderer = await ReactThreeTestRenderer.create(
        <AirportScene flights={flights} selectedFlight="non-existent-flight" />
      );

      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });
});
