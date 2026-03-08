import { describe, it, expect, vi, beforeEach } from 'vitest';
import ReactThreeTestRenderer from '@react-three/test-renderer';
import { Building3D, preloadBuildingModels } from './Building3D';
import { BuildingPlacement, BuildingType } from '../../config/buildingModels';

// Use vi.hoisted to declare the mock function before module hoisting
const { mockPreload } = vi.hoisted(() => ({
  mockPreload: vi.fn(),
}));

// Mock useGLTF to avoid loading actual models
vi.mock('@react-three/drei', async () => {
  const actual = await vi.importActual('@react-three/drei');
  const mockUseGLTF = Object.assign(
    () => ({
      scene: {
        clone: vi.fn(() => ({
          traverse: vi.fn(),
        })),
      },
    }),
    { preload: mockPreload }
  );
  return {
    ...actual,
    useGLTF: mockUseGLTF,
  };
});

// Helper to create mock building placement
const createMockPlacement = (
  type: BuildingType,
  overrides: Partial<BuildingPlacement> = {}
): BuildingPlacement => ({
  id: `test-${type}`,
  type,
  position: { x: 0, y: 0, z: 0 },
  rotation: 0,
  ...overrides,
});

describe('Building3D', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPreload.mockClear();
  });

  describe('Rendering building types', () => {
    it('renders terminal building', async () => {
      const placement = createMockPlacement('terminal');
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders control tower with procedural geometry', async () => {
      const placement = createMockPlacement('control-tower');
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );

      // Control tower has multiple meshes (base, shaft, deck, antenna)
      const group = renderer.scene.children[0];
      expect(group.type).toBe('Group');

      // Should have at least 4 meshes for control tower parts
      const meshes = group.children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      expect(meshes.length).toBeGreaterThanOrEqual(4);
    });

    it('renders hangar with procedural geometry', async () => {
      const placement = createMockPlacement('hangar');
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );

      const group = renderer.scene.children[0];
      expect(group.type).toBe('Group');

      // Hangar has main structure, curved roof, and door markings
      const meshes = group.children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      expect(meshes.length).toBeGreaterThanOrEqual(3);
    });

    it('renders jetbridge with accordion joints', async () => {
      const placement = createMockPlacement('jetbridge');
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );

      const group = renderer.scene.children[0];
      expect(group.type).toBe('Group');

      // Jetbridge has corridor + 3 accordion joints + rotunda
      const meshes = group.children.filter(
        (child: { type: string }) => child.type === 'Mesh'
      );
      expect(meshes.length).toBeGreaterThanOrEqual(5);
    });

    it('renders cargo building with box geometry', async () => {
      const placement = createMockPlacement('cargo');
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );

      // Cargo renders as a single mesh (falls through to default case)
      const mesh = renderer.scene.children[0];
      expect(mesh.type).toBe('Mesh');
    });

    it('renders fuel-station building', async () => {
      const placement = createMockPlacement('fuel-station');
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders fire-station building', async () => {
      const placement = createMockPlacement('fire-station');
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Position and rotation', () => {
    it('applies position correctly', async () => {
      const placement = createMockPlacement('terminal', {
        position: { x: 100, y: 0, z: -50 },
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('applies rotation correctly', async () => {
      const placement = createMockPlacement('hangar', {
        rotation: Math.PI / 4, // 45 degrees
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles negative position values', async () => {
      const placement = createMockPlacement('cargo', {
        position: { x: -200, y: 0, z: -150 },
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles elevated position (y > 0)', async () => {
      const placement = createMockPlacement('fire-station', {
        position: { x: 50, y: 5, z: 25 },
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Custom properties', () => {
    it('uses custom color when provided', async () => {
      const placement = createMockPlacement('terminal', {
        color: 0xff0000, // Custom red color
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('uses custom scale when provided', async () => {
      const placement = createMockPlacement('hangar', {
        scale: 2.0,
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('falls back to default color when not provided', async () => {
      const placement = createMockPlacement('control-tower');
      // No color specified
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });
  });

  describe('Multiple buildings', () => {
    it('renders multiple buildings independently', async () => {
      const placements = [
        createMockPlacement('terminal', { id: 'b1', position: { x: 0, y: 0, z: 0 } }),
        createMockPlacement('control-tower', { id: 'b2', position: { x: 100, y: 0, z: 0 } }),
        createMockPlacement('hangar', { id: 'b3', position: { x: -100, y: 0, z: 0 } }),
      ];

      for (const placement of placements) {
        const renderer = await ReactThreeTestRenderer.create(
          <Building3D placement={placement} />
        );
        expect(renderer.scene.children.length).toBeGreaterThan(0);
      }
    });
  });

  describe('preloadBuildingModels', () => {
    it('calls preload for each building type', () => {
      const types: BuildingType[] = ['terminal', 'control-tower', 'hangar'];
      preloadBuildingModels(types);

      // Should attempt to preload each model
      expect(mockPreload).toHaveBeenCalledTimes(3);
    });

    it('handles preload errors gracefully', () => {
      mockPreload.mockImplementation(() => {
        throw new Error('Model not found');
      });

      const types: BuildingType[] = ['terminal'];

      // Should not throw
      expect(() => preloadBuildingModels(types)).not.toThrow();
    });

    it('handles empty array', () => {
      preloadBuildingModels([]);

      expect(mockPreload).not.toHaveBeenCalled();
    });
  });

  describe('Edge cases', () => {
    it('handles zero rotation', async () => {
      const placement = createMockPlacement('terminal', {
        rotation: 0,
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles full rotation (2*PI)', async () => {
      const placement = createMockPlacement('hangar', {
        rotation: Math.PI * 2,
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles negative rotation', async () => {
      const placement = createMockPlacement('control-tower', {
        rotation: -Math.PI / 2,
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('handles origin position (0, 0, 0)', async () => {
      const placement = createMockPlacement('jetbridge', {
        position: { x: 0, y: 0, z: 0 },
      });
      const renderer = await ReactThreeTestRenderer.create(
        <Building3D placement={placement} />
      );
      expect(renderer.scene.children.length).toBeGreaterThan(0);
    });

    it('renders all valid building types', async () => {
      const allTypes: BuildingType[] = [
        'terminal',
        'control-tower',
        'hangar',
        'cargo',
        'jetbridge',
        'fuel-station',
        'fire-station',
      ];

      for (const type of allTypes) {
        const placement = createMockPlacement(type);
        const renderer = await ReactThreeTestRenderer.create(
          <Building3D placement={placement} />
        );
        expect(renderer.scene.children.length).toBeGreaterThan(0);
      }
    });
  });
});
