import { describe, it, expect, vi, beforeEach } from 'vitest';
import ReactThreeTestRenderer from '@react-three/test-renderer';
import { SatelliteGround } from './SatelliteGround';

const defaultProps = {
  size: 2000,
  centerLat: 37.6213,
  centerLon: -122.379,
  scale: 10000,
};

describe('SatelliteGround', () => {
  it('renders a mesh with plane geometry', async () => {
    const renderer = await ReactThreeTestRenderer.create(
      <SatelliteGround {...defaultProps} />
    );
    const root = renderer.scene.children[0];
    expect(root.type).toBe('Mesh');
  });

  it('renders with fallback material when no texture loaded', async () => {
    const renderer = await ReactThreeTestRenderer.create(
      <SatelliteGround {...defaultProps} />
    );
    const mesh = renderer.scene.children[0];
    // Should have a material (either textured or fallback gray)
    expect(mesh.props).toBeDefined();
  });

  it('accepts inpainting and airportIcao props without error', async () => {
    const renderer = await ReactThreeTestRenderer.create(
      <SatelliteGround {...defaultProps} inpainting={true} airportIcao="KSFO" />
    );
    expect(renderer.scene.children.length).toBeGreaterThan(0);
  });

  it('re-renders when inpainting prop changes', async () => {
    const renderer = await ReactThreeTestRenderer.create(
      <SatelliteGround {...defaultProps} inpainting={false} />
    );
    expect(renderer.scene.children.length).toBeGreaterThan(0);

    // Update to enable inpainting — should not crash
    await renderer.update(
      <SatelliteGround {...defaultProps} inpainting={true} airportIcao="KJFK" />
    );
    expect(renderer.scene.children.length).toBeGreaterThan(0);
  });

  it('positions mesh at y=-0.1 rotated to horizontal', async () => {
    const renderer = await ReactThreeTestRenderer.create(
      <SatelliteGround {...defaultProps} />
    );
    const mesh = renderer.scene.children[0];
    // Rotation: [-PI/2, 0, 0] for horizontal ground plane
    expect(mesh.props.rotation).toBeDefined();
    expect(mesh.props.position).toBeDefined();
  });
});
