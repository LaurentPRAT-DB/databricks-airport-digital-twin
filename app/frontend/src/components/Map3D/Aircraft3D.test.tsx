import { describe, it, expect, vi, beforeEach } from 'vitest';
import ReactThreeTestRenderer from '@react-three/test-renderer';
import { Flight } from '../../types/flight';

// Mock GLTFAircraft to avoid loading actual GLTF models
vi.mock('./GLTFAircraft', () => ({
  GLTFAircraft: ({ selected }: { selected?: boolean }) => (
    <mesh>
      <boxGeometry args={[10, 5, 30]} />
      <meshStandardMaterial color={selected ? 0x00ff00 : 0xcccccc} />
    </mesh>
  ),
}));

// Mock useFrame to avoid Canvas context requirement
vi.mock('@react-three/fiber', async () => {
  const actual = await vi.importActual('@react-three/fiber');
  return {
    ...actual,
    useFrame: vi.fn(),
  };
});

// Import after mocking
import { Aircraft3D } from './Aircraft3D';

// Mock flight data
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
  last_seen: Date.now(),
  data_source: 'synthetic',
  flight_phase: 'descending',
  aircraft_type: 'B737',
  ...overrides,
});

describe('Aircraft3D', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.classList.remove('cursor-pointer');
  });

  describe('Rendering', () => {
    it('renders without crashing', async () => {
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders a group as root element', async () => {
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      const root = renderer.scene.children[0];
      expect(root.type).toBe('Group');
    });

    it('renders with different coordinates', async () => {
      const flight = createMockFlight({
        latitude: 40.7128,
        longitude: -74.006,
        altitude: 10000,
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders with different heading', async () => {
      const flight = createMockFlight({ heading: 90 });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Selection', () => {
    it('renders selection ring when selected', async () => {
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} selected={true} />
      );
      const group = renderer.scene.children[0];
      const meshes = group.children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      // At least 3 meshes: aircraft + 2 selection rings
      expect(meshes.length).toBeGreaterThanOrEqual(3);
    });

    it('has fewer meshes when not selected', async () => {
      const flight = createMockFlight();
      const rendererSelected = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} selected={true} />
      );
      const rendererUnselected = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} selected={false} />
      );
      const selectedMeshes = rendererSelected.scene.children[0].children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      const unselectedMeshes = rendererUnselected.scene.children[0].children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      expect(selectedMeshes.length).toBeGreaterThan(unselectedMeshes.length);
    });
  });

  describe('Click Handler', () => {
    it('calls onClick when clicked', async () => {
      const onClick = vi.fn();
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} onClick={onClick} />
      );
      const group = renderer.scene.children[0];
      await renderer.fireEvent(group, 'click', { stopPropagation: vi.fn() });
      expect(onClick).toHaveBeenCalled();
    });

    it('stops event propagation on click', async () => {
      const onClick = vi.fn();
      const stopPropagation = vi.fn();
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} onClick={onClick} />
      );
      const group = renderer.scene.children[0];
      await renderer.fireEvent(group, 'click', { stopPropagation });
      expect(stopPropagation).toHaveBeenCalled();
    });

    it('works without onClick handler', async () => {
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      const group = renderer.scene.children[0];
      await expect(
        renderer.fireEvent(group, 'click', { stopPropagation: vi.fn() })
      ).resolves.not.toThrow();
    });
  });

  describe('Aircraft Types', () => {
    const aircraftTypes = ['B737', 'A320', 'B787', 'A380', 'B777', 'CRJ9', 'E175', 'UNKNOWN', undefined];

    aircraftTypes.forEach((type) => {
      it(`renders ${type ?? 'undefined'} aircraft type`, async () => {
        const flight = createMockFlight({ aircraft_type: type });
        const renderer = await ReactThreeTestRenderer.create(
          <Aircraft3D flight={flight} />
        );
        expect(renderer.scene.children.length).toBeGreaterThan(0);
      });
    });
  });

  describe('Airlines', () => {
    const callsigns = ['UAL123', 'DAL456', 'SWA789', 'AAL100', 'JBU200', null];

    callsigns.forEach((callsign) => {
      it(`renders ${callsign ?? 'null'} callsign`, async () => {
        const flight = createMockFlight({ callsign });
        const renderer = await ReactThreeTestRenderer.create(
          <Aircraft3D flight={flight} />
        );
        expect(renderer.scene.children.length).toBeGreaterThan(0);
      });
    });
  });

  describe('Flight Phases', () => {
    it('renders aircraft on ground', async () => {
      const flight = createMockFlight({
        on_ground: true,
        altitude: 0,
        flight_phase: 'ground',
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders aircraft descending', async () => {
      const flight = createMockFlight({
        on_ground: false,
        altitude: 5000,
        flight_phase: 'descending',
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders aircraft cruising', async () => {
      const flight = createMockFlight({
        on_ground: false,
        altitude: 35000,
        flight_phase: 'cruising',
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders aircraft climbing', async () => {
      const flight = createMockFlight({
        on_ground: false,
        altitude: 15000,
        flight_phase: 'climbing',
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Hover Events', () => {
    it('handles pointer over event', async () => {
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      const group = renderer.scene.children[0];
      await renderer.fireEvent(group, 'pointerOver', { stopPropagation: vi.fn() });
      expect(document.body.classList.contains('cursor-pointer')).toBe(true);
    });

    it('handles pointer out event', async () => {
      const flight = createMockFlight();
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      const group = renderer.scene.children[0];
      await renderer.fireEvent(group, 'pointerOver', { stopPropagation: vi.fn() });
      await renderer.fireEvent(group, 'pointerOut');
      expect(document.body.classList.contains('cursor-pointer')).toBe(false);
    });
  });

  describe('Edge Cases', () => {
    it('handles negative altitude', async () => {
      const flight = createMockFlight({ altitude: -100 });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles very high altitude', async () => {
      const flight = createMockFlight({ altitude: 50000 });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles null altitude', async () => {
      const flight = createMockFlight({ altitude: null as unknown as number });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles extreme coordinates', async () => {
      const flight = createMockFlight({ latitude: 89.9, longitude: 179.9 });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles zero heading', async () => {
      const flight = createMockFlight({ heading: 0 });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles 360 heading', async () => {
      const flight = createMockFlight({ heading: 360 });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles negative heading', async () => {
      const flight = createMockFlight({ heading: -90 });
      const renderer = await ReactThreeTestRenderer.create(
        <Aircraft3D flight={flight} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });
});
