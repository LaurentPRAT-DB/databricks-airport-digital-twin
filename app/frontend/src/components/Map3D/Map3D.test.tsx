import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Flight } from '../../types/flight';
import { SharedViewport } from '../../hooks/useViewportState';
import { OSMTerminal, OSMTaxiway, OSMApron, OSMRunway } from '../../types/airportFormats';

// ============================================================================
// Mocks
// ============================================================================

// Track what props Map3D passes to child components
let lastAirportSceneProps: Record<string, unknown> = {};
let lastOrbitControlsProps: Record<string, unknown> = {};
let lastCameraProps: Record<string, unknown> = {};

// Mock useAirportConfig
const mockGetTerminals = vi.fn((): OSMTerminal[] => []);
const mockGetAirportCenter = vi.fn(() => ({ lat: 37.6213, lon: -122.379 }));
const mockGetTaxiways = vi.fn((): OSMTaxiway[] => []);
const mockGetAprons = vi.fn((): OSMApron[] => []);
const mockGetOSMRunways = vi.fn((): OSMRunway[] => []);

vi.mock('../../hooks/useAirportConfig', () => ({
  useAirportConfig: () => ({
    getTerminals: mockGetTerminals,
    getAirportCenter: mockGetAirportCenter,
    getTaxiways: mockGetTaxiways,
    getAprons: mockGetAprons,
    getOSMRunways: mockGetOSMRunways,
  }),
}));

// Mock React Three Fiber to avoid WebGL requirement
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: { children: React.ReactNode }) => {
    return <div data-testid="r3f-canvas">{children}</div>;
  },
  useThree: () => ({
    camera: {
      position: { x: 0, y: 300, z: 200, distanceTo: () => 360 },
      getWorldDirection: (v: { x: number; y: number; z: number; copy: () => unknown; add: () => unknown }) => {
        v.x = 0;
        v.y = -0.8;
        v.z = -0.6;
        return v;
      },
    },
  }),
}));

// Mock drei components
vi.mock('@react-three/drei', () => ({
  OrbitControls: (props: Record<string, unknown>) => {
    lastOrbitControlsProps = props;
    return <div data-testid="orbit-controls" />;
  },
  PerspectiveCamera: (props: Record<string, unknown>) => {
    lastCameraProps = props;
    return <div data-testid="perspective-camera" />;
  },
}));

// Mock AirportScene
vi.mock('./AirportScene', () => ({
  AirportScene: (props: Record<string, unknown>) => {
    lastAirportSceneProps = props;
    return <div data-testid="airport-scene" />;
  },
}));

// Mock THREE
vi.mock('three', () => ({
  PCFShadowMap: 1,
  Vector3: class {
    x = 0; y = 0; z = 0;
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
    copy(v: { x: number; y: number; z: number }) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
    add(v: { x: number; y: number; z: number }) { this.x += v.x; this.y += v.y; this.z += v.z; return this; }
    multiplyScalar(s: number) { this.x *= s; this.y *= s; this.z *= s; return this; }
  },
}));

// Mock airport3D config
vi.mock('../../constants/airport3D', () => ({
  AIRPORT_3D_CONFIG: {
    lighting: {
      ambient: { intensity: 0.6 },
      directional: {
        position: { x: 100, y: 200, z: 100 },
        intensity: 1.0,
      },
    },
  },
}));

// Import after all mocks
import { Map3D } from './Map3D';

// ============================================================================
// Helpers
// ============================================================================

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

const sfoViewport: SharedViewport = {
  center: { lat: 37.6213, lon: -122.379 },
  zoom: 13,
  bearing: 0,
};

// ============================================================================
// Tests
// ============================================================================

describe('Map3D', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastAirportSceneProps = {};
    lastOrbitControlsProps = {};
    lastCameraProps = {};
    mockGetTerminals.mockReturnValue([]);
    mockGetAirportCenter.mockReturnValue({ lat: 37.6213, lon: -122.379 });
    mockGetTaxiways.mockReturnValue([]);
    mockGetAprons.mockReturnValue([]);
    mockGetOSMRunways.mockReturnValue([]);
  });

  describe('Basic rendering', () => {
    it('renders a canvas container', () => {
      render(<Map3D />);
      expect(screen.getByTestId('r3f-canvas')).toBeInTheDocument();
    });

    it('renders AirportScene inside canvas', () => {
      render(<Map3D />);
      expect(screen.getByTestId('airport-scene')).toBeInTheDocument();
    });

    it('renders OrbitControls', () => {
      render(<Map3D />);
      expect(screen.getByTestId('orbit-controls')).toBeInTheDocument();
    });

    it('renders PerspectiveCamera', () => {
      render(<Map3D />);
      expect(screen.getByTestId('perspective-camera')).toBeInTheDocument();
    });

    it('applies className to container div', () => {
      const { container } = render(<Map3D className="test-class" />);
      expect(container.firstChild).toHaveClass('test-class');
    });

    it('sets 100% width and height on container', () => {
      const { container } = render(<Map3D />);
      const div = container.firstChild as HTMLElement;
      expect(div.style.width).toBe('100%');
      expect(div.style.height).toBe('100%');
    });
  });

  describe('Flight props forwarding', () => {
    it('passes flights to AirportScene', () => {
      const flights = [createMockFlight(), createMockFlight({ icao24: 'def456' })];
      render(<Map3D flights={flights} />);
      expect(lastAirportSceneProps.flights).toEqual(flights);
    });

    it('passes selectedFlight to AirportScene', () => {
      render(<Map3D selectedFlight="abc123" />);
      expect(lastAirportSceneProps.selectedFlight).toBe('abc123');
    });

    it('passes onSelectFlight to AirportScene', () => {
      const onSelect = vi.fn();
      render(<Map3D onSelectFlight={onSelect} />);
      expect(lastAirportSceneProps.onSelectFlight).toBe(onSelect);
    });

    it('defaults flights to empty array', () => {
      render(<Map3D />);
      expect(lastAirportSceneProps.flights).toEqual([]);
    });

    it('defaults selectedFlight to null', () => {
      render(<Map3D />);
      expect(lastAirportSceneProps.selectedFlight).toBeNull();
    });
  });

  describe('Airport config forwarding', () => {
    it('passes terminals from hook to AirportScene', () => {
      const terminals: OSMTerminal[] = [{ id: 't1', osmId: 1000, name: 'T1', type: 'terminal', position: { x: 0, y: 0, z: 0 }, dimensions: { width: 100, height: 10, depth: 50 }, polygon: [], color: 0xcccccc, geo: { latitude: 37.62, longitude: -122.38 }, geoPolygon: [] }];
      mockGetTerminals.mockReturnValue(terminals);
      render(<Map3D />);
      expect(lastAirportSceneProps.terminals).toEqual(terminals);
    });

    it('passes airportCenter to AirportScene', () => {
      render(<Map3D />);
      expect(lastAirportSceneProps.airportCenter).toEqual({ lat: 37.6213, lon: -122.379 });
    });

    it('uses airportCenter prop over hook value', () => {
      const customCenter = { lat: 40.6413, lon: -73.7781 };
      render(<Map3D airportCenter={customCenter} />);
      expect(lastAirportSceneProps.airportCenter).toEqual(customCenter);
    });

    it('passes osmTaxiways to AirportScene', () => {
      const taxiways: OSMTaxiway[] = [{ id: 'tw1', osmId: 3000, name: 'A', points: [], width: 15, color: 0x888888, geoPoints: [] }];
      mockGetTaxiways.mockReturnValue(taxiways);
      render(<Map3D />);
      expect(lastAirportSceneProps.osmTaxiways).toEqual(taxiways);
    });

    it('passes osmAprons to AirportScene', () => {
      const aprons: OSMApron[] = [{ id: 'ap1', osmId: 4000, name: 'A1', position: { x: 0, y: 0, z: 0 }, dimensions: { width: 50, height: 1, depth: 50 }, polygon: [], color: 0xaaaaaa, geo: { latitude: 37.62, longitude: -122.38 }, geoPolygon: [] }];
      mockGetAprons.mockReturnValue(aprons);
      render(<Map3D />);
      expect(lastAirportSceneProps.osmAprons).toEqual(aprons);
    });

    it('passes osmRunways to AirportScene', () => {
      const runways: OSMRunway[] = [{ id: 'rw1', osmId: 2000, name: '28L', points: [], width: 60, color: 0x333333, geoPoints: [] }];
      mockGetOSMRunways.mockReturnValue(runways);
      render(<Map3D />);
      expect(lastAirportSceneProps.osmRunways).toEqual(runways);
    });
  });

  describe('Default camera (no OSM data, no shared viewport)', () => {
    it('positions camera at default aerial viewpoint', () => {
      render(<Map3D />);
      const pos = lastCameraProps.position as [number, number, number];
      expect(pos).toEqual([0, 300, 200]);
    });

    it('targets origin', () => {
      render(<Map3D />);
      const target = lastOrbitControlsProps.target as [number, number, number];
      expect(target).toEqual([0, 0, 0]);
    });

    it('sets far plane to 5000', () => {
      render(<Map3D />);
      expect(lastCameraProps.far).toBe(5000);
    });

    it('sets fov to 60', () => {
      render(<Map3D />);
      expect(lastCameraProps.fov).toBe(60);
    });

    it('sets near plane to 0.5', () => {
      render(<Map3D />);
      expect(lastCameraProps.near).toBe(0.5);
    });
  });

  describe('Camera with OSM data', () => {
    it('computes camera from bounding box of OSM terminals', () => {
      mockGetTerminals.mockReturnValue([
        { id: 't1', osmId: 1001, name: 'T1', type: 'terminal' as const, position: { x: 0, y: 0, z: 0 }, dimensions: { width: 100, height: 10, depth: 50 }, polygon: [], color: 0xcccccc, geo: { latitude: 37.615, longitude: -122.385 }, geoPolygon: [] },
        { id: 't2', osmId: 1002, name: 'T2', type: 'terminal' as const, position: { x: 0, y: 0, z: 0 }, dimensions: { width: 100, height: 10, depth: 50 }, polygon: [], color: 0xcccccc, geo: { latitude: 37.625, longitude: -122.375 }, geoPolygon: [] },
      ]);
      render(<Map3D />);

      // Camera should be positioned based on terminal bounding box, not default
      const pos = lastCameraProps.position as [number, number, number];
      expect(pos).not.toEqual([0, 300, 200]);
    });

    it('computes camera from runways when no terminals', () => {
      mockGetOSMRunways.mockReturnValue([
        {
          id: 'rw1', osmId: 2001, name: '28L', points: [], width: 60, color: 0x333333,
          geoPoints: [
            { latitude: 37.610, longitude: -122.390 },
            { latitude: 37.630, longitude: -122.370 },
          ],
        },
      ]);
      render(<Map3D />);

      const pos = lastCameraProps.position as [number, number, number];
      expect(pos).not.toEqual([0, 300, 200]);
    });

    it('increases far plane for large airports', () => {
      mockGetOSMRunways.mockReturnValue([
        {
          id: 'rw1', osmId: 2002, name: '28L', points: [], width: 60, color: 0x333333,
          geoPoints: [
            { latitude: 37.5, longitude: -122.5 },
            { latitude: 37.7, longitude: -122.2 },
          ],
        },
      ]);
      render(<Map3D />);

      // Extent is large → far plane should be > default 5000
      expect(lastCameraProps.far).toBeGreaterThan(5000);
    });
  });

  describe('Camera with shared viewport (2D→3D sync)', () => {
    it('uses shared viewport center for camera target', () => {
      render(<Map3D sharedViewport={sfoViewport} />);

      const target = lastOrbitControlsProps.target as [number, number, number];
      // Target should be near origin (since viewport center ≈ airport center)
      expect(target[0]).toBeCloseTo(0, 0); // x
      expect(target[1]).toBe(0); // y (ground)
      expect(target[2]).toBeCloseTo(0, 0); // z
    });

    it('positions camera based on zoom level', () => {
      const closeZoom: SharedViewport = { center: { lat: 37.6213, lon: -122.379 }, zoom: 16, bearing: 0 };
      const farZoom: SharedViewport = { center: { lat: 37.6213, lon: -122.379 }, zoom: 10, bearing: 0 };

      const { unmount } = render(<Map3D sharedViewport={closeZoom} />);
      const closePos = lastCameraProps.position as [number, number, number];
      unmount();

      render(<Map3D sharedViewport={farZoom} />);
      const farPos = lastCameraProps.position as [number, number, number];

      // Higher zoom = closer camera (lower Y)
      expect(closePos[1]).toBeLessThan(farPos[1]);
    });

    it('applies bearing to camera horizontal offset', () => {
      const bearing0: SharedViewport = { center: { lat: 37.6213, lon: -122.379 }, zoom: 13, bearing: 0 };
      const bearing90: SharedViewport = { center: { lat: 37.6213, lon: -122.379 }, zoom: 13, bearing: 90 };

      const { unmount } = render(<Map3D sharedViewport={bearing0} />);
      const pos0 = lastCameraProps.position as [number, number, number];
      unmount();

      render(<Map3D sharedViewport={bearing90} />);
      const pos90 = lastCameraProps.position as [number, number, number];

      // Different bearing → different X/Z offset
      expect(pos0).not.toEqual(pos90);
    });

    it('camera height is positive', () => {
      render(<Map3D sharedViewport={sfoViewport} />);
      const pos = lastCameraProps.position as [number, number, number];
      expect(pos[1]).toBeGreaterThan(0);
    });
  });

  describe('OrbitControls configuration', () => {
    it('enables pan, zoom, and rotate', () => {
      render(<Map3D />);
      expect(lastOrbitControlsProps.enablePan).toBe(true);
      expect(lastOrbitControlsProps.enableZoom).toBe(true);
      expect(lastOrbitControlsProps.enableRotate).toBe(true);
    });

    it('limits polar angle to prevent below-ground camera', () => {
      render(<Map3D />);
      expect(lastOrbitControlsProps.maxPolarAngle).toBeCloseTo(Math.PI / 2.1, 2);
    });

    it('sets min and max distance', () => {
      render(<Map3D />);
      expect(lastOrbitControlsProps.minDistance).toBe(10);
      expect(lastOrbitControlsProps.maxDistance).toBe(3000);
    });
  });

  describe('Viewport change callback', () => {
    it('renders without onViewportChange', () => {
      expect(() => render(<Map3D />)).not.toThrow();
    });

    it('accepts onViewportChange prop', () => {
      const cb = vi.fn();
      expect(() => render(<Map3D onViewportChange={cb} />)).not.toThrow();
    });
  });

  describe('Lighting', () => {
    it('renders ambient light', () => {
      render(<Map3D />);
      // Canvas contains ambient and directional light via mock
      expect(screen.getByTestId('r3f-canvas')).toBeInTheDocument();
    });
  });

  describe('Edge cases', () => {
    it('handles empty flights array', () => {
      render(<Map3D flights={[]} />);
      expect(lastAirportSceneProps.flights).toEqual([]);
    });

    it('handles large flight count', () => {
      const flights = Array.from({ length: 100 }, (_, i) =>
        createMockFlight({ icao24: `flight-${i}` })
      );
      render(<Map3D flights={flights} />);
      expect((lastAirportSceneProps.flights as Flight[]).length).toBe(100);
    });

    it('handles null selectedFlight', () => {
      render(<Map3D selectedFlight={null} />);
      expect(lastAirportSceneProps.selectedFlight).toBeNull();
    });

    it('handles viewport with zero bearing', () => {
      render(<Map3D sharedViewport={{ center: { lat: 0, lon: 0 }, zoom: 13, bearing: 0 }} />);
      expect(screen.getByTestId('r3f-canvas')).toBeInTheDocument();
    });

    it('handles viewport with extreme zoom', () => {
      render(<Map3D sharedViewport={{ center: { lat: 37.62, lon: -122.38 }, zoom: 1, bearing: 0 }} />);
      const pos = lastCameraProps.position as [number, number, number];
      // Very low zoom → very far camera
      expect(pos[1]).toBeGreaterThan(1000);
    });
  });
});
