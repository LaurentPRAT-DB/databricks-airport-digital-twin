import { describe, it, expect, vi, beforeEach } from 'vitest';
import ReactThreeTestRenderer from '@react-three/test-renderer';
import { Trajectory3D } from './Trajectory3D';

// Mock useFlightContext
const mockUseFlightContext = vi.fn();
vi.mock('../../context/FlightContext', () => ({
  useFlightContext: () => mockUseFlightContext(),
}));

// Mock useTrajectory hook
const mockUseTrajectory = vi.fn();
vi.mock('../../hooks/useTrajectory', () => ({
  useTrajectory: (icao24: string | null, enabled: boolean) =>
    mockUseTrajectory(icao24, enabled),
}));

// Mock Line component from drei
vi.mock('@react-three/drei', async () => {
  const actual = await vi.importActual('@react-three/drei');
  return {
    ...actual,
    Line: ({ points: _points }: { points: unknown[] }) => (
      <mesh>
        <bufferGeometry />
        <meshBasicMaterial />
      </mesh>
    ),
  };
});

describe('Trajectory3D', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('When no flight is selected', () => {
    it('returns null when selectedFlight is null', async () => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: null,
        showTrajectory: true,
      });
      mockUseTrajectory.mockReturnValue({ data: null });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBe(0);
    });

    it('returns null when showTrajectory is false', async () => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: { icao24: 'abc123' },
        showTrajectory: false,
      });
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.6, longitude: -122.3, altitude: 1000 },
            { latitude: 37.7, longitude: -122.4, altitude: 2000 },
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBe(0);
    });
  });

  describe('When trajectory data is empty or invalid', () => {
    beforeEach(() => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: { icao24: 'abc123' },
        showTrajectory: true,
      });
    });

    it('returns null when trajectory is null', async () => {
      mockUseTrajectory.mockReturnValue({ data: null });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBe(0);
    });

    it('returns null when trajectory has no points', async () => {
      mockUseTrajectory.mockReturnValue({
        data: { points: [] },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBe(0);
    });

    it('returns null when trajectory has only one point', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [{ latitude: 37.6, longitude: -122.3, altitude: 1000 }],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBe(0);
    });

    it('filters out points with null coordinates', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.6, longitude: -122.3, altitude: 1000 },
            { latitude: null, longitude: -122.4, altitude: 2000 }, // Invalid
            { latitude: 37.8, longitude: null, altitude: 3000 }, // Invalid
          ],
        },
      });

      // Only one valid point, should return null
      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBe(0);
    });
  });

  describe('When trajectory data is valid', () => {
    beforeEach(() => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: { icao24: 'abc123' },
        showTrajectory: true,
      });
    });

    it('renders trajectory with 2 points', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.6, longitude: -122.3, altitude: 1000 },
            { latitude: 37.7, longitude: -122.4, altitude: 2000 },
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBeGreaterThan(0);

      // Should have a group containing trajectory elements
      const group = renderer.scene.children[0];
      expect(group.type).toBe('Group');
    });

    it('renders trajectory with multiple points', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.6, longitude: -122.3, altitude: 1000 },
            { latitude: 37.65, longitude: -122.35, altitude: 1500 },
            { latitude: 37.7, longitude: -122.4, altitude: 2000 },
            { latitude: 37.75, longitude: -122.45, altitude: 2500 },
            { latitude: 37.8, longitude: -122.5, altitude: 3000 },
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      const group = renderer.scene.children[0];

      // Should contain main line, point meshes, start point, and vertical lines
      expect(group.children.length).toBeGreaterThan(1);
    });

    it('renders start point (larger green sphere)', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.6, longitude: -122.3, altitude: 1000 },
            { latitude: 37.7, longitude: -122.4, altitude: 2000 },
            { latitude: 37.8, longitude: -122.5, altitude: 3000 },
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      const group = renderer.scene.children[0];

      // Find mesh elements (spheres at trajectory points)
      const meshes = group.children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      expect(meshes.length).toBeGreaterThan(0);
    });

    it('renders vertical lines for altitude visualization', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: Array(20)
            .fill(null)
            .map((_, i) => ({
              latitude: 37.6 + i * 0.01,
              longitude: -122.3 - i * 0.01,
              altitude: 1000 + i * 100,
            })),
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      const group = renderer.scene.children[0];

      // Should have multiple children including vertical lines
      expect(group.children.length).toBeGreaterThan(3);
    });
  });

  describe('Hook parameters', () => {
    it('calls useTrajectory with correct icao24', async () => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: { icao24: 'test123' },
        showTrajectory: true,
      });
      mockUseTrajectory.mockReturnValue({ data: null });

      await ReactThreeTestRenderer.create(<Trajectory3D />);

      expect(mockUseTrajectory).toHaveBeenCalledWith('test123', true);
    });

    it('calls useTrajectory with null when no flight selected', async () => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: null,
        showTrajectory: true,
      });
      mockUseTrajectory.mockReturnValue({ data: null });

      await ReactThreeTestRenderer.create(<Trajectory3D />);

      expect(mockUseTrajectory).toHaveBeenCalledWith(null, true);
    });

    it('disables useTrajectory when showTrajectory is false', async () => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: { icao24: 'test123' },
        showTrajectory: false,
      });
      mockUseTrajectory.mockReturnValue({ data: null });

      await ReactThreeTestRenderer.create(<Trajectory3D />);

      expect(mockUseTrajectory).toHaveBeenCalledWith('test123', false);
    });
  });

  describe('Coordinate conversion', () => {
    beforeEach(() => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: { icao24: 'abc123' },
        showTrajectory: true,
      });
    });

    it('handles points at different altitudes', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.6, longitude: -122.3, altitude: 0 }, // Ground level
            { latitude: 37.65, longitude: -122.35, altitude: 10000 }, // Cruising
            { latitude: 37.7, longitude: -122.4, altitude: 35000 }, // High altitude
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles points near the airport reference', async () => {
      // SFO reference: 37.6213, -122.379
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.62, longitude: -122.38, altitude: 500 },
            { latitude: 37.621, longitude: -122.379, altitude: 200 },
            { latitude: 37.6213, longitude: -122.379, altitude: 0 }, // At airport
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles points with undefined altitude', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.6, longitude: -122.3, altitude: undefined },
            { latitude: 37.7, longitude: -122.4, altitude: 2000 },
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      // Should still render (altitude defaults or handled gracefully)
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Mixed valid and invalid points', () => {
    beforeEach(() => {
      mockUseFlightContext.mockReturnValue({
        selectedFlight: { icao24: 'abc123' },
        showTrajectory: true,
      });
    });

    it('renders with some null coordinates filtered out', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: 37.6, longitude: -122.3, altitude: 1000 },
            { latitude: null, longitude: -122.35, altitude: 1500 }, // Filtered
            { latitude: 37.7, longitude: -122.4, altitude: 2000 },
            { latitude: 37.75, longitude: null, altitude: 2500 }, // Filtered
            { latitude: 37.8, longitude: -122.5, altitude: 3000 },
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      // Should render with 3 valid points
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('returns null when all points are filtered out', async () => {
      mockUseTrajectory.mockReturnValue({
        data: {
          points: [
            { latitude: null, longitude: -122.3, altitude: 1000 },
            { latitude: 37.7, longitude: null, altitude: 2000 },
          ],
        },
      });

      const renderer = await ReactThreeTestRenderer.create(<Trajectory3D />);
      expect(renderer.scene.children.length).toBe(0);
    });
  });
});
